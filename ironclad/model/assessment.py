"""Assessment results: per-control verdicts and the rolled-up readiness score.

The scoring rule is deliberately explicit and deterministic. A readiness score
that moves because a model felt differently today is worthless to an auditor, so
the number is computed from the control verdicts by weight and the AI consensus
is carried alongside it as commentary, never folded into it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ironclad.ids import iso, utc_now
from ironclad.model.control import Control, Framework
from ironclad.model.evidence import EvidenceLink


class ControlStatus(str, Enum):
    """The verdict on one control."""

    COMPLIANT = "compliant"
    PARTIAL = "partial"
    GAP = "gap"
    NOT_APPLICABLE = "not_applicable"
    ACCEPTED_RISK = "accepted_risk"
    PENDING = "pending"

    def __str__(self) -> str:
        return self.value


# Worst-first. Used to sort a report and to pick the driving status when two
# assessment modules disagree about the same control.
STATUS_ORDER: tuple[ControlStatus, ...] = (
    ControlStatus.GAP,
    ControlStatus.PARTIAL,
    ControlStatus.PENDING,
    ControlStatus.ACCEPTED_RISK,
    ControlStatus.COMPLIANT,
    ControlStatus.NOT_APPLICABLE,
)

# Credit each status earns toward the readiness score. An accepted risk earns
# partial credit: the organisation knows about it and has signed for it, which
# is materially better than an unknown gap but is not a working control.
STATUS_CREDIT: dict[ControlStatus, float] = {
    ControlStatus.COMPLIANT: 1.0,
    ControlStatus.PARTIAL: 0.5,
    ControlStatus.ACCEPTED_RISK: 0.5,
    ControlStatus.GAP: 0.0,
    ControlStatus.PENDING: 0.0,
    ControlStatus.NOT_APPLICABLE: 0.0,  # also excluded from the denominator
}


def worst(statuses: list[ControlStatus]) -> ControlStatus:
    """The most severe status in the list, per STATUS_ORDER."""
    if not statuses:
        return ControlStatus.PENDING
    return min(statuses, key=STATUS_ORDER.index)


@dataclass
class ControlAssessment:
    """The verdict on one control, with the evidence that produced it."""

    control_id: str
    control_name: str
    status: ControlStatus = ControlStatus.PENDING
    rationale: str = ""
    evidence_links: list[EvidenceLink] = field(default_factory=list)
    points_covered: int = 0
    points_total: int = 0
    weight: float = 1.0
    confidence: float = 0.0  # 0.0 - 1.0, how strongly the evidence supports the verdict
    assessed_at: datetime = field(default_factory=utc_now)
    assessed_by: str = "engine"
    exception_id: str = ""  # set when an approved risk acceptance drives the status
    notes: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Fraction of the control's points of focus with supporting evidence."""
        if self.points_total <= 0:
            return 0.0
        return self.points_covered / self.points_total

    @property
    def credit(self) -> float:
        return STATUS_CREDIT[self.status]

    def is_scored(self) -> bool:
        """Not-applicable controls are excluded from the readiness denominator."""
        return self.status is not ControlStatus.NOT_APPLICABLE

    def add_note(self, note: str) -> None:
        if note and note not in self.notes:
            self.notes.append(note)

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "control_name": self.control_name,
            "status": str(self.status),
            "rationale": self.rationale,
            "evidence_links": [link.to_dict() for link in self.evidence_links],
            "evidence_count": len(self.evidence_links),
            "points_covered": self.points_covered,
            "points_total": self.points_total,
            "coverage": round(self.coverage, 3),
            "weight": self.weight,
            "confidence": round(self.confidence, 3),
            "assessed_at": iso(self.assessed_at),
            "assessed_by": self.assessed_by,
            "exception_id": self.exception_id,
            "notes": list(self.notes),
        }


@dataclass
class AssessmentSummary:
    """Counts and the weighted readiness score."""

    total_controls: int = 0
    compliant: int = 0
    partial: int = 0
    gap: int = 0
    not_applicable: int = 0
    accepted_risk: int = 0
    pending: int = 0
    readiness_score: float = 0.0  # 0-100, weighted
    evidence_artifacts: int = 0
    stale_artifacts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_controls": self.total_controls,
            "compliant": self.compliant,
            "partial": self.partial,
            "gap": self.gap,
            "not_applicable": self.not_applicable,
            "accepted_risk": self.accepted_risk,
            "pending": self.pending,
            "readiness_score": self.readiness_score,
            "evidence_artifacts": self.evidence_artifacts,
            "stale_artifacts": self.stale_artifacts,
        }


@dataclass
class Assessment:
    """One complete run against one framework for one tenant."""

    assessment_id: str
    tenant_id: str
    framework: Framework
    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    assessment_type: str = "full"
    modules_run: list[str] = field(default_factory=list)
    controls: list[ControlAssessment] = field(default_factory=list)
    summary: AssessmentSummary = field(default_factory=AssessmentSummary)
    # Commentary from the central AI consensus engine. Never folded into the
    # readiness score — the score must be reproducible from the verdicts alone.
    consensus: dict[str, Any] = field(default_factory=dict)

    def get(self, control_id: str) -> ControlAssessment | None:
        for item in self.controls:
            if item.control_id == control_id:
                return item
        return None

    def by_status(self, status: ControlStatus) -> list[ControlAssessment]:
        return [c for c in self.controls if c.status is status]

    def recompute_summary(self, evidence_count: int = 0, stale_count: int = 0) -> AssessmentSummary:
        """Recount every bucket and recompute the weighted readiness score.

        Score is the weighted credit earned over the weighted credit available,
        with not-applicable controls removed from both sides so scoping a control
        out never silently penalises the tenant.
        """
        summary = AssessmentSummary(
            total_controls=len(self.controls),
            evidence_artifacts=evidence_count,
            stale_artifacts=stale_count,
        )
        earned = 0.0
        available = 0.0
        for item in self.controls:
            if item.status is ControlStatus.COMPLIANT:
                summary.compliant += 1
            elif item.status is ControlStatus.PARTIAL:
                summary.partial += 1
            elif item.status is ControlStatus.GAP:
                summary.gap += 1
            elif item.status is ControlStatus.NOT_APPLICABLE:
                summary.not_applicable += 1
            elif item.status is ControlStatus.ACCEPTED_RISK:
                summary.accepted_risk += 1
            else:
                summary.pending += 1

            if item.is_scored():
                earned += item.credit * item.weight
                available += item.weight

        summary.readiness_score = round(100.0 * earned / available, 1) if available else 0.0
        self.summary = summary
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "tenant_id": self.tenant_id,
            "client_id": self.tenant_id,  # storeAssessmentResults reads client_id
            "framework": self.framework.to_dict(),
            "assessment_type": self.assessment_type,
            "started_at": iso(self.started_at),
            "completed_at": iso(self.completed_at) if self.completed_at else None,
            "modules_run": list(self.modules_run),
            "summary": self.summary.to_dict(),
            "controls": [c.to_dict() for c in self.controls],
            "consensus": self.consensus or None,
        }


def blank_control_assessment(control: Control) -> ControlAssessment:
    """A pending verdict for a control, before any module has looked at it."""
    return ControlAssessment(
        control_id=control.id,
        control_name=control.name,
        status=ControlStatus.PENDING,
        points_total=len(control.points_of_focus),
        weight=control.weight,
    )
