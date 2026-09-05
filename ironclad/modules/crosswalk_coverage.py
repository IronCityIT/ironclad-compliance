"""Project the assessed verdicts onto the other supported frameworks.

The commercial answer to "we did SOC 2, how far are we from HIPAA". Every
projected verdict is marked as inherited and names the control it came from, so
nothing here can be mistaken for a direct assessment of the target framework.
"""

from __future__ import annotations

from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult
from ironclad.frameworks.loader import FRAMEWORK_ALIASES, load_framework
from ironclad.model.assessment import ControlStatus


class CrosswalkCoverage(AssessmentModule):
    name = "crosswalk_coverage"
    description = (
        "Project assessed control verdicts onto the other supported frameworks "
        "to show what is already covered."
    )
    groups = ("deep",)
    requires = ("control_mapping",)

    def run(self, ctx: AssessmentContext) -> ModuleResult:
        findings: list[Finding] = []

        if len(ctx.crosswalk) == 0:
            ctx.warn("no crosswalks are loaded; cross-framework coverage was not computed")
            ctx.module_output[self.name] = {"projections": {}}
            return self.result(findings, projections=0)

        verdicts = {
            v.control_id: v.status
            for v in ctx.assessment.controls
            if v.status in (ControlStatus.COMPLIANT, ControlStatus.PARTIAL, ControlStatus.GAP)
        }

        projections: dict[str, dict] = {}
        source_id = ctx.framework.id

        for alias in sorted(FRAMEWORK_ALIASES):
            try:
                target = load_framework(alias)
            except Exception as exc:  # noqa: BLE001 — a missing target must not fail the run
                ctx.warn(f"could not load {alias} for cross-framework coverage: {exc}")
                continue
            if target.id == source_id:
                continue

            inherited = ctx.crosswalk.inherit(source_id, verdicts, target.id)
            if not inherited:
                continue

            target_ids = [c.id for c in target.controls]
            mapped_share = ctx.crosswalk.coverage(source_id, target.id, target_ids)
            satisfied = [
                v for v in inherited.values() if v.status is ControlStatus.COMPLIANT
            ]

            projections[target.id] = {
                "framework": target.to_dict(),
                "mapped_share": mapped_share,
                "projected_controls": len(inherited),
                "projected_satisfied": len(satisfied),
                "projected_readiness": round(100.0 * len(satisfied) / len(target_ids), 1),
                "unmapped_controls": sorted(set(target_ids) - set(inherited)),
                "verdicts": {cid: v.to_dict() for cid, v in sorted(inherited.items())},
            }

            findings.append(
                Finding(
                    module=self.name,
                    target=target.id,
                    severity="info",
                    title=(
                        f"{target.name} is {round(100 * mapped_share)}% addressed by this "
                        f"assessment"
                    ),
                    detail=(
                        f"{len(satisfied)} of {len(target_ids)} {target.name} controls are "
                        f"already satisfied by evidence supplied for {ctx.framework.name}. "
                        f"{len(target_ids) - len(inherited)} control(s) have no mapping and "
                        f"would need to be assessed directly."
                    ),
                    evidence={
                        "target_framework": target.id,
                        "mapped_share": mapped_share,
                        "projected_satisfied": len(satisfied),
                        "target_control_count": len(target_ids),
                    },
                )
            )

        ctx.module_output[self.name] = {"source_framework": source_id, "projections": projections}
        return self.result(findings, projections=len(projections))
