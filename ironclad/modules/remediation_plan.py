"""Turn every failing verdict into a prioritised, dated unit of work.

A report that ends at "these controls are gaps" leaves the hardest question
unanswered. This capability produces the ordered plan: what to fix, in what
order, by when, and what evidence closes it.

Guidance is drawn from the control's own expected evidence types rather than
generated prose, so it says exactly what the assessment will accept next time.
"""

from __future__ import annotations

from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult
from ironclad.model.assessment import ControlStatus
from ironclad.model.remediation import RemediationPlan, build_item

# Verdicts that generate work. Accepted risk does not: it is tracked through the
# exception's own expiry, and duplicating it as an open task would double-count
# the same decision.
ACTIONABLE = (ControlStatus.GAP, ControlStatus.PARTIAL, ControlStatus.PENDING)


class RemediationPlanning(AssessmentModule):
    name = "remediation_plan"
    description = "Produce a prioritised remediation plan with owners, due dates and required evidence."
    groups = ("standard", "deep")
    # exception_review must land first, or this would raise work for controls
    # whose risk has already been formally accepted. Declaring it rather than
    # relying on the registry's ordering happening to come out right.
    requires = ("control_mapping", "exception_review")

    def run(self, ctx: AssessmentContext) -> ModuleResult:
        findings: list[Finding] = []
        plan = ctx.plan or RemediationPlan(
            tenant_id=ctx.tenant_id,
            assessment_id=ctx.assessment.assessment_id,
            generated_at=ctx.as_of,
        )

        for verdict in ctx.assessment.controls:
            if verdict.status not in ACTIONABLE:
                continue

            control = ctx.framework.get(verdict.control_id)
            expected = list(control.common_evidence) if control else []
            supplied = {
                ctx.evidence.get(link.artifact_id).evidence_type.lower()
                for link in verdict.evidence_links
                if ctx.evidence.get(link.artifact_id) is not None
            }
            missing = [e for e in expected if e.lower() not in supplied]

            item = build_item(
                tenant_id=ctx.tenant_id,
                item=verdict,
                guidance=self._guidance(verdict, missing),
                missing_evidence=missing,
                now=ctx.as_of,
            )
            plan.add(item)

            findings.append(
                Finding(
                    module=self.name,
                    target=verdict.control_id,
                    severity=str(item.severity),
                    title=item.title,
                    detail=(
                        f"{item.guidance} Target date "
                        f"{item.due_date.date().isoformat() if item.due_date else 'unset'}."
                    ),
                    evidence={
                        "item_id": item.item_id,
                        "control_id": verdict.control_id,
                        "priority": item.priority,
                        "due_date": item.due_date.isoformat() if item.due_date else None,
                        "required_evidence": missing,
                    },
                )
            )

        ctx.plan = plan
        ctx.module_output[self.name] = plan.to_dict()
        return self.result(findings, items=len(plan), by_severity=plan.by_severity())

    @staticmethod
    def _guidance(verdict, missing: list[str]) -> str:  # type: ignore[no-untyped-def]
        if verdict.status is ControlStatus.GAP:
            opening = "No current evidence supports this control."
        elif verdict.status is ControlStatus.PARTIAL:
            opening = (
                f"The control is partly evidenced "
                f"({int(verdict.coverage * 100)}% of its points of focus)."
            )
        else:
            opening = "This control has not yet been assessed."

        if missing:
            return f"{opening} Supply: {', '.join(missing[:6])}."
        return (
            f"{opening} Strengthen the existing evidence, or record a risk acceptance with "
            f"compensating measures if the control will not be met this period."
        )
