"""Judge the currency of the evidence behind each passing control.

Control mapping already refuses to count expired evidence. This capability looks
at the evidence that is still inside its window but close to the edge, and at
controls whose whole case rests on a single ageing document. Both are the shape
of a programme that will fail its next audit without anything visibly changing.
"""

from __future__ import annotations

from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult
from ironclad.model.assessment import ControlStatus

# Evidence inside this share of its remaining window is treated as ageing.
AGEING_THRESHOLD = 0.85


class FreshnessCheck(AssessmentModule):
    name = "freshness_check"
    description = "Flag controls whose supporting evidence is ageing or about to expire."
    groups = ("standard", "deep")
    requires = ("control_mapping",)

    def run(self, ctx: AssessmentContext) -> ModuleResult:
        findings: list[Finding] = []
        ageing_controls = 0

        for verdict in ctx.assessment.controls:
            if verdict.status not in (ControlStatus.COMPLIANT, ControlStatus.PARTIAL):
                continue

            ageing: list[str] = []
            for link in verdict.evidence_links:
                artifact = ctx.evidence.get(link.artifact_id)
                if artifact is None or artifact.is_stale(ctx.as_of):
                    continue

                window = (artifact.effective_valid_until - (artifact.valid_from or artifact.collected_at)).days
                if window <= 0:
                    continue
                elapsed = artifact.age_days(ctx.as_of) / window
                if elapsed >= AGEING_THRESHOLD:
                    ageing.append(artifact.name)

            if not ageing:
                continue

            ageing_controls += 1
            verdict.add_note(
                f"Supporting evidence is approaching the end of its currency window: "
                f"{', '.join(ageing)}."
            )
            findings.append(
                Finding(
                    module=self.name,
                    target=verdict.control_id,
                    severity="low",
                    title=f"Evidence is ageing for {verdict.control_id}",
                    detail=(
                        f"{len(ageing)} supporting item(s) are near the end of their currency "
                        f"window. Refresh them before the next audit period or this control "
                        f"will regress without any change to the underlying practice."
                    ),
                    evidence={"control_id": verdict.control_id, "ageing_evidence": ageing},
                )
            )

        single_source = [
            v.control_id
            for v in ctx.assessment.controls
            if v.status is ControlStatus.COMPLIANT and len(v.evidence_links) == 1
        ]

        ctx.module_output[self.name] = {
            "ageing_controls": ageing_controls,
            "single_source_controls": single_source,
        }
        return self.result(
            findings, ageing_controls=ageing_controls, single_source=len(single_source)
        )
