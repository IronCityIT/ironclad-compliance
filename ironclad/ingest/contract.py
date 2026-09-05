"""The evidence ingestion contract.

A manifest is the agreement between whatever collects a tenant's evidence — a
GCS sync, a Drive connector, a client upload — and this engine. Declaring it
explicitly, versioned, and validating it strictly is what stops the engine from
silently assessing a half-delivered evidence set and reporting a clean gap that
is really a broken pipeline.

Contract shape (contract_version 1.0):

    {
      "contract_version": "1.0",
      "tenant_id": "acme",
      "framework": "soc2",
      "collected_at": "2026-09-05T12:00:00+00:00",
      "source_system": "gcs",
      "items": [
        {
          "name": "Access Control Policy.pdf",   # required
          "uri": "gs://bucket/acme/acp.pdf",     # required
          "evidence_type": "Access control policy",
          "media_type": "application/pdf",
          "sha256": "…",                          # optional but recommended
          "size_bytes": 148213,
          "collected_at": "2026-09-01T00:00:00+00:00",
          "valid_from": "2026-01-01T00:00:00+00:00",
          "valid_until": "2027-01-01T00:00:00+00:00",
          "classification": "confidential",
          "control_hints": ["CC6.1", "CC6.2"]    # optional operator assertion
        }
      ]
    }

`control_hints` is how a human asserts a link the keyword matcher would miss. It
produces a MANUAL evidence link, which is recorded as such in the report — an
auditor can tell an asserted link from a derived one.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ironclad.errors import ValidationError
from ironclad.ids import iso, slugify, utc_now

CONTRACT_VERSION = "1.0"
SUPPORTED_CONTRACT_VERSIONS = frozenset({"1.0"})

MANIFEST_FILENAMES = ("evidence-manifest.json", "manifest.json")

REQUIRED_ITEM_FIELDS = ("name", "uri")
VALID_CLASSIFICATIONS = frozenset({"public", "internal", "confidential", "restricted"})


def _parse_moment(value: Any, field: str, errors: list[str]) -> datetime | None:
    """Parse an ISO-8601 timestamp, recording a fault instead of raising."""
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} is not an ISO-8601 timestamp: {value!r}")
        return None


def validate_manifest(document: Any) -> list[str]:
    """Return every problem with an evidence manifest. Empty list means valid."""
    errors: list[str] = []

    if not isinstance(document, dict):
        return ["evidence manifest must be a JSON object"]

    version = str(document.get("contract_version", "")).strip()
    if not version:
        errors.append("contract_version is required")
    elif version not in SUPPORTED_CONTRACT_VERSIONS:
        errors.append(
            f"contract_version {version!r} is not supported "
            f"(this engine speaks {', '.join(sorted(SUPPORTED_CONTRACT_VERSIONS))})"
        )

    if not str(document.get("tenant_id", "")).strip():
        errors.append("tenant_id is required")

    _parse_moment(document.get("collected_at"), "collected_at", errors)

    items = document.get("items")
    if not isinstance(items, list):
        errors.append("'items' must be an array")
        return errors
    if not items:
        # An empty evidence set is a legitimate state (a tenant that has
        # submitted nothing yet) but it must be declared, not inferred from a
        # failed download. The caller decides what to do; the contract is valid.
        return errors

    seen_uris: set[str] = set()
    for index, item in enumerate(items):
        where = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where} must be an object")
            continue

        for field in REQUIRED_ITEM_FIELDS:
            if not str(item.get(field, "")).strip():
                errors.append(f"{where}.{field} is required")

        uri = str(item.get("uri", "")).strip()
        if uri:
            if uri in seen_uris:
                errors.append(f"{where}.uri {uri!r} appears more than once")
            seen_uris.add(uri)

        sha = str(item.get("sha256", "")).strip()
        if sha and (len(sha) != 64 or not all(ch in "0123456789abcdefABCDEF" for ch in sha)):
            errors.append(f"{where}.sha256 must be 64 hex characters")

        size = item.get("size_bytes", 0)
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errors.append(f"{where}.size_bytes must be a non-negative integer")

        classification = str(item.get("classification", "confidential")).strip().lower()
        if classification not in VALID_CLASSIFICATIONS:
            errors.append(
                f"{where}.classification {classification!r} is not one of "
                f"{sorted(VALID_CLASSIFICATIONS)}"
            )

        valid_from = _parse_moment(item.get("valid_from"), f"{where}.valid_from", errors)
        valid_until = _parse_moment(item.get("valid_until"), f"{where}.valid_until", errors)
        _parse_moment(item.get("collected_at"), f"{where}.collected_at", errors)
        if valid_from and valid_until and valid_until <= valid_from:
            errors.append(f"{where}.valid_until must be after valid_from")

        hints = item.get("control_hints", [])
        if not isinstance(hints, list) or not all(isinstance(h, str) for h in hints):
            errors.append(f"{where}.control_hints must be an array of control ids")

    return errors


def load_manifest(path: Path) -> dict[str, Any]:
    """Read and validate a manifest file, raising ValidationError on any fault."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc

    errors = validate_manifest(document)
    if errors:
        raise ValidationError(f"{path.name} does not satisfy the evidence contract", errors)
    return document


def find_manifest(directory: Path) -> Path | None:
    for filename in MANIFEST_FILENAMES:
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


def build_manifest(
    tenant_id: str,
    items: list[dict[str, Any]],
    framework: str = "",
    source_system: str = "",
    collected_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble a contract-shaped manifest. Validates before returning."""
    document = {
        "contract_version": CONTRACT_VERSION,
        "tenant_id": slugify(tenant_id),
        "framework": framework,
        "source_system": source_system,
        "collected_at": iso(collected_at or utc_now()),
        "items": items,
    }
    errors = validate_manifest(document)
    if errors:
        raise ValidationError("built manifest does not satisfy its own contract", errors)
    return document


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_from_directory(
    tenant_id: str,
    directory: Path,
    framework: str = "",
    source_system: str = "filesystem",
) -> dict[str, Any]:
    """Derive a manifest from a directory of files.

    The fallback path for a tenant that hands over a folder rather than a
    manifest. Every derived item is checksummed, so a re-run recognises the same
    evidence even if the folder was reorganised in between.
    """
    items: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name in MANIFEST_FILENAMES:
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "uri": str(path.resolve()),
                # With no manifest to declare the evidence class, the file's own
                # name is the only signal available. It feeds the freshness
                # window, so a file named "Q3 access review.xlsx" still ages on
                # the 90-day clock rather than the default annual one.
                "evidence_type": path.stem,
                "media_type": "",
                "sha256": sha256_file(path),
                "size_bytes": stat.st_size,
                "collected_at": iso(datetime.fromtimestamp(stat.st_mtime).astimezone()),
                "classification": "confidential",
                "control_hints": [],
            }
        )
    return build_manifest(tenant_id, items, framework=framework, source_system=source_system)
