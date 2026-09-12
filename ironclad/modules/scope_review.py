"""Apply the tenant's scoping determinations, and keep them honest.

A control scoped out is removed from the readiness denominator entirely, so
scoping is the cheapest way to make a failing control disappear from a report.
That makes it worth auditing, and this capability is where that happens:

  * a scope-out is applied only if the control actually exists in the framework
  * every determination is written to the audit trail with who signed it
  * a determination past its review date is reported, because "not applicable"
    was true about a business three years ago and may not be true now
  * a scoped-out control that the evidence nonetheless supports is flagged — it
    usually means the scope-out is stale rather than that the evidence is wrong

Runs after control mapping so it can see what the evidence actually said before
setting the control aside.
"""

from __future__ import annotations

from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult
from ironclad.model.assessment import ControlStatus

# Warn this far ahead of a scoping determination falling due for review.
REVIEW_WARNING_DAYS = 30


class ScopeReview(AssessmentModule):
    name = "scope_review"
    description = "Apply the client's scoping determinations and flag any that need re-examining."
    groups = ("standard", "deep")
    requires = ("control_mapping",)

    def run(self, ctx: AssessmentContext) -> ModuleResult:
        findings: list[Finding] = []
        policy = ctx.policy

        if policy is None or not policy.exclusions:
            ctx.module_output[self.name] = {"excluded": 0, "exclusions": []}
            return self.result(findings, excluded=0)

        applied = 0
        for exclusion in policy.exclusions:
            verdict = ctx.assessment.get(exclusion.control_id)
            if verdict is None:
                ctx.warn(
                    f"the scope exclusion for {exclusion.control_id} names a control that is "
                    f"not in {ctx.framework.key}"
                )
                continue

            had_evidence = bool(verdict.evidence_links)
            was = verdict.status

            verdict.status = ControlStatus.NOT_APPLICABLE
            verdict.rationale = (
                f"Scoped out of this assessment. {exclusion.justification} "
                f"Determined by {exclusion.approved_by} on "
                f"{exclusion.approved_at.date().isoformat()}."
            )
            verdict.add_note(f"Excluded from scope by {exclusion.approved_by}.")
            applied += 1

            ctx.audit.record(
                actor=ctx.actor,
                action="scope.excluded",
                object_type="control",
                object_id=exclusion.control_id,
                metadata={
                    "approved_by": exclusion.approved_by,
                    "justification": exclusion.justification,
                    "previous_status": str(was),
                },
                at=ctx.as_of,
            )

            if had_evidence:
                # Evidence exists for a control the client says does not apply.
                # Nearly always the scope-out has outlived the business reason
                # for it, so it is worth surfacing rather than silently honouring.
                findings.append(
                    Finding(
                        module=self.name,
                        target=exclusion.control_id,
                        severity="low",
                        title=f"Scoped-out control has supporting evidence: {exclusion.control_id}",
                        detail=(
                            "This control is excluded from scope, but submitted evidence "
                            "matches it. That usually means the exclusion has outlived its "
                            "reason. Re-examine whether it still does not apply."
                        ),
                        evidence={
                            "control_id": exclusion.control_id,
                            "approved_by": exclusion.approved_by,
                            "evidence_count": len(verdict.evidence_links),
                        },
                    )
                )

            if exclusion.review_by is not None:
                days = (exclusion.review_by - ctx.as_of).days
                if days < 0:
                    findings.append(
                        Finding(
                            module=self.name,
                            target=exclusion.control_id,
                            severity="medium",
                            title=(
                                f"Scoping determination is overdue for review: "
                                f"{exclusion.control_id}"
                            ),
                            detail=(
                                f"The exclusion fell due for review "
                                f"{abs(days)} day(s) ago. An auditor will ask whether it still "
                                f"holds, and the assessment cannot answer that."
                            ),
                            evidence={
                                "control_id": exclusion.control_id,
                                "review_by": exclusion.review_by.isoformat(),
                                "days_overdue": abs(days),
                            },
                        )
                    )
                elif days <= REVIEW_WARNING_DAYS:
                    findings.append(
                        Finding(
                            module=self.name,
                            target=exclusion.control_id,
                            severity="low",
                            title=f"Scoping determination falls due for review in {days} day(s)",
                            detail="Confirm the control still does not apply before it lapses.",
                            evidence={
                                "control_id": exclusion.control_id,
                                "review_by": exclusion.review_by.isoformat(),
                            },
                        )
                    )

        ctx.module_output[self.name] = {
            "excluded": applied,
            "exclusions": [e.to_dict() for e in policy.exclusions],
        }
        return self.result(findings, excluded=applied)
