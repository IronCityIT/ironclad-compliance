"""A NAS volume, used as the result store.

The reference implementation, and the one that works today: no database, no
credential, no network. It writes the same rows the MariaDB store writes, laid
out as files under a tenant prefix, which is the shape a NAS-backed volume
takes:

    <root>/<tenant_id>/assessments/<assessment_id>/assessment.json
    <root>/<tenant_id>/assessments/<assessment_id>/rows/<table>.json
    <root>/<tenant_id>/audit.jsonl
    <root>/<tenant_id>/oversight/<kind>/<record_id>/<revision>.json

Two reasons this is not a stopgap. Artifact files — reports, auditor packages,
evidence — belong on a volume rather than in a database whatever else happens,
so this layout is target-state for them regardless. And it is what lets the
storage contract be tested end to end before a database credential exists, which
is the difference between a migration that is designed and one that is guessed.

The audit trail is a separate append-only file, never rewritten. Everything else
for one assessment lives under that assessment's directory, so re-storing it
replaces exactly that assessment and touches nothing else.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ironclad.ids import is_safe_document_id
from ironclad.oversight import (
    StaleRevisionError,
    check_kind,
    check_record_id,
    check_stored,
    verify_history,
)
from ironclad.store.base import StoreError, verify_stored_chains
from ironclad.store.rows import TABLES, rows_from_document

AUDIT_FILE = "audit.jsonl"


class FileResultStore:
    """Result storage on a filesystem, partitioned by tenant."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -------------------------------------------------------------- internals

    def _tenant_dir(self, tenant_id: str) -> Path:
        # The tenant id becomes a path segment, so it is checked rather than
        # trusted: a value containing a separator would escape its own prefix
        # and land in another tenant's tree.
        if not is_safe_document_id(tenant_id):
            raise StoreError(f"{tenant_id!r} is not a usable tenant directory name")
        return self.root / tenant_id

    def _assessment_dir(self, tenant_id: str, assessment_id: str) -> Path:
        if not is_safe_document_id(assessment_id):
            raise StoreError(f"{assessment_id!r} is not a usable assessment directory name")
        return self._tenant_dir(tenant_id) / "assessments" / assessment_id

    @staticmethod
    def _write(path: Path, content: str) -> None:
        """Write through a temporary file in the same directory, then rename.

        A half-written assessment.json is worse than none: it reads as a corrupt
        record rather than a missing one. The rename is atomic on the same
        filesystem, so a reader sees either the old file or the new one.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
        )
        try:
            with handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------ write

    def put_assessment(self, document: dict[str, Any]) -> str:
        rows = rows_from_document(document)
        target = self._assessment_dir(rows.tenant_id, rows.assessment_id)

        self._write(target / "assessment.json", json.dumps(document, indent=2) + "\n")
        for table in TABLES:
            if table == "audit_events":
                continue
            self._write(
                target / "rows" / f"{table}.json",
                json.dumps(rows.table(table), indent=2) + "\n",
            )

        # Append-only, and only what is not already there. Re-storing the same
        # assessment must not duplicate its trail, and must never rewrite an
        # event that is already recorded.
        self._append_audit(rows.tenant_id, rows.assessment_id, rows.audit_events)
        return rows.assessment_id

    def _append_audit(
        self, tenant_id: str, assessment_id: str, events: list[dict[str, Any]]
    ) -> None:
        if not events:
            return
        path = self._tenant_dir(tenant_id) / AUDIT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        seen = {
            (event.get("assessment_id"), event.get("event_id"))
            for event in self._read_audit(tenant_id)
        }
        fresh = [e for e in events if (assessment_id, e.get("event_id")) not in seen]
        if not fresh:
            return
        with path.open("a", encoding="utf-8") as handle:
            for event in fresh:
                handle.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    # ------------------------------------------------------------------- read

    def _read_audit(self, tenant_id: str) -> list[dict[str, Any]]:
        path = self._tenant_dir(tenant_id) / AUDIT_FILE
        if not path.exists():
            return []
        events = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise StoreError(f"{path}: line {number} is not a valid audit event") from exc
        return events

    def _summary(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        rows = json.loads(path.read_text(encoding="utf-8"))
        return rows[0] if rows else None

    def get_assessment(self, tenant_id: str, assessment_id: str) -> dict[str, Any] | None:
        return self._summary(
            self._assessment_dir(tenant_id, assessment_id) / "rows" / "assessments.json"
        )

    def list_controls(self, tenant_id: str, assessment_id: str) -> list[dict[str, Any]]:
        """The projected control rows, as the MariaDB store lists them."""
        path = self._assessment_dir(tenant_id, assessment_id) / "rows" / "assessment_controls.json"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        return sorted(rows, key=lambda row: str(row.get("control_id", "")))

    def get_document(self, tenant_id: str, assessment_id: str) -> dict[str, Any] | None:
        """The complete stored document, as it was written."""
        path = self._assessment_dir(tenant_id, assessment_id) / "assessment.json"
        if not path.exists():
            return None
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return document

    def list_assessments(self, tenant_id: str, limit: int = 25) -> list[dict[str, Any]]:
        base = self._tenant_dir(tenant_id) / "assessments"
        if not base.is_dir():
            return []
        found = []
        for directory in base.iterdir():
            summary = self._summary(directory / "rows" / "assessments.json")
            if summary:
                found.append(summary)
        found.sort(key=lambda row: str(row.get("started_at", "")), reverse=True)
        return found[:limit]

    def list_remediation(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """The tenant's current queue: the most recent assessment's items.

        Not every item ever raised. A control outstanding in March and again in
        June is one piece of work, and returning it twice would make the queue
        grow every time an assessment is re-run.
        """
        latest = self.list_assessments(tenant_id, limit=1)
        if not latest:
            return []
        path = (
            self._assessment_dir(tenant_id, str(latest[0]["assessment_id"]))
            / "rows"
            / "remediation_items.json"
        )
        if not path.exists():
            return []
        items: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        # The plan's own order: most urgent first, ties by control id
        # (RemediationPlan.ordered). The same rule as the MariaDB query.
        items.sort(
            key=lambda row: (-float(row.get("priority") or 0), str(row.get("control_id", "")))
        )
        return items[:limit]

    def list_audit(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        events = self._read_audit(tenant_id)
        return events[-limit:] if limit else events

    def verify_audit_chain(self, tenant_id: str) -> dict[str, Any]:
        """Re-verify every assessment's chain in this tenant's trail, as stored."""
        return verify_stored_chains(self._read_audit(tenant_id), tenant_id)

    # ------------------------------------------------- partner/integration register

    def _oversight_dir(self, tenant_id: str, kind: str, record_id: str | None = None) -> Path:
        base = self._tenant_dir(tenant_id) / "oversight" / check_kind(kind)
        return base if record_id is None else base / check_record_id(record_id)

    def put_oversight(
        self, tenant_id: str, kind: str, record_id: str, record: dict[str, Any]
    ) -> None:
        """Store the next revision of one record, and its history, as one step.

        On a volume the history *is* the record: each revision is a file named
        for its number, created exclusively, and the current record is the
        highest. So there is no moment at which a record exists without its
        entry, and two writers at the same revision cannot both land — the
        second `link` finds the name taken and is refused as stale.
        """
        check_stored(tenant_id, record)
        directory = self._oversight_dir(tenant_id, kind, record_id)
        revision = int(record["revision"])
        latest = self._oversight_revisions(directory)
        current = latest[-1] if latest else 0
        if revision != current + 1:
            raise StaleRevisionError(
                f"{kind}/{record_id} is at revision {current}; revision {revision} cannot follow it"
            )
        directory.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        try:
            with handle:
                handle.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            # A hard link fails if the name exists, and appears whole or not
            # at all: an exclusive, atomic create of a complete file.
            os.link(handle.name, directory / f"{revision}.json")
        except FileExistsError as exc:
            raise StaleRevisionError(
                f"{kind}/{record_id} revision {revision} was saved by someone else first"
            ) from exc
        except OSError as exc:
            raise StoreError(f"cannot write {kind}/{record_id}: {exc}") from exc
        finally:
            Path(handle.name).unlink(missing_ok=True)

    @staticmethod
    def _oversight_revisions(directory: Path) -> list[int]:
        if not directory.is_dir():
            return []
        return sorted(int(p.stem) for p in directory.glob("*.json") if p.stem.isdigit())

    def _oversight_entry(self, directory: Path, revision: int) -> dict[str, Any]:
        path = directory / f"{revision}.json"
        try:
            entry: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"{path} is not a readable register entry") from exc
        return entry

    def get_oversight(self, tenant_id: str, kind: str, record_id: str) -> dict[str, Any] | None:
        directory = self._oversight_dir(tenant_id, kind, record_id)
        revisions = self._oversight_revisions(directory)
        return self._oversight_entry(directory, revisions[-1]) if revisions else None

    def list_oversight(self, tenant_id: str, kind: str) -> list[dict[str, Any]]:
        """Every record of one kind in one tenant, current revision, by name."""
        base = self._oversight_dir(tenant_id, kind)
        if not base.is_dir():
            return []
        found = []
        for directory in base.iterdir():
            revisions = self._oversight_revisions(directory)
            if revisions:
                found.append(
                    {"id": directory.name, **self._oversight_entry(directory, revisions[-1])}
                )
        found.sort(key=lambda r: (str(r.get("name", "")).lower(), r["id"]))
        return found

    def oversight_ids(self, tenant_id: str, kind: str) -> list[str]:
        """Every record id of one kind with a record or any history, sorted."""
        base = self._oversight_dir(tenant_id, kind)
        if not base.is_dir():
            return []
        return sorted(d.name for d in base.iterdir() if self._oversight_revisions(d))

    def oversight_history(self, tenant_id: str, kind: str, record_id: str) -> list[dict[str, Any]]:
        """Every revision of one record, oldest first, exactly as written."""
        directory = self._oversight_dir(tenant_id, kind, record_id)
        return [self._oversight_entry(directory, n) for n in self._oversight_revisions(directory)]

    def verify_oversight(self, tenant_id: str, kind: str, record_id: str) -> dict[str, Any]:
        return verify_history(
            self.get_oversight(tenant_id, kind, record_id),
            self.oversight_history(tenant_id, kind, record_id),
            tenant_id,
        )

    # ----------------------------------------------------------------- health

    def health(self) -> dict[str, Any]:
        """Whether this volume can actually be written to.

        Checked by writing, not by looking: a NAS volume that is mounted
        read-only, or not mounted at all so the mount point is an empty local
        directory, both look fine to a stat.
        """
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            # One name per check: a shared name let two overlapping checks
            # race, one unlinking the other's file, and the loser reported a
            # writable volume as read-only (PRODUCTIZE_NOTES §16.44).
            probe = self.root / f".ironclad-write-probe-{uuid.uuid4().hex}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return {"store": "file", "root": str(self.root), "writable": False, "detail": str(exc)}
        return {"store": "file", "root": str(self.root), "writable": True, "detail": ""}
