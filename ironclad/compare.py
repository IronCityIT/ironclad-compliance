"""What changed between two assessments.

A compliance programme is a trend, not a snapshot. The question a client asks at
the second assessment is not "what is our readiness" but "what moved, and did
the work we did in between show up". Everything needed to answer that has been
stored since the first release — the complete register, every verdict, the whole
remediation plan — and nothing read it back.

Pure: two documents in, a comparison out. No storage, no I/O, so the CLI, the
store and any future surface all get the same answer.

Three honesty rules, because a trend is the easiest thing in this product to
make flattering by accident:

**A control scoped out is not a control fixed.** Moving to `not_applicable`
removes it from the denominator and lifts the score, which looks exactly like
progress. It is reported as a scope change, in its own list, never as an
improvement.

**A framework version change invalidates the comparison** as a like-for-like
trend, because the control set moved underneath it. Said plainly rather than
quietly producing a number.

**Controls present in only one assessment are named**, not dropped. A control
that disappears between two runs is either a scope change or a defect, and
silently omitting it from both lists hides which.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ironclad.model.assessment import ControlStatus

#: Where a status sits when asking "did this get better or worse".
#:
#: Deliberately not STATUS_ORDER, which ranks severity for reporting and puts
#: `not_applicable` at the top — correct there, and here it would read a control
#: scoped out of the assessment as the best possible outcome.
#:
#: An accepted risk ranks with partial: the control is still not met, and the
#: organisation has decided about it, which is materially better than an unknown
#: gap and is not a working control. Same 0.5 the score gives it.
MOVEMENT_RANK: dict[ControlStatus, int] = {
    ControlStatus.GAP: 0,
    ControlStatus.PENDING: 0,
    ControlStatus.PARTIAL: 1,
    ControlStatus.ACCEPTED_RISK: 1,
    ControlStatus.COMPLIANT: 2,
}

IMPROVED = "improved"
REGRESSED = "regressed"
UNCHANGED = "unchanged"
SCOPED_OUT = "scoped_out"
SCOPED_IN = "scoped_in"


def _rank(status: str) -> int | None:
    """The movement rank of a status, or None if it does not have one."""
    try:
        return MOVEMENT_RANK.get(ControlStatus(status))
    except ValueError:
        return None


@dataclass
class ControlChange:
    """One control, before and after."""

    control_id: str
    control_name: str
    was: str
    now: str
    movement: str
    points_before: int = 0
    points_after: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "control_name": self.control_name,
            "was": self.was,
            "now": self.now,
            "movement": self.movement,
            "points_before": self.points_before,
            "points_after": self.points_after,
        }


@dataclass
class Comparison:
    """Two assessments of one tenant, and what moved between them."""

    tenant_id: str
    framework_id: str
    earlier_id: str
    later_id: str
    earlier_at: str
    later_at: str
    readiness_before: float
    readiness_after: float
    comparable: bool = True
    caveats: list[str] = field(default_factory=list)
    improved: list[ControlChange] = field(default_factory=list)
    regressed: list[ControlChange] = field(default_factory=list)
    unchanged: list[ControlChange] = field(default_factory=list)
    scoped_out: list[ControlChange] = field(default_factory=list)
    scoped_in: list[ControlChange] = field(default_factory=list)
    only_earlier: list[str] = field(default_factory=list)
    only_later: list[str] = field(default_factory=list)
    remediation_closed: list[dict[str, Any]] = field(default_factory=list)
    remediation_opened: list[dict[str, Any]] = field(default_factory=list)
    remediation_carried: list[dict[str, Any]] = field(default_factory=list)

    @property
    def readiness_change(self) -> float:
        return round(self.readiness_after - self.readiness_before, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "framework_id": self.framework_id,
            "earlier": {"assessment_id": self.earlier_id, "at": self.earlier_at},
            "later": {"assessment_id": self.later_id, "at": self.later_at},
            "comparable": self.comparable,
            "caveats": list(self.caveats),
            "readiness": {
                "before": self.readiness_before,
                "after": self.readiness_after,
                "change": self.readiness_change,
            },
            "controls": {
                "improved": [c.to_dict() for c in self.improved],
                "regressed": [c.to_dict() for c in self.regressed],
                "unchanged": len(self.unchanged),
                "scoped_out": [c.to_dict() for c in self.scoped_out],
                "scoped_in": [c.to_dict() for c in self.scoped_in],
                "only_in_earlier": list(self.only_earlier),
                "only_in_later": list(self.only_later),
            },
            "remediation": {
                "closed": self.remediation_closed,
                "opened": self.remediation_opened,
                "still_open": len(self.remediation_carried),
            },
        }

    def headline(self) -> str:
        """One line a human can read off the end of a pipeline."""
        direction = (
            "up"
            if self.readiness_change > 0
            else ("down" if self.readiness_change < 0 else "level")
        )
        return (
            f"readiness {self.readiness_before}% → {self.readiness_after}% "
            f"({direction} {abs(self.readiness_change)}), "
            f"{len(self.improved)} improved, {len(self.regressed)} regressed, "
            f"{len(self.remediation_closed)} remediation item(s) closed, "
            f"{len(self.remediation_opened)} opened"
        )


def _controls(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c.get("control_id")): c for c in document.get("controls") or []}


def _items(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    remediation = document.get("remediation") or {}
    return {str(i.get("item_id")): i for i in remediation.get("items") or []}


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": item.get("item_id", ""),
        "control_id": item.get("control_id", ""),
        "control_name": item.get("control_name", ""),
        "severity": item.get("severity", ""),
        "owner": item.get("owner", ""),
        "due_date": item.get("due_date", ""),
    }


def compare(earlier: dict[str, Any], later: dict[str, Any]) -> Comparison:
    """What changed between two assessments of the same tenant.

    Refuses two tenants outright — a trend across clients is meaningless and
    would be a cross-tenant read besides. A different framework, or a different
    version of one, produces a comparison marked not comparable with the reason
    stated, rather than a number that looks like a trend and is not.
    """
    earlier_tenant = str(earlier.get("tenant_id") or earlier.get("client_id") or "")
    later_tenant = str(later.get("tenant_id") or later.get("client_id") or "")
    if earlier_tenant != later_tenant:
        raise ValueError(
            f"cannot compare assessments of different tenants: "
            f"{earlier_tenant!r} and {later_tenant!r}"
        )

    earlier_framework = (earlier.get("framework") or {}).get("id", "")
    later_framework = (later.get("framework") or {}).get("id", "")
    earlier_version = (earlier.get("framework") or {}).get("version", "")
    later_version = (later.get("framework") or {}).get("version", "")

    comparison = Comparison(
        tenant_id=later_tenant,
        framework_id=str(later_framework),
        earlier_id=str(earlier.get("assessment_id", "")),
        later_id=str(later.get("assessment_id", "")),
        earlier_at=str(earlier.get("started_at", "")),
        later_at=str(later.get("started_at", "")),
        readiness_before=float((earlier.get("summary") or {}).get("readiness_score") or 0.0),
        readiness_after=float((later.get("summary") or {}).get("readiness_score") or 0.0),
    )

    if earlier_framework != later_framework:
        comparison.comparable = False
        comparison.caveats.append(
            f"These are assessments against different frameworks "
            f"({earlier_framework} and {later_framework}). The readiness figures are "
            f"not a trend and the controls do not correspond."
        )
    elif earlier_version != later_version:
        comparison.comparable = False
        comparison.caveats.append(
            f"The framework moved from version {earlier_version} to {later_version} "
            f"between these assessments. Controls that changed with it are not a "
            f"like-for-like comparison, and the readiness figures are not a trend."
        )

    before = _controls(earlier)
    after = _controls(later)

    for control_id in sorted(set(before) & set(after)):
        was, now = before[control_id], after[control_id]
        was_status, now_status = str(was.get("status")), str(now.get("status"))
        change = ControlChange(
            control_id=control_id,
            control_name=str(now.get("control_name", "")),
            was=was_status,
            now=now_status,
            movement=UNCHANGED,
            points_before=int(was.get("points_covered") or 0),
            points_after=int(now.get("points_covered") or 0),
        )

        # A control scoped out is not a control fixed. It leaves the denominator
        # and lifts the score, which looks exactly like progress.
        if now_status == str(ControlStatus.NOT_APPLICABLE) and was_status != now_status:
            change.movement = SCOPED_OUT
            comparison.scoped_out.append(change)
            continue
        if was_status == str(ControlStatus.NOT_APPLICABLE) and was_status != now_status:
            change.movement = SCOPED_IN
            comparison.scoped_in.append(change)
            continue

        was_rank, now_rank = _rank(was_status), _rank(now_status)
        if was_rank is None or now_rank is None or was_rank == now_rank:
            # Same rank still counts as unchanged movement even when the status
            # differs — partial to accepted_risk is a decision, not progress.
            comparison.unchanged.append(change)
        elif now_rank > was_rank:
            change.movement = IMPROVED
            comparison.improved.append(change)
        else:
            change.movement = REGRESSED
            comparison.regressed.append(change)

    comparison.only_earlier = sorted(set(before) - set(after))
    comparison.only_later = sorted(set(after) - set(before))
    if comparison.only_earlier or comparison.only_later:
        comparison.caveats.append(
            f"{len(comparison.only_earlier)} control(s) appear only in the earlier "
            f"assessment and {len(comparison.only_later)} only in the later one. "
            f"They are named rather than dropped: a control that disappears between "
            f"two runs is either a scope change or a defect."
        )

    items_before, items_after = _items(earlier), _items(later)
    comparison.remediation_closed = [
        _brief(items_before[i]) for i in sorted(set(items_before) - set(items_after))
    ]
    comparison.remediation_opened = [
        _brief(items_after[i]) for i in sorted(set(items_after) - set(items_before))
    ]
    comparison.remediation_carried = [
        _brief(items_after[i]) for i in sorted(set(items_after) & set(items_before))
    ]

    return comparison
