"""Identifier helpers.

Every id the engine mints is deterministic and path-safe. Deterministic matters
for two reasons: a re-run of the same assessment must address the same Firestore
document rather than accumulating duplicates, and an auditor comparing two
exports must see stable identifiers for the same object.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Normalize free text into a stable, path-safe slug.

    Matches the `toClientId` normalization in functions/index.js exactly, so a
    tenant slug minted here addresses the same Firestore path the Cloud Function
    writes to.
    """
    return _SLUG_STRIP.sub("-", str(value or "").strip().lower()).strip("-")


def client_slug(value: str) -> str:
    """The tenant slug for an operator-supplied client identifier, or ValueError.

    `slugify` quietly turns "../beta" into "beta" — a *different valid tenant*.
    That is not a traversal, but it is a silent reinterpretation of what was
    asked for, and everywhere a client id chooses whose record is written it is
    refused rather than guessed at. `ironclad evidence stage` applies the same
    rule to the prefix it reads; this is the rule for the record it produces.
    """
    raw = str(value or "")
    if "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError(
            f"{raw!r} is not a client identifier; a path separator or '..' in one names "
            f"a different tenant once normalised, so it is refused rather than reinterpreted"
        )
    slug = slugify(raw)
    if not slug:
        raise ValueError(f"{raw!r} does not name a tenant")
    return slug


# A control id becomes a Firestore document id when a large framework's control
# detail is stored in its own subcollection. "/" would address a different
# collection path, and "." / ".." / "__x__" are rejected by Firestore outright,
# so a framework carrying one would lose that control at storage time with a
# 200 in the log. Caught when the framework is validated instead, where it names
# the offending control. Mirrors isSafeDocId in functions/core.js.
_DOC_ID_MAX = 1500


def is_safe_document_id(value: str) -> bool:
    """True if `value` may be used verbatim as a stored document id."""
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > _DOC_ID_MAX:
        return False
    if "/" in candidate:
        return False
    if candidate in (".", ".."):
        return False
    return not (candidate.startswith("__") and candidate.endswith("__"))


def utc_now() -> datetime:
    """Timezone-aware now. The engine never handles a naive datetime."""
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    """Serialize a datetime as UTC ISO-8601, normalizing any input offset."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def content_hash(*parts: str) -> str:
    """Short stable digest over the given parts, for deterministic ids."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def assessment_id(tenant_id: str, framework_id: str, started_at: datetime) -> str:
    """`<tenant>-<framework>-<UTC timestamp>` — sortable and human-readable."""
    stamp = started_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{slugify(tenant_id)}-{slugify(framework_id)}-{stamp}"


def artifact_id(tenant_id: str, uri: str, sha256: str = "") -> str:
    """Stable id for one evidence artifact.

    Keyed on the checksum when the manifest supplies one, so the same file
    re-submitted under a new path is recognised as the same evidence. Falls back
    to the URI when no checksum was provided.
    """
    return "ev-" + content_hash(slugify(tenant_id), sha256 or uri.strip().lower())
