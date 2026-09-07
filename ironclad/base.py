"""The contract every assessment capability implements.

The ICIT module pattern, adapted for an evidence engine. In a scanning tool a
module runs against a network target; here it runs against a tenant's evidence
set and framework, and contributes to one shared Assessment. Everything else is
the same on purpose: one capability per file, a name and a client-safe
description, group membership for presets, and a catalog that the CLI and the
dashboard both render from.

Modules are cooperative, not independent — control mapping must run before
freshness can downgrade a verdict — so a module declares what it `requires` and
the registry orders the run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ironclad.frameworks.crosswalk import Crosswalk
from ironclad.ids import utc_now
from ironclad.model.assessment import Assessment
from ironclad.model.audit import AuditLog
from ironclad.model.control import Framework
from ironclad.model.evidence import EvidenceSet
from ironclad.model.exception import RiskException
from ironclad.model.remediation import RemediationPlan
from ironclad.policy import TenantPolicy

# Shared with the AI consensus engine's finding shape. Anything outside this set
# is a hard error rather than a value that quietly reaches a client report.
SEVERITIES = ("info", "low", "medium", "high", "critical")


@dataclass
class Finding:
    """One observation, in the shape every ICIT product emits.

    `target` is the control the observation is about, which is this product's
    equivalent of a host or URL in a scanning tool.
    """

    module: str
    target: str
    severity: str
    title: str
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"bad severity {self.severity!r}, use one of {SEVERITIES}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "target": self.target,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class AssessmentContext:
    """Everything a module reads from and contributes to.

    One context per run. Modules mutate the shared Assessment, plan and audit
    log rather than returning fragments to be merged, so a downstream module
    always sees what the ones before it decided.
    """

    tenant_id: str
    framework: Framework
    evidence: EvidenceSet
    assessment: Assessment
    audit: AuditLog
    exceptions: list[RiskException] = field(default_factory=list)
    # The tenant's own decisions: what is out of scope, what risk is accepted,
    # who owns which control. None means the client supplied no policy, which is
    # a legitimate state -- it just means nothing can be scoped out or accepted.
    policy: TenantPolicy | None = None
    crosswalk: Crosswalk = field(default_factory=Crosswalk)
    plan: RemediationPlan | None = None
    as_of: datetime = field(default_factory=utc_now)
    actor: str = "system:pipeline"
    warnings: list[str] = field(default_factory=list)
    # Per-module output payloads, keyed by module name. Carried into the stored
    # result so the dashboard can render what each capability produced.
    module_output: dict[str, Any] = field(default_factory=dict)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


@dataclass
class ModuleResult:
    """What one module produced."""

    module: str
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
        }


class AssessmentModule(ABC):
    """One assessment capability."""

    # Set these on each subclass.
    name: str = ""
    # Client-facing. White-labeled: never names an underlying tool or vendor.
    description: str = ""
    groups: tuple[str, ...] = ("standard",)
    # Module names that must have run before this one, enforced by the registry.
    requires: tuple[str, ...] = ()

    @abstractmethod
    def run(self, ctx: AssessmentContext) -> ModuleResult:
        """Contribute to the assessment. Return the findings produced."""
        raise NotImplementedError

    def result(self, findings: list[Finding], **summary: Any) -> ModuleResult:
        """Convenience for subclasses building their return value."""
        return ModuleResult(module=self.name, findings=findings, summary=summary)
