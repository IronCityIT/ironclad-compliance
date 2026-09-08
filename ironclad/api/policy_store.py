"""A tenant policy file, used as the store behind the service API.

`ComplianceService` implements the whole risk-acceptance workflow — request,
approve with separation of duties, revoke, expire, every step audited — against
a `Store`. The only implementation was `InMemoryStore`, which forgets everything
when the process ends, so the workflow was reachable from tests and from nowhere
else. The one way an acceptance could reach a real assessment was somebody
hand-editing `policy.json`.

This is the missing half. The policy file is already the pipeline's input for
acceptances, so writing back to it closes the loop: request, approve, and the
next `ironclad assess` honours it.

Two decisions worth stating:

**The file is the record, not a cache.** Every call re-reads it. Two people
working on the same policy see each other's changes, and nothing is held in a
process that might not be the only one running.

**The audit trail is hash-chained and lives beside the policy**, not inside it.
`policy.json` is an input a human edits; an append-only record of who approved
what is not. They are separate files for the same reason a ledger is not kept in
the margin of the document it describes.

Assessments are not this store's business, and this store does not pretend they
might be. It implements `ComplianceService`'s `PolicyRecords` and nothing else;
results go to an `ironclad.store.ResultStore` — a volume or MariaDB. A service
handed only this reports that plainly when asked for an assessment, rather than
raising from inside a persist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ironclad.errors import IroncladError
from ironclad.model.exception import RiskException
from ironclad.policy import POLICY_VERSION, policy_from_document, validate_policy

AUDIT_SUFFIX = ".audit.json"


class PolicyStore:
    """Reads and writes one tenant's policy file and its audit sidecar."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.audit_path = self.path.with_name(self.path.name + AUDIT_SUFFIX)

    # ------------------------------------------------------------------ policy

    def document(self) -> dict[str, Any]:
        """The policy document, or an empty one if the file does not exist yet."""
        if not self.path.exists():
            return {
                "policy_version": POLICY_VERSION,
                "tenant_id": "",
                "scope_exclusions": [],
                "exceptions": [],
                "owners": {},
            }
        document = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise IroncladError(f"{self.path} is not a policy document")
        return document

    def tenant_id(self) -> str:
        return str(self.document().get("tenant_id", "")).strip()

    def _write(self, document: dict[str, Any]) -> None:
        # Validated before it lands. A store that can write a policy the loader
        # will later refuse turns one bad command into an assessment that cannot
        # run at all.
        errors = validate_policy(document)
        if errors:
            raise IroncladError(
                "refusing to write a policy that would not load: " + "; ".join(errors)
            )
        self.path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------- exceptions

    def list_exceptions(self, tenant_id: str) -> list[RiskException]:
        document = self.document()
        if str(document.get("tenant_id", "")).strip() != tenant_id:
            return []
        return policy_from_document(document).exceptions

    def get_exception(self, tenant_id: str, exception_id: str) -> RiskException | None:
        for exception in self.list_exceptions(tenant_id):
            if exception.exception_id == exception_id:
                return exception
        return None

    def save_exception(self, tenant_id: str, exception: RiskException) -> None:
        document = self.document()
        if not str(document.get("tenant_id", "")).strip():
            document["tenant_id"] = tenant_id
        if str(document["tenant_id"]).strip() != tenant_id:
            raise IroncladError(
                f"{self.path} belongs to tenant {document['tenant_id']!r}, not {tenant_id!r}"
            )

        record = _policy_entry(exception)
        entries = list(document.get("exceptions", []))
        for index, existing in enumerate(entries):
            if str(existing.get("exception_id", "")) == exception.exception_id:
                entries[index] = record
                break
        else:
            entries.append(record)
        document["exceptions"] = entries
        document.setdefault("policy_version", POLICY_VERSION)
        document.setdefault("scope_exclusions", [])
        document.setdefault("owners", {})
        self._write(document)

    # ------------------------------------------------------------------ audit

    def append_audit(self, tenant_id: str, events: list[dict[str, Any]]) -> None:
        stored = self._audit_document(tenant_id)
        stored["events"].extend(events)
        stored["event_count"] = len(stored["events"])
        stored["head"] = stored["events"][-1]["hash"] if stored["events"] else ""
        self.audit_path.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")

    def list_audit(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        events = self._audit_document(tenant_id)["events"]
        return events[-limit:] if limit else events

    def _audit_document(self, tenant_id: str) -> dict[str, Any]:
        if not self.audit_path.exists():
            return {"tenant_id": tenant_id, "event_count": 0, "head": "", "events": []}
        document = json.loads(self.audit_path.read_text(encoding="utf-8"))
        events = document.get("events")
        if not isinstance(document, dict) or not isinstance(events, list):
            raise IroncladError(f"{self.audit_path} is not an audit trail")
        return document


def _policy_entry(exception: RiskException) -> dict[str, Any]:
    """One acceptance in the shape `policy.json` carries.

    `RiskException.to_dict()` is the API shape and includes derived fields —
    `active`, `days_remaining` — that are computed at read time and would be
    stale the moment they were written to a file.
    """
    entry: dict[str, Any] = {
        "exception_id": exception.exception_id,
        "control_id": exception.control_id,
        "justification": exception.justification,
        "requested_by": exception.requested_by,
        "requested_at": _iso(exception.requested_at),
        "compensating_controls": list(exception.compensating_controls),
        "status": str(exception.status),
    }
    if exception.approved_by:
        entry["approved_by"] = exception.approved_by
    if exception.approved_at:
        entry["approved_at"] = _iso(exception.approved_at)
    if exception.expires_at:
        entry["expires_at"] = _iso(exception.expires_at)
    if exception.review_notes:
        entry["note"] = exception.review_notes[-1]
    return entry


def _iso(moment: Any) -> str:
    from ironclad.ids import iso  # noqa: PLC0415 — keeps this module import-light

    return iso(moment)
