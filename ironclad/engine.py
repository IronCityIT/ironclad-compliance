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
from ironclad.method import method_dict
from ironclad.model.assessment import Assessment
from ironclad.model.audit import AuditLog
from ironclad.model.control import Framework
from ironclad.model.evidence import EvidenceSet
from ironclad.model.exception import RiskException
from ironclad.model.remediation import RemediationPlan
from ironclad.policy import TenantPolicy
from ironclad.version import __version__
from ironclad.white_label import redact


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
            # Which bars were the framework's and which were ours. Stored, not
            # only rendered, so the machine record an auditor is handed can be
            # read back years later without the report beside it.
            "method": method_dict(),
            "warnings": list(self.warnings),
            "failed_modules": dict(self.failed_modules),
            "audit": self.audit.to_dict(),
        }

    def consensus_payload(self) -> str:
        """Base64 findings, as the consensus-engine `workflow_call` contract wants.

        The engine's `findings_json` input is base64-encoded JSON — passing raw
        JSON there produces an analysis over nothing. What goes in it is the
        subset `consensus_findings` chooses, not every finding: see there.
        """
        encoded = json.dumps(consensus_findings(self.findings_payload()), separators=(",", ":"))
        return base64.b64encode(encoded.encode("utf-8")).decode("ascii")


