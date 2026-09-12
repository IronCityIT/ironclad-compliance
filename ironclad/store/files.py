"""A NAS volume, used as the result store.

The reference implementation, and the one that works today: no database, no
credential, no network. It writes the same rows the MariaDB store writes, laid
out as files under a tenant prefix, which is the shape a NAS-backed volume
takes:

    <root>/<tenant_id>/assessments/<assessment_id>/assessment.json
    <root>/<tenant_id>/assessments/<assessment_id>/rows/<table>.json
    <root>/<tenant_id>/audit.jsonl

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
from pathlib import Path
from typing import Any

from ironclad.ids import is_safe_document_id
from ironclad.store.base import StoreError
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
        items.sort(key=lambda row: (int(row.get("priority", 0)), str(row.get("due_date", ""))))
        return items[:limit]

    def list_audit(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        events = self._read_audit(tenant_id)
        return events[-limit:] if limit else events

    # ----------------------------------------------------------------- health

    def health(self) -> dict[str, Any]:
        """Whether this volume can actually be written to.

        Checked by writing, not by looking: a NAS volume that is mounted
        read-only, or not mounted at all so the mount point is an empty local
        directory, both look fine to a stat.
        """
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".ironclad-write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return {"store": "file", "root": str(self.root), "writable": False, "detail": str(exc)}
        return {"store": "file", "root": str(self.root), "writable": True, "detail": ""}
