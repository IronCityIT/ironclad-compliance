"""Which bars are the standard's, and which are Iron City's.

An auditor's first question about an adverse verdict is "says who?". Every
judgment in an assessment has one of three sources, and until now the report
presented all three in the same voice:

  framework      the control and its points of focus, as published
  icit-policy    Iron City's own bars — corroboration, freshness, weighting.
                 Defensible, deliberate, and *not* in any standard
  tenant-policy  the client's own determinations: scope exclusions, risk
                 acceptances, owners

Presenting an ICIT bar as though the framework required it is the kind of thing
that survives right up until an auditor asks where in SOC 2 it says two
documents are needed. It does not say that anywhere. Two documents is our bar,
it is stricter than the standard, and saying so plainly is what makes it
arguable — which is the point. A client who wants to argue the 90-day access
review window should be able to find the number, see whose rule it is, and
change it in one place.

This module is that page. It is generated from the constants that actually
drive the engine, never hand-written, so a rule that changes in the code cannot
keep its old description in the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ironclad.model.assessment import STATUS_CREDIT, ControlStatus
from ironclad.model.control import DEFAULT_WEIGHT, FAMILY_WEIGHT
from ironclad.model.evidence import DEFAULT_VALIDITY_DAYS, VALIDITY_DAYS
from ironclad.modules.control_mapping import CORROBORATION_MIN, RELEVANCE_THRESHOLD

FRAMEWORK = "framework"
ICIT_POLICY = "icit-policy"
TENANT_POLICY = "tenant-policy"

SOURCE_LABELS = {
    FRAMEWORK: "The framework",
    ICIT_POLICY: "Iron City policy",
    TENANT_POLICY: "Client determination",
}


@dataclass(frozen=True)
class MethodRule:
    """One rule the assessment applied, and whose rule it is."""

    name: str
    source: str
    statement: str
    value: str = ""

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "statement": self.statement,
            "value": self.value,
        }


def _freshness_value() -> str:
    """The freshness windows, shortest first, as a readable sentence fragment."""
    by_days: dict[int, list[str]] = {}
    for evidence_type, days in VALIDITY_DAYS.items():
        by_days.setdefault(days, []).append(evidence_type)
    parts = [
        f"{days} days for {', '.join(sorted(types))}" for days, types in sorted(by_days.items())
    ]
    parts.append(f"{DEFAULT_VALIDITY_DAYS} days for anything else")
    return "; ".join(parts)


def _weight_value() -> str:
    weighted = sorted(FAMILY_WEIGHT.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = [f"{family} ×{weight:g}" for family, weight in weighted]
    parts.append(f"everything else ×{DEFAULT_WEIGHT:g}")
    return "; ".join(parts)


def _credit_value() -> str:
    order = (
        ControlStatus.COMPLIANT,
        ControlStatus.PARTIAL,
        ControlStatus.ACCEPTED_RISK,
        ControlStatus.GAP,
        ControlStatus.PENDING,
    )
    return "; ".join(f"{str(status)} {STATUS_CREDIT[status]:g}" for status in order)


def method_rules() -> list[MethodRule]:
    """Every rule that shaped the verdicts, with its source.

    Read off the engine's own constants. A number that changes in the code
    changes here, so the report cannot describe a rule the engine stopped
    applying.
    """
    return [
        MethodRule(
            name="Control set",
            source=FRAMEWORK,
            statement=(
                "Controls, their points of focus and the evidence each ordinarily "
                "requires are taken from the framework as published. Nothing is added "
                "to a control and nothing is dropped from one."
            ),
        ),
        MethodRule(
            name="Corroboration",
            source=ICIT_POLICY,
            statement=(
                "A control reads as met only when at least this many independent "
                "evidence items support it. One document is a claim; two is "
                "corroboration. No framework requires this — it is the bar Iron City "
                "applies, and it is stricter than the standard, so a control may read "
                "as partly evidenced here that a lighter assessment would pass."
            ),
            value=f"{CORROBORATION_MIN} independent items",
        ),
        MethodRule(
            name="Evidence relevance",
            source=ICIT_POLICY,
            statement=(
                "An evidence item is linked to a control only when it carries this "
                "share of the control's own terms, matched on whole words. Relative "
                "rather than absolute, so a richly described control is not easier to "
                "satisfy than a sparse one."
            ),
            value=f"{RELEVANCE_THRESHOLD:.0%} of the control's terms",
        ),
        MethodRule(
            name="Evidence freshness",
            source=ICIT_POLICY,
            statement=(
                "Evidence outside its currency window does not support a control. The "
                "windows are Iron City's, derived from the evidence class rather than "
                "from any standard, and a manifest may override the window for an "
                "individual item."
            ),
            value=_freshness_value(),
        ),
        MethodRule(
            name="Readiness score",
            source=ICIT_POLICY,
            statement=(
                "A weighted percentage computed from the verdicts alone. Controls "
                "scoped out leave the denominator entirely. An accepted risk earns "
                "partial credit: it is known and signed for, which is better than an "
                "unknown gap and is not a working control."
            ),
            value=_credit_value(),
        ),
        MethodRule(
            name="Risk weighting",
            source=ICIT_POLICY,
            statement=(
                "Control families carrying more breach risk weigh more in the score "
                "and sort higher in the remediation plan. The framework itself ranks "
                "no control above another."
            ),
            value=_weight_value(),
        ),
        MethodRule(
            name="Scope and acceptance",
            source=TENANT_POLICY,
            statement=(
                "Controls scoped out, risks formally accepted and remediation owners "
                "come from the client's own policy file. Each carries a written "
                "reason, a named approver and a date, and each is written to the "
                "audit trail. Nothing is scoped out or accepted by the engine."
            ),
        ),
        MethodRule(
            name="AI commentary",
            source=ICIT_POLICY,
            statement=(
                "Automated commentary is carried alongside the assessment as advisory "
                "text. It never moves a verdict and never moves the score, so the "
                "number is reproducible from the control register alone."
            ),
            value="excluded from scoring",
        ),
    ]


def method_dict() -> dict[str, Any]:
    """The basis of assessment, for the stored record."""
    return {
        "sources": dict(SOURCE_LABELS),
        "rules": [rule.to_dict() for rule in method_rules()],
    }
