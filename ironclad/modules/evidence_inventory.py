"""Catalogue the evidence set and report what is missing or expired.

Runs first in every group. An assessment against an evidence set nobody has
looked at produces a report full of gaps that are really delivery failures, so
this capability states plainly what arrived, what could not be read, and what
has aged out before any control is judged.
"""

from __future__ import annotations

from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult


class EvidenceInventory(AssessmentModule):
    name = "evidence_inventory"
    description = "Catalogue submitted evidence and flag missing, unreadable or expired items."
    groups = ("quick", "standard", "deep")

    def run(self, ctx: AssessmentContext) -> ModuleResult:
        findings: list[Finding] = []
        artifacts = list(ctx.evidence)
        stale = ctx.evidence.stale(ctx.as_of)
        unreadable = [a for a in artifacts if not a.text]

        if not artifacts:
            findings.append(
                Finding(
                    module=self.name,
                    target="evidence-set",
                    severity="critical",
                    title="No evidence was submitted",
                    detail=(
                        "The assessment ran against an empty evidence set. Every control "
                        "will report as unevidenced until evidence is supplied. Confirm the "
                        "evidence delivery completed before reading the control results."
                    ),
                    evidence={"artifact_count": 0},
                )
            )

        for artifact in stale:
            findings.append(
                Finding(
                    module=self.name,
                    target="evidence-set",
                    severity="medium",
                    title=f"Evidence has aged out: {artifact.name}",
                    detail=(
                        f"This item was collected {artifact.age_days(ctx.as_of)} days ago and "
                        f"passed its currency window on "
                        f"{artifact.effective_valid_until.date().isoformat()}. Evidence outside "
                        f"its window does not support a control at audit."
                    ),
                    evidence={
                        "artifact_id": artifact.artifact_id,
                        "evidence_type": artifact.evidence_type,
                        "valid_until": artifact.effective_valid_until.isoformat(),
                    },
                )
            )

        for artifact in unreadable:
            # An artifact with no extractable text is catalogued but cannot be
            # matched automatically. That is a fact about the pipeline, not a
            # finding against the tenant, so it stays informational.
            findings.append(
                Finding(
                    module=self.name,
                    target="evidence-set",
                    severity="info",
                    title=f"Evidence could not be read automatically: {artifact.name}",
                    detail=(
                        "The item is recorded in the evidence register and remains available "
                        "for manual review, but contributed no automatic control matches."
                    ),
                    evidence={"artifact_id": artifact.artifact_id, "uri": artifact.uri},
                )
            )

        ctx.module_output[self.name] = {
            "artifact_count": len(artifacts),
            "stale_count": len(stale),
            "unreadable_count": len(unreadable),
            "artifacts": [a.to_dict() for a in artifacts],
        }

        return self.result(
            findings,
            artifacts=len(artifacts),
            stale=len(stale),
            unreadable=len(unreadable),
        )
