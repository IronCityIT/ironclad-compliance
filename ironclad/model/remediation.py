"""Remediation items and the plan that orders them.

Priority is computed, not typed in. Two organisations with the same gaps should
get the same work order, and the order should be defensible: risk of the control
family, how far the control is from passing, and whether the evidence that does
exist has gone stale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from ironclad.ids import content_hash, iso, utc_now
from ironclad.model.assessment import ControlAssessment, ControlStatus


class RemediationStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    RISK_ACCEPTED = "risk_accepted"

    def __str__(self) -> str:
        return self.value


class Severity(str, Enum):
    """Severity vocabulary shared with the AI consensus engine's finding shape."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    def __str__(self) -> str:
        return self.value


# Days to remediate, by severity. Drives the due date, which is what turns a
# report into a plan someone can be held to.
SLA_DAYS: dict[Severity, int] = {
    Severity.CRITICAL: 14,
    Severity.HIGH: 30,
    Severity.MEDIUM: 60,
    Severity.LOW: 90,
    Severity.INFO: 180,
}

SEVERITY_SCORE: dict[Severity, float] = {
    Severity.CRITICAL: 5.0,
    Severity.HIGH: 4.0,
    Severity.MEDIUM: 3.0,
    Severity.LOW: 2.0,
    Severity.INFO: 1.0,
}


def severity_for(item: ControlAssessment) -> Severity:
    """Map a control verdict plus its risk weight onto a severity.

    A full gap in a heavily-weighted family (access control, incident response)
    is critical; the same gap in a governance family is high. A partial is one
    step down from the gap it would otherwise be.
    """
    if item.status is ControlStatus.GAP:
        base = Severity.CRITICAL if item.weight >= 1.4 else Severity.HIGH
    elif item.status is ControlStatus.PARTIAL:
        base = Severity.HIGH if item.weight >= 1.4 else Severity.MEDIUM
    elif item.status is ControlStatus.PENDING:
        base = Severity.MEDIUM
    else:
        base = Severity.LOW
    return base


@dataclass
class RemediationItem:
    """One unit of work that closes one control gap."""

    item_id: str
    tenant_id: str
    control_id: str
    control_name: str
    title: str
    guidance: str
    severity: Severity = Severity.MEDIUM
    status: RemediationStatus = RemediationStatus.OPEN
    priority: float = 0.0
    owner: str = ""
    created_at: datetime = field(default_factory=utc_now)
    due_date: datetime | None = None
    evidence_gap: list[str] = field(default_factory=list)
    exception_id: str = ""
    source: str = "engine"

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "tenant_id": self.tenant_id,
            "control_id": self.control_id,
            "control_name": self.control_name,
            "title": self.title,
            "guidance": self.guidance,
            "severity": str(self.severity),
            "status": str(self.status),
            "priority": round(self.priority, 2),
            "owner": self.owner,
            "created_at": iso(self.created_at),
            "due_date": iso(self.due_date) if self.due_date else None,
            "evidence_gap": list(self.evidence_gap),
            "exception_id": self.exception_id,
            "source": self.source,
        }


def priority_score(item: ControlAssessment, severity: Severity) -> float:
    """Rank a remediation item. Higher is more urgent.

    severity x control weight, discounted by how much of the control is already
    covered. A control with four of five points of focus evidenced is closer to
    done than one with none, and should be ranked below it even at equal severity.
    """
    closeness_discount = 1.0 - (0.4 * item.coverage)
    return round(SEVERITY_SCORE[severity] * item.weight * closeness_discount, 3)


def build_item(
    tenant_id: str,
    item: ControlAssessment,
    guidance: str,
    missing_evidence: list[str],
    now: datetime | None = None,
) -> RemediationItem:
    """Mint the remediation item for one failing control verdict."""
    now = now or utc_now()
    severity = severity_for(item)
    return RemediationItem(
        item_id="rm-" + content_hash(tenant_id, item.control_id),
        tenant_id=tenant_id,
        control_id=item.control_id,
        control_name=item.control_name,
        title=f"Close {item.control_id} — {item.control_name}",
        guidance=guidance,
        severity=severity,
        priority=priority_score(item, severity),
        created_at=now,
        due_date=now + timedelta(days=SLA_DAYS[severity]),
        evidence_gap=missing_evidence,
    )


@dataclass
class RemediationPlan:
    """Every open item for one assessment, ordered by priority."""

    tenant_id: str
    assessment_id: str
    items: list[RemediationItem] = field(default_factory=list)
    generated_at: datetime = field(default_factory=utc_now)

    def __len__(self) -> int:
        return len(self.items)

    def add(self, item: RemediationItem) -> None:
        self.items.append(item)

    def ordered(self) -> list[RemediationItem]:
        """Highest priority first; ties broken by control id so runs are stable."""
        return sorted(self.items, key=lambda i: (-i.priority, i.control_id))

    def overdue(self, as_of: datetime | None = None) -> list[RemediationItem]:
        now = as_of or utc_now()
        return [
            i
            for i in self.items
            if i.due_date
            and i.due_date < now
            and i.status not in (RemediationStatus.COMPLETE, RemediationStatus.RISK_ACCEPTED)
        ]

    def by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for i in self.items:
            counts[str(i.severity)] = counts.get(str(i.severity), 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "assessment_id": self.assessment_id,
            "generated_at": iso(self.generated_at),
            "item_count": len(self.items),
            "by_severity": self.by_severity(),
            "items": [i.to_dict() for i in self.ordered()],
        }
