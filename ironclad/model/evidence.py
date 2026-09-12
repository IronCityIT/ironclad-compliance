"""Evidence artifacts and the links that bind them to controls.

An artifact is a single piece of client evidence: a policy PDF, an access review
export, a ticket dump. A link is the claim "this artifact supports this control",
carrying how the claim was made (automated match or human attestation) and how
strongly. Keeping the link separate from the artifact is what lets one document
support many controls, and what lets an auditor see why a control was passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from ironclad.ids import iso, utc_now


class LinkMethod(str, Enum):
    """How an evidence link came to exist."""

    AUTOMATED = "automated"  # keyword/term match performed by the engine
    MANUAL = "manual"  # a human asserted the link in the dashboard
    INHERITED = "inherited"  # carried across frameworks by a crosswalk

    def __str__(self) -> str:
        return self.value


# How long evidence of a given class stays current. An access review from
# fourteen months ago does not evidence a control today, and an auditor will say
# so; the engine says so first. Keyed by substring of the evidence type, longest
# match wins. Anything unmatched takes DEFAULT_VALIDITY_DAYS.
VALIDITY_DAYS: dict[str, int] = {
    "penetration test": 365,
    "risk assessment": 365,
    "policy": 365,
    "charter": 365,
    "training": 365,
    "review": 90,
    "access review": 90,
    "scan": 30,
    "vulnerability scan": 30,
    "backup": 30,
    "log": 30,
    "monitoring": 30,
    "ticket": 90,
    "meeting minutes": 180,
}
DEFAULT_VALIDITY_DAYS = 365


def validity_days_for(evidence_type: str) -> int:
    """Freshness window for an evidence type. Longest matching key wins."""
    needle = (evidence_type or "").lower()
    best_key = ""
    for key in VALIDITY_DAYS:
        if key in needle and len(key) > len(best_key):
            best_key = key
    return VALIDITY_DAYS[best_key] if best_key else DEFAULT_VALIDITY_DAYS


@dataclass
class EvidenceArtifact:
    """One piece of client evidence."""

    artifact_id: str
    tenant_id: str
    name: str
    uri: str
    evidence_type: str = ""
    media_type: str = ""
    sha256: str = ""
    size_bytes: int = 0
    collected_at: datetime = field(default_factory=utc_now)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_system: str = ""
    classification: str = "confidential"
    # Controls an operator asserted this artifact supports, from the manifest's
    # `control_hints`. An assertion about the artifact, so it belongs on the
    # artifact; it produces a MANUAL link that a report shows as asserted rather
    # than derived.
    control_hints: list[str] = field(default_factory=list)
    # Extracted text is held in memory for matching and is deliberately never
    # serialised into a stored result or a client-facing report — the evidence
    # itself stays in the tenant's own bucket.
    text: str = ""

    @property
    def effective_valid_until(self) -> datetime:
        """When this artifact goes stale.

        An explicit `valid_until` from the manifest always wins; otherwise the
        window is derived from the evidence type.
        """
        if self.valid_until is not None:
            return self.valid_until
        base = self.valid_from or self.collected_at
        return base + timedelta(days=validity_days_for(self.evidence_type or self.name))

    def is_stale(self, as_of: datetime | None = None) -> bool:
        return (as_of or utc_now()) > self.effective_valid_until

    def age_days(self, as_of: datetime | None = None) -> int:
        return max(0, ((as_of or utc_now()) - (self.valid_from or self.collected_at)).days)

    def to_dict(self, include_text: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "uri": self.uri,
            "evidence_type": self.evidence_type,
            "media_type": self.media_type,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "collected_at": iso(self.collected_at),
            "valid_until": iso(self.effective_valid_until),
            "source_system": self.source_system,
            "classification": self.classification,
            "control_hints": list(self.control_hints),
            "stale": self.is_stale(),
        }
        if include_text:
            payload["text"] = self.text
        return payload


@dataclass(frozen=True)
class EvidenceLink:
    """The claim that an artifact supports a control."""

    control_id: str
    artifact_id: str
    method: LinkMethod = LinkMethod.AUTOMATED
    relevance: float = 0.0  # 0.0 - 1.0
    matched_terms: tuple[str, ...] = ()
    linked_by: str = "engine"
    linked_at: datetime = field(default_factory=utc_now)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "artifact_id": self.artifact_id,
            "method": str(self.method),
            "relevance": round(self.relevance, 3),
            "matched_terms": list(self.matched_terms),
            "linked_by": self.linked_by,
            "linked_at": iso(self.linked_at),
            "note": self.note,
        }


@dataclass
class EvidenceSet:
    """Every artifact submitted for one assessment, indexed for lookup."""

    tenant_id: str
    artifacts: list[EvidenceArtifact] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.artifacts)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.artifacts)

    def add(self, artifact: EvidenceArtifact) -> None:
        if artifact.tenant_id != self.tenant_id:
            raise ValueError(
                f"artifact {artifact.artifact_id} belongs to tenant "
                f"{artifact.tenant_id!r}, not {self.tenant_id!r}"
            )
        self.artifacts.append(artifact)

    def get(self, artifact_id: str) -> EvidenceArtifact | None:
        for artifact in self.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        return None

    def fresh(self, as_of: datetime | None = None) -> list[EvidenceArtifact]:
        return [a for a in self.artifacts if not a.is_stale(as_of)]

    def stale(self, as_of: datetime | None = None) -> list[EvidenceArtifact]:
        return [a for a in self.artifacts if a.is_stale(as_of)]
