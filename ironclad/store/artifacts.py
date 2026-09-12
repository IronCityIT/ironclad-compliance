"""The deliverables, on a NAS-backed volume.

The target architecture splits persistence in two: relational state in MariaDB,
object and artifact files on a volume. `rows.py` and the result stores handle the
first. This handles the second — the report a client is issued, the auditor
package, and anything else that is a file rather than a row.

Kept separate from the record store on purpose. A database is the wrong place for
a 300 KB HTML document and a directory of CSVs, and a volume is the wrong place to
query a readiness score from, so the two are different objects with different
jobs rather than one store pretending to do both. A MariaDB deployment uses this
alongside the database; a volume-only deployment uses the same volume for both,
and the layout is chosen so that works without a second root.

    <root>/<tenant>/assessments/<assessment_id>/artifacts/…

Every stored file is checksummed into a manifest. A deliverable that cannot be
shown to be the one that was issued is not evidence of anything, which is the
same argument the evidence index makes about the client's own documents.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ironclad.ids import is_safe_document_id, iso, utc_now
from ironclad.store.base import StoreError

MANIFEST = "artifacts.json"
MANIFEST_VERSION = "1.0"


@dataclass(frozen=True)
class StoredArtifact:
    """One file as stored, and how to recognise it again."""

    name: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size_bytes": self.size_bytes, "sha256": self.sha256}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ArtifactStore:
    """Deliverable files on a volume, partitioned by tenant."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -------------------------------------------------------------- internals

    def _dir(self, tenant_id: str, assessment_id: str) -> Path:
        # Both become path segments, so both are checked rather than trusted.
        if not is_safe_document_id(tenant_id):
            raise StoreError(f"{tenant_id!r} is not a usable tenant directory name")
        if not is_safe_document_id(assessment_id):
            raise StoreError(f"{assessment_id!r} is not a usable assessment directory name")
        return self.root / tenant_id / "assessments" / assessment_id / "artifacts"

    @staticmethod
    def _write(path: Path, content: str) -> None:
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

    def put(self, tenant_id: str, assessment_id: str, source: Path | str) -> list[StoredArtifact]:
        """Store a file, or every file in a directory, keeping its layout.

        Replaces what was there for that assessment. A re-issued report is the
        report; keeping the previous one beside it under a different name is how
        two versions of a client's deliverable end up in circulation.
        """
        origin = Path(source)
        if not origin.exists():
            raise StoreError(f"nothing to store: {origin} does not exist")

        target = self._dir(tenant_id, assessment_id)
        files = (
            [origin] if origin.is_file() else sorted(p for p in origin.rglob("*") if p.is_file())
        )
        if not files:
            raise StoreError(f"nothing to store: {origin} holds no files")

        stored: list[StoredArtifact] = []
        for path in files:
            resolved = path.resolve(strict=False)
            if not origin.is_file() and not resolved.is_relative_to(origin.resolve()):
                # A symlink out of the directory being published. Skipped, not
                # followed: a deliverable set must contain only what was issued.
                continue
            relative = Path(path.name) if origin.is_file() else path.relative_to(origin)
            landing = target / relative
            landing.parent.mkdir(parents=True, exist_ok=True)
            landing.write_bytes(resolved.read_bytes())
            stored.append(
                StoredArtifact(
                    name=relative.as_posix(),
                    size_bytes=landing.stat().st_size,
                    sha256=_sha256(landing),
                )
            )

        if not stored:
            raise StoreError(f"nothing was stored from {origin}: every item resolved outside it")

        self._write(
            target / MANIFEST,
            json.dumps(
                {
                    "manifest_version": MANIFEST_VERSION,
                    "tenant_id": tenant_id,
                    "assessment_id": assessment_id,
                    "stored_at": iso(utc_now()),
                    "artifacts": [a.to_dict() for a in stored],
                },
                indent=2,
            )
            + "\n",
        )
        return stored

    # ------------------------------------------------------------------- read

    def manifest(self, tenant_id: str, assessment_id: str) -> dict[str, Any] | None:
        path = self._dir(tenant_id, assessment_id) / MANIFEST
        if not path.exists():
            return None
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return document

    def location(self, tenant_id: str, assessment_id: str) -> str:
        """Where the deliverables for this assessment live."""
        return str(self._dir(tenant_id, assessment_id))

    def verify(self, tenant_id: str, assessment_id: str) -> dict[str, Any]:
        """Re-checksum what is stored against the manifest.

        A deliverable that cannot be shown to be the one that was issued is not
        evidence of anything. This is what makes that showable, and it is the
        check to run on a restore from backup.
        """
        manifest = self.manifest(tenant_id, assessment_id)
        if manifest is None:
            return {"verified": False, "detail": "no manifest was stored", "checked": 0}

        base = self._dir(tenant_id, assessment_id)
        for entry in manifest.get("artifacts", []):
            path = base / str(entry["name"])
            if not path.exists():
                return {
                    "verified": False,
                    "detail": f"{entry['name']} is named in the manifest and is not there",
                    "checked": len(manifest.get("artifacts", [])),
                }
            if _sha256(path) != entry["sha256"]:
                return {
                    "verified": False,
                    "detail": f"{entry['name']} does not match its recorded checksum",
                    "checked": len(manifest.get("artifacts", [])),
                }
        return {
            "verified": True,
            "detail": "",
            "checked": len(manifest.get("artifacts", [])),
        }

    # ----------------------------------------------------------------- health

    def health(self) -> dict[str, Any]:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".ironclad-artifact-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return {
                "store": "artifacts",
                "root": str(self.root),
                "writable": False,
                "detail": str(exc),
            }
        return {"store": "artifacts", "root": str(self.root), "writable": True, "detail": ""}
