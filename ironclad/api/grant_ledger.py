"""Who granted and who revoked each service token, kept after the entry is gone.

`tokens issue` writes `issued_by` into the token-file entry, and `tokens
revoke` prints `revoked_by` and removes the entry: once a grant was revoked,
nothing on the server said it had ever existed, and a hand-edited entry looked
exactly like an issued one. HIPAA's access-authorization and termination
procedures (164.308(a)(4)(ii)(B)-(C), (a)(3)(ii)(C)) want the grant and the
removal on record, and the audit-controls standard (164.312(b)) wants that
record to be one that cannot be quietly rewritten.

The ledger is one JSON object per line beside the token file (`tokens.json.ledger`
by default), written by `issue` and `revoke` under the token file's lock and
before the token file is replaced, so no edit lands unrecorded. Each line
carries the digest of the line before it, the same chain as the access log.
A line holds the time, the action, who took it, the user, tenant, roles and
expiry of the entry, and the entry's `sha256` (the digest the token file
already stores; never the token).

`reconcile()` holds a token file to its ledger for `tokens review --ledger`:
an entry with no grant on record, one that differs from its grant, or one
revoked and back in the file is high; a grant with neither an entry nor a
revocation is a notice.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ironclad.api.access_log import (
    GENESIS_HASH,
    AccessLogError,
    line_digest,
    read_lines,
    verify_lines,
)

#: The keys every line carries, in addition to `hash`.
FIELDS = (
    "seq",
    "at",
    "as_of",
    "action",
    "actor",
    "user_id",
    "tenant_id",
    "roles",
    "expires_at",
    "sha256",
    "prev_hash",
)

ACTIONS = ("issue", "revoke")

#: The entry fields a grant fixes. An entry that differs from its grant on
#: any of them was edited by hand after it was issued.
GRANTED = ("user_id", "tenant_id", "roles", "expires_at")

KIND = "a grant-ledger entry"


class GrantLedgerError(Exception):
    """The ledger cannot be read, is not a chain, or cannot be written."""


def default_path(token_file: Path) -> Path:
    return token_file.with_name(token_file.name + ".ledger")


def verify_file(path: Path | str) -> dict[str, Any]:
    """The verdict on one ledger. A missing file is an empty, whole chain."""
    try:
        return verify_lines(read_lines(Path(path)), FIELDS, KIND)
    except AccessLogError as exc:
        raise GrantLedgerError(str(exc)) from exc


def read_file(path: Path | str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The verdict and, only if the ledger is a whole chain, its entries."""
    try:
        lines = read_lines(Path(path))
    except AccessLogError as exc:
        raise GrantLedgerError(str(exc)) from exc
    verdict = verify_lines(lines, FIELDS, KIND)
    if not verdict["verified"]:
        return verdict, []
    return verdict, [json.loads(line) for line in lines]


def _granted(entry: dict[str, Any]) -> dict[str, Any]:
    """The fields a grant fixes, normalised as `issue_token` writes them."""
    roles = entry.get("roles")
    return {
        "user_id": str(entry.get("user_id", "")).strip(),
        "tenant_id": str(entry.get("tenant_id", "")).strip(),
        "roles": sorted({str(r) for r in roles}) if isinstance(roles, list) else roles,
        "expires_at": entry.get("expires_at"),
    }


