"""What each assessment type actually puts in front of the reader.

`full`, `gap-only` and `readiness` were offered by the workflow dropdown, the
CLI, the dashboard and the service API, validated on the way in, stored on the
record — and then ignored. All three produced byte-identical output.

A view shapes the *deliverable*, never the assessment. Everything is always
assessed and everything is always stored: you cannot know which controls are
gaps without judging them all, the readiness score is only reproducible from the
complete register, and a later trend comparison needs the whole record. What
changes is what the issued report shows.

The one rule that makes an abridged report safe to hand to somebody: **a view
that leaves something out says so, in the report, where the omission happened.**
A gap-only report that silently omits the passing controls is indistinguishable
from a catastrophic result.

This module is also the one place the set of assessment types is written down.
The CLI's choices, the service API's validation and the dashboard's dropdown all
derive from `VIEWS` rather than repeating the list — a type that is offered
somewhere but has no view here is exactly the defect this module exists to fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ironclad.model.assessment import ControlStatus

DEFAULT_VIEW = "full"


@dataclass(frozen=True)
class ReportView:
    """How one assessment type presents a completed assessment."""

    name: str
    title: str
    description: str
    show_register: bool = True
    # None means every status. Otherwise only these appear in the register.
    register_statuses: tuple[ControlStatus, ...] | None = None
    show_remediation: bool = True
    show_crosswalk: bool = True
    omission_note: str = ""

    def includes(self, status: ControlStatus) -> bool:
        return self.register_statuses is None or status in self.register_statuses

    def register_for(self, controls: list[Any]) -> list[Any]:
        """The controls this view lists individually. Never a filter on scoring."""
        if not self.show_register:
            return []
        return [c for c in controls if self.includes(c.status)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "shows_register": self.show_register,
            "register_statuses": (
                [str(s) for s in self.register_statuses] if self.register_statuses else None
            ),
            "shows_remediation": self.show_remediation,
            "shows_crosswalk": self.show_crosswalk,
        }


# Statuses that represent outstanding work. Accepted risk is included: the
# control is not met, and a reader looking at what needs attention should see
# that a decision was taken rather than find the control simply missing.
OUTSTANDING: tuple[ControlStatus, ...] = (
    ControlStatus.GAP,
    ControlStatus.PARTIAL,
    ControlStatus.PENDING,
    ControlStatus.ACCEPTED_RISK,
)

VIEWS: dict[str, ReportView] = {
    "full": ReportView(
        name="full",
        title="Compliance readiness assessment",
        description="Every control, the remediation plan and the framework crosswalk.",
    ),
    "gap-only": ReportView(
        name="gap-only",
        title="Compliance gap analysis",
        description="Only the controls with outstanding work, plus the remediation plan.",
        register_statuses=OUTSTANDING,
        omission_note=(
            "This is a gap analysis. The register below lists only the controls with "
            "outstanding work. Controls that are met, and controls scoped out of this "
            "assessment, are counted in the summary above but are not listed individually. "
            "Run a full assessment for the complete control register."
        ),
    ),
    "readiness": ReportView(
        name="readiness",
        title="Compliance readiness summary",
        description="The overall position and the work outstanding, without the register.",
        show_register=False,
        omission_note=(
            "This is a readiness summary. It gives the overall position and the work "
            "outstanding, without the control-by-control register. Run a full assessment "
            "for the complete register and the evidence supporting each control."
        ),
    ),
}

#: The assessment types the product offers, in presentation order. Every surface
#: that names them reads this rather than repeating the list.
ASSESSMENT_TYPES: tuple[str, ...] = tuple(VIEWS)


def view_for(assessment_type: str) -> ReportView:
    """The view for an assessment type, falling back to the full report.

    An unrecognised type must never silently produce an abridged document — the
    safe default is to show everything.
    """
    return VIEWS.get((assessment_type or "").strip().lower(), VIEWS[DEFAULT_VIEW])


def catalog() -> list[dict[str, Any]]:
    """The assessment types as the dashboard renders them."""
    return [VIEWS[name].to_dict() for name in ASSESSMENT_TYPES]