#: The most findings sent for AI analysis in one assessment. The consensus
#: engine queries fifteen models per finding, sequentially per finding, so
#: this number is the cost and the wall-clock of the AI stage. The first dry
#: run sent 57 and took the better part of an hour.
CONSENSUS_MAX_FINDINGS = 25

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def consensus_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The subset of findings sent for AI analysis, in the order it is sent.

    The consensus engine answers with one result per finding, index-aligned,
    and echoes nothing that identifies which finding a result is about. So this
    function is the contract between the payload and the merge: both call it
    over the same stored findings and get the same list in the same order.

    Three rules, each because of what the first real run showed:

    - **One item per control.** The control mapping and the remediation plan
      both raise a finding for the same gap, so half the payload was the other
      half restated and the AI analysed every gap twice.
    - **Gaps only.** An `info` finding — crosswalk coverage, a note — has no
      severity to triage.
    - **Most severe first, capped.** Fifteen model calls per item; the cap is
      the bound on cost and time, and it drops the least severe.
    """
    chosen: dict[str, dict[str, Any]] = {}
    for finding in findings:
        if finding.get("severity", "info") == "info":
            continue
        target = str(finding.get("target", ""))
        current = chosen.get(target)
        if current is None or _SEVERITY_RANK.get(
            finding.get("severity", ""), 0
        ) > _SEVERITY_RANK.get(current.get("severity", ""), 0):
            chosen[target] = finding
    ordered = sorted(
        chosen.values(),
        key=lambda f: -_SEVERITY_RANK.get(f.get("severity", ""), 0),
    )
    return ordered[:CONSENSUS_MAX_FINDINGS]


def run_assessment(
    tenant_id: str,
    framework: Framework | str,
    evidence: EvidenceSet,
    modules: list[str] | None = None,
    group: str | None = None,
    exceptions: list[RiskException] | None = None,
    policy: TenantPolicy | None = None,
    crosswalk: Crosswalk | None = None,
    assessment_type: str = "full",
    assessment_id: str = "",
    actor: str = "system:pipeline",
    as_of: datetime | None = None,
    framework_dir: Path | None = None,
    previous: dict[str, Any] | None = None,
) -> RunResult:
    """Run the selected capabilities against one tenant's evidence.

    `previous` is the tenant's last stored assessment, when the caller has it:
    remediation items it still carries keep their first-raised and target
    dates rather than being re-dated to today.
    """
    now = as_of or utc_now()
    tenant = slugify(tenant_id)

    if isinstance(framework, str):
        framework = load_framework(framework, framework_dir)

    if policy is not None and policy.tenant_id != tenant:
        # Applying one client's scope-outs and acceptances to another client's
        # assessment has to be impossible, not merely unlikely.
        raise ValueError(f"tenant policy belongs to {policy.tenant_id!r}, not {tenant!r}")

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
            "policy": policy.source if policy is not None else None,
            "scope_exclusions": len(policy.exclusions) if policy is not None else 0,
        },
        at=now,
    )

    # Acceptances come from the policy unless the caller passed them directly
    # (the service layer reads them from its own store instead).
    resolved_exceptions = (
        list(exceptions)
        if exceptions is not None
        else (list(policy.exceptions) if policy is not None else [])
    )

    ctx = AssessmentContext(
        tenant_id=tenant,
        framework=framework,
        evidence=evidence,
        assessment=assessment,
        audit=audit,
        exceptions=resolved_exceptions,
        policy=policy,
        crosswalk=crosswalk if crosswalk is not None else load_crosswalks(),
        previous=previous,
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


def merge_consensus(result: Any, consensus_b64: str) -> dict[str, Any]:
    """Fold the AI engine's base64 consensus output into the result.

    Decoding is defensive on purpose: the consensus engine documents that its
    output is empty when analysis fails, and an assessment must still be stored
    and reported when the AI enrichment did not come back.

    The engine's output is one `ConsensusResult` per finding sent — a JSON
    list, or a bare object when exactly one finding was sent — carrying
    `consensus_severity`, `confidence_percent`, `aggregated_remediation` and
    model counts, and nothing that names the finding. Results are matched to
    findings by position over `consensus_findings`, which is the same list the
    payload was built from. The first version of this function treated a list
    as an unexpected shape, so every real assessment discarded its analysis.

    `result` is a `RunResult` or the stored-result stand-in the report job
    rebuilds; both carry `findings_payload()`, `assessment` and `warnings`.
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

    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        result.warnings.append("AI consensus output was neither an object nor a list of them")
        result.assessment.consensus = {"status": "unexpected_shape"}
        return result.assessment.consensus

    sent = consensus_findings(result.findings_payload())
    if len(payload) != len(sent):
        result.warnings.append(
            f"AI consensus returned {len(payload)} result(s) for {len(sent)} finding(s) sent; "
            "matched by position as far as they go"
        )

    results: list[dict[str, Any]] = []
    responded = 0
    asked = 0
    redactions: list[int] = []
    for finding, item in zip(sent, payload, strict=False):
        successful = int(item.get("successful_models") or 0)
        total = int(item.get("total_models") or 0)
        responded += successful
        asked += total
        results.append(
            {
                "target": finding.get("target", ""),
                "title": finding.get("title", ""),
                "severity": str(item.get("consensus_severity", "")).lower(),
                "confidence": _number(item.get("confidence_percent")),
                "exploitability": item.get("exploitability", ""),
                "impact": item.get("impact", ""),
                "false_positive_likelihood": item.get("false_positive_likelihood", ""),
                "remediation": [
                    _white_labelled(str(r), redactions)
                    for r in (item.get("aggregated_remediation") or [])[:5]
                ],
                "verification": [
                    _white_labelled(str(v), redactions)
                    for v in (item.get("verification_steps") or [])[:5]
                ],
                "models_responded": successful,
                "models_asked": total,
            }
        )

    if results and responded == 0:
        # The engine ran and every model failed — a key missing on every
        # provider, or all of them down. That is not commentary, and it is
        # reported as its own state rather than as a low-confidence "ok".
        result.warnings.append("AI consensus ran but no model responded; commentary unavailable")
        result.assessment.consensus = {"status": "no_models", "analysed": len(results)}
        return result.assessment.consensus

    confidences = [r["confidence"] for r in results if r["confidence"] is not None]
    top = max(results, key=lambda r: _SEVERITY_RANK.get(r["severity"], -1), default=None)
    severity = top["severity"] if top else ""
    confidence = round(sum(confidences) / len(confidences), 1) if confidences else None
    engine_version = str((payload[0] if payload else {}).get("engine_version", ""))

    merged: dict[str, Any] = {
        "status": "ok",
        "engine_version": engine_version,
        "analysed": len(results),
        "sent": len(sent),
        "severity": severity,
        "confidence": confidence,
        "models_responded": responded,
        "models_asked": asked,
        "summary": _consensus_summary(results, severity, confidence),
        "results": results,
        # The models' advice is stored on the record and shipped in the
        # auditor package, which the gates cannot scan at run time. A tool
        # named in it is replaced before it lands, and the count says so.
        "redacted_tool_names": sum(redactions),
    }
    if sum(redactions):
        result.warnings.append(
            f"AI commentary named an underlying tool {sum(redactions)} time(s); "
            f"replaced before storage"
        )
    result.assessment.consensus = merged
    result.audit.record(
        actor="system:pipeline",
        action="assessment.consensus_merged",
        object_type="assessment",
        object_id=result.assessment.assessment_id,
        metadata={"severity": severity, "confidence": confidence, "analysed": len(results)},
    )
    return merged


def _white_labelled(text: str, redactions: list[int]) -> str:
    cleaned, count = redact(text)
    redactions.append(count)
    return cleaned


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _consensus_summary(
    results: list[dict[str, Any]], severity: str, confidence: float | None
) -> str:
    """One sentence for the report, from the numbers rather than from a model.

    The models' free text is not quoted on the client's report: fifteen of
    them produced it, none of them is named there, and a sentence generated
    from the counts says what the analysis found without putting any model's
    wording under Iron City's name.
    """
    if not results:
        return ""
    counts: dict[str, int] = {}
    for item in results:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    parts = [
        f"{n} rated {label}"
        for label, n in sorted(counts.items(), key=lambda kv: -_SEVERITY_RANK.get(kv[0], -1))
        if label
    ]
    conf = f" at {confidence:.0f}% mean confidence" if confidence is not None else ""
    return (
        f"Independent analysis of the {len(results)} most significant gap(s){conf}: "
        + ", ".join(parts)
        + "."
    )