class GrantLedger:
    """Appends chained lines. Held only under the token file's lock.

    Opening re-checks the whole file and refuses one that is not a whole
    chain, as the access log does: an edit recorded after a break would verify
    from a head nobody can trust.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        verdict = verify_file(self.path)
        if not verdict["verified"]:
            raise GrantLedgerError(
                f"{self.path} is not a whole chain at line {verdict['broken_at']} "
                f"({verdict['reason']}); keep it as evidence and start a new ledger"
            )
        self._seq = verdict["entries"]
        self._head = verdict["head"]

    @property
    def head(self) -> str:
        return self._head

    @property
    def anchor(self) -> str:
        """`N:DIGEST` for the ledger as it stands, for `verify-ledger --anchor`."""
        return f"{self._seq}:{self._head}" if self._seq else ""

    def record(
        self,
        action: str,
        entries: list[dict[str, Any]],
        *,
        actor: str,
        as_of: date,
        at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Append one line per entry and make them durable before returning.

        Raises `GrantLedgerError` if they cannot be written; the caller then
        leaves the token file as it was.
        """
        if action not in ACTIONS:
            raise GrantLedgerError(f"unknown action {action!r}")
        moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        stamp = moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        seq, head = self._seq, self._head
        lines: list[str] = []
        written: list[dict[str, Any]] = []
        for entry in entries:
            seq += 1
            line: dict[str, Any] = {
                "seq": seq,
                "at": stamp,
                "as_of": as_of.isoformat(),
                "action": action,
                "actor": actor,
                **_granted(entry),
                "sha256": str(entry.get("sha256", "")).strip().lower(),
                "prev_hash": head,
            }
            line["hash"] = line_digest(line, FIELDS)
            head = line["hash"]
            lines.append(json.dumps(line, sort_keys=True, separators=(",", ":")))
            written.append(line)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as handle:
                handle.write("".join(text + "\n" for text in lines))
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise GrantLedgerError(f"cannot append to {self.path}: {exc}") from exc
        self._seq, self._head = seq, head
        return written


def reconcile(document: object, ledger: list[dict[str, Any]]) -> dict[str, Any]:
    """Hold a token file's entries to the grants and revocations on record.

    Returns `findings`, a list per file position (high-level messages), and
    `unrecorded`: grants whose entry is gone without a revocation on record.
    """
    last: dict[str, dict[str, Any]] = {}
    for line in ledger:
        last[line["sha256"]] = line
    entries = document.get("tokens") if isinstance(document, dict) else None
    entries = entries if isinstance(entries, list) else []

    findings: list[list[str]] = []
    granted_by: list[dict[str, str] | None] = []
    present: set[str] = set()
    for entry in entries:
        messages: list[str] = []
        grant: dict[str, str] | None = None
        if isinstance(entry, dict):
            digest = str(entry.get("sha256", "")).strip().lower()
            present.add(digest)
            event = last.get(digest)
            if event is None:
                messages.append(
                    "no grant on record in the ledger: written by hand or before the ledger; "
                    "revoke it and issue a replacement with `tokens issue`"
                )
            elif event["action"] == "revoke":
                messages.append(
                    f"revoked {event['at']} by {event['actor']} and back in the file; "
                    "remove it and find out who restored it"
                )
            else:
                held = _granted(entry)
                changed = [f for f in GRANTED if held[f] != event[f]]
                if changed:
                    messages.append(
                        "differs from its grant of "
                        f"{event['as_of']} by {event['actor']} in "
                        + ", ".join(f"{f} (granted {event[f]!r}, now {held[f]!r})" for f in changed)
                        + "; revoke it and issue what was meant"
                    )
                else:
                    grant = {"granted_by": event["actor"], "granted_at": event["at"]}
        findings.append(messages)
        granted_by.append(grant)

    unrecorded = [
        {
            "user_id": event["user_id"],
            "tenant_id": event["tenant_id"],
            "digest_prefix": digest[:12],
            "granted_by": event["actor"],
            "granted_at": event["at"],
            "message": (
                "granted and not in the token file, with no revocation on record: the "
                "write did not land, or the entry was removed without `tokens revoke`"
            ),
        }
        for digest, event in last.items()
        if event["action"] == "issue" and digest not in present
    ]
    return {"findings": findings, "granted": granted_by, "unrecorded": unrecorded}


__all__ = [
    "ACTIONS",
    "FIELDS",
    "GENESIS_HASH",
    "GrantLedger",
    "GrantLedgerError",
    "default_path",
    "read_file",
    "reconcile",
    "verify_file",
]
