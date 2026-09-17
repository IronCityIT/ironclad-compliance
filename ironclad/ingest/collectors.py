"""Turn a manifest or a directory into an EvidenceSet the engine can assess."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ironclad.errors import ValidationError
from ironclad.ids import artifact_id, slugify, utc_now
from ironclad.ingest.contract import find_manifest, load_manifest, manifest_from_directory
from ironclad.ingest.extractors import extract_text
from ironclad.model.evidence import EvidenceArtifact, EvidenceSet


def _moment(value: Any, default: datetime | None = None) -> datetime | None:
    if value in (None, ""):
        return default
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def collect_from_manifest(
    manifest: dict[str, Any],
    base_dir: Path | None = None,
) -> tuple[EvidenceSet, list[str]]:
    """Build an EvidenceSet from a validated manifest.

    Returns the set plus any extraction warnings. A warning means one artifact
    could not be read; the artifact is still catalogued (it exists, an auditor
    can be pointed at it) but it contributes no matched text.

    With a `base_dir`, every local URI in the manifest must resolve to a path
    inside it. The manifest is the tenant's own file, so a URI in it is
    tenant-supplied: `../other-client/policy.pdf` or `/volume1/evidence/beta/`
    would otherwise be read, matched and linked to this tenant's controls, with
    the path recorded in their assessment. Staging confines the prefix; this
    confines what the prefix's manifest may point at. One escaping item refuses
    the whole ingest, with every offender named.
    """
    tenant_id = slugify(manifest["tenant_id"])
    default_collected = _moment(manifest.get("collected_at"), utc_now())
    evidence = EvidenceSet(tenant_id=tenant_id)
    warnings: list[str] = []

    if base_dir is not None:
        escaped = [
            f"{item.get('name', '?')}: {item.get('uri', '')} resolves outside {base_dir}"
            for item in manifest.get("items", [])
            if _escapes(str(item.get("uri", "")), base_dir)
        ]
        if escaped:
            raise ValidationError("manifest names evidence outside the evidence directory", escaped)

    for item in manifest.get("items", []):
        uri = str(item["uri"])
        artifact = EvidenceArtifact(
            artifact_id=artifact_id(tenant_id, uri, str(item.get("sha256", ""))),
            tenant_id=tenant_id,
            name=str(item["name"]),
            uri=uri,
            evidence_type=str(item.get("evidence_type", "")),
            media_type=str(item.get("media_type", "")),
            sha256=str(item.get("sha256", "")),
            size_bytes=int(item.get("size_bytes", 0)),
            collected_at=_moment(item.get("collected_at"), default_collected) or utc_now(),
            valid_from=_moment(item.get("valid_from")),
            valid_until=_moment(item.get("valid_until")),
            source_system=str(manifest.get("source_system", "")),
            classification=str(item.get("classification", "confidential")),
        )

        # Only a local path can be read here. A gs:// or https:// URI is fetched
        # by the workflow before this runs, and the manifest it hands over points
        # at the downloaded copy; anything still remote is catalogued without
        # text rather than silently fetched from inside the engine.
        local = _local_path(uri, base_dir)
        if local is not None:
            extraction = extract_text(local)
            if extraction.ok:
                artifact.text = extraction.text
                if extraction.truncated:
                    warnings.append(f"{artifact.name}: text truncated for matching")
            else:
                warnings.append(f"{artifact.name}: {extraction.error}")

        # Operator-asserted links ride on the artifact and are consumed by the
        # control mapping module, which records them as manual links.
        artifact.control_hints = [str(h) for h in item.get("control_hints", [])]

        evidence.add(artifact)

    return evidence, warnings


def _candidate_path(uri: str, base_dir: Path | None) -> Path | None:
    """The path a URI names on this machine, unchecked, or None if it is remote."""
    if "://" in uri and not uri.startswith("file://"):
        return None
    raw = uri[len("file://") :] if uri.startswith("file://") else uri
    path = Path(raw)
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path


def _escapes(uri: str, base_dir: Path) -> bool:
    """Whether a local URI resolves to somewhere other than inside base_dir.

    Resolved on both sides, so `..` segments and symlinks are judged by where
    they land rather than how they are spelled. Existence is not the test: a
    URI outside the directory is refused whether or not anything is there,
    because the path itself would otherwise be recorded in the tenant's
    evidence inventory.
    """
    candidate = _candidate_path(uri, base_dir)
    if candidate is None:
        return False
    return not candidate.resolve().is_relative_to(base_dir.resolve())


def _local_path(uri: str, base_dir: Path | None) -> Path | None:
    """The on-disk path for a URI, or None if it is not local or not present."""
    path = _candidate_path(uri, base_dir)
    if path is None or not path.exists():
        return None
    return path


def collect_from_directory(
    tenant_id: str,
    directory: Path,
    framework: str = "",
) -> tuple[EvidenceSet, list[str]]:
    """Ingest a directory, preferring a manifest inside it when one is present."""
    manifest_path = find_manifest(directory)
    if manifest_path is not None:
        manifest = load_manifest(manifest_path)
        return collect_from_manifest(manifest, base_dir=directory)

    manifest = manifest_from_directory(tenant_id, directory, framework=framework)
    return collect_from_manifest(manifest, base_dir=directory)
