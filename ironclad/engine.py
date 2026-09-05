"""Orchestration: selected capabilities in, a scored Assessment out.

The engine owns the run, not the capabilities. It builds the context, runs the
ordered selection, records the run in the audit log, recomputes the summary and
emits the JSON contract that flows to the AI consensus engine and then to the
storeAssessmentResults Cloud Function.

One capability failing must not lose the whole assessment. A module that raises
is recorded as a failed capability on the result and the run continues, because
a partial assessment with a named failure is worth more to a client than nothing
at all — and hiding the failure would be worse than either.
"""

from __future__ import annotations

import base64
import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ironclad import registry
from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult
from ironclad.frameworks.crosswalk import Crosswalk, load_crosswalks
from ironclad.frameworks.loader import load_framework
from ironclad.ids import assessment_id as mint_assessment_id
from ironclad.ids import slugify, utc_now
from ironclad.model.assessment import Assessment
from ironclad.model.audit import AuditLog
from ironclad.model.control import Framework
from ironclad.model.evidence import EvidenceSet
from ironclad.model.exception import RiskException
from ironclad.model.remediation import RemediationPlan
from ironclad.version import __version__


@dataclass
class RunResult:
    """Everything one engine run produced."""

    assessment: Assessment
    plan: RemediationPlan
    audit: AuditLog
    findings: list[Finding] = field(default_factory=list)
    module_results: list[ModuleResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failed_modules: dict[str, str] = field(default_factory=dict)
    module_output: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed_modules

    def findings_payload(self) -> list[dict[str, Any]]:
        """The findings array, in the shape every ICIT product emits."""
        return [f.to_dict() for f in self.findings]

    def to_dict(self) -> dict[str, Any]:
        """The full result document. This is what gets stored and reported on."""
        return {
            "engine_version": __version__,
            "contract_version": "1.0",
            **self.assessment.to_dict(),
            "findings": self.findings_payload(),
            "remediation": self.plan.to_dict(),
            "module_output": self.module_output,
            "warnings": list(self.warnings),
            "failed_modules": dict(self.failed_modules),
            "audit": self.audit.to_dict(),
        }

    def consensus_payload(self) -> str:
        """Base64 findings, as the consensus-engine `workflow_call` contract wants.

        The engine's `findings_json` input is base64-encoded JSON — passing raw
        JSON there produces an analysis over nothing.
        """
        encoded = json.dumps(self.findings_payload(), separators=(",", ":"))
        return base64.b64encode(encoded.encode("utf-8")).decode("ascii")


def run_assessment(
    tenant_id: str,
    framework: Framework | str,
    evidence: EvidenceSet,
    modules: list[str] | None = None,
    group: str | None = None,
    exceptions: list[RiskException] | None = None,
    crosswalk: Crosswalk | None = None,
    assessment_type: str = "full",
    assessment_id: str = "",
    actor: str = "system:pipeline",
    as_of: datetime | None = None,
    framework_dir: Path | None = None,
) -> RunResult:
    """Run the selected capabilities against one tenant's evidence."""
    now = as_of or utc_now()
    tenant = slugify(tenant_id)

    if isinstance(framework, str):
        framework = load_framework(framework, framework_dir)

    if evidence.tenant_id != tenant:
        # A tenant mismatch here would mean assessing one client's evidence into
        # another client's record. It is not a warning.
        raise ValueError(f"evidence set belongs to tenant {evidence.tenant_id!r}, not {tenant!r}")

    assessment = Assessment(
        assessment_id=assessment_id or mint_assessment_id(tenant, framework.id, now),
        tenant_id=tenant,
        framework=framework,
        started_at=now,
        assessment_type=assessment_type,
    )
    audit = AuditLog(tenant_id=tenant)
    audit.record(
        actor=actor,
        action="assessment.started",
        object_type="assessment",
        object_id=assessment.assessment_id,
        metadata={
            "framework": framework.key,
            "evidence_artifacts": len(evidence),
            "assessment_type": assessment_type,
        },
        at=now,
    )

    ctx = AssessmentContext(
        tenant_id=tenant,
        framework=framework,
        evidence=evidence,
        assessment=assessment,
        audit=audit,
        exceptions=list(exceptions or []),
        crosswalk=crosswalk if crosswalk is not None else load_crosswalks(),
        as_of=now,
        actor=actor,
    )

    reg = registry.discover()
    selected: list[AssessmentModule] = registry.select(reg, modules=modules, group=group)

    result = RunResult(
        assessment=assessment,
        plan=RemediationPlan(
            tenant_id=tenant, assessment_id=assessment.assessment_id, generated_at=now
        ),
        audit=audit,
    )

    for module in selected:
        try:
            produced = module.run(ctx)
        except Exception as exc:  # noqa: BLE001 — one capability must not lose the run
            detail = f"{type(exc).__name__}: {exc}"
            result.failed_modules[module.name] = detail
            ctx.warn(f"capability {module.name!r} failed: {detail}")
            audit.record(
                actor=actor,
                action="assessment.module_failed",
                object_type="assessment",
                object_id=assessment.assessment_id,
                metadata={
                    "module": module.name,
                    "error": detail,
                    "trace": traceback.format_exc(limit=3),
                },
                at=now,
            )
            continue

        assessment.modules_run.append(module.name)
        result.module_results.append(produced)
        result.findings.extend(produced.findings)

    if ctx.plan is not None:
        result.plan = ctx.plan

    assessment.completed_at = utc_now()
    assessment.recompute_summary(
        evidence_count=len(evidence),
        stale_count=len(evidence.stale(now)),
    )
    result.warnings = list(ctx.warnings)
    result.module_output = dict(ctx.module_output)

    audit.record(
        actor=actor,
        action="assessment.completed",
        object_type="assessment",
        object_id=assessment.assessment_id,
        metadata={
            "readiness_score": assessment.summary.readiness_score,
            "gaps": assessment.summary.gap,
            "modules_run": list(assessment.modules_run),
            "failed_modules": sorted(result.failed_modules),
        },
        at=assessment.completed_at,
    )

    return result


def merge_consensus(result: RunResult, consensus_b64: str) -> dict[str, Any]:
    """Fold the AI engine's base64 consensus output into the result.

    Decoding is defensive on purpose: the consensus engine documents that its
    output is empty when analysis fails, and an assessment must still be stored
    and reported when the AI enrichment did not come back.
    """
    if not consensus_b64:
        result.assessment.consensus = {"status": "unavailable"}
        return result.assessment.consensus

    try:
        decoded = base64.b64decode(consensus_b64, validate=True)
        payload = json.loads(decoded.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — bad enrichment must not lose the assessment
        result.warnings.append(f"AI consensus output could not be decoded: {exc}")
        result.assessment.consensus = {"status": "undecodable"}
        return result.assessment.consensus

    if not isinstance(payload, dict):
        result.warnings.append("AI consensus output was not an object")
        result.assessment.consensus = {"status": "unexpected_shape"}
        return result.assessment.consensus

    payload.setdefault("status", "ok")
    result.assessment.consensus = payload
    result.audit.record(
        actor="system:pipeline",
        action="assessment.consensus_merged",
        object_type="assessment",
        object_id=result.assessment.assessment_id,
        metadata={"severity": payload.get("severity"), "confidence": payload.get("confidence")},
    )
    return payload
