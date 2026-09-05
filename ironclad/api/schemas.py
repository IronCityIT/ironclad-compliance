"""Request and response contracts for the service surface.

These are the shapes the Cloud Function boundary and the dashboard send. They
validate the same way the evidence manifest does — every fault reported at once,
nothing coerced silently — because a request that is half-understood produces an
assessment that is confidently wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ironclad.frameworks.loader import FRAMEWORK_ALIASES
from ironclad.ids import slugify

ASSESSMENT_TYPES = ("full", "gap-only", "readiness")
MAX_JUSTIFICATION = 4000


@dataclass
class AssessmentRequest:
    """Ask for an assessment run."""

    tenant_id: str
    framework: str
    evidence_path: str = ""
    assessment_type: str = "full"
    modules: list[str] = field(default_factory=list)
    group: str = ""
    assessment_id: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssessmentRequest:
        # client_id and client_name are the names the standard ICIT workflow
        # inputs use; accept either rather than making callers translate.
        tenant = payload.get("tenant_id") or payload.get("client_id") or payload.get("client_name")
        modules = payload.get("modules") or []
        if isinstance(modules, str):
            modules = [m.strip() for m in modules.split(",") if m.strip()]
        return cls(
            tenant_id=slugify(str(tenant or "")),
            framework=str(payload.get("framework", "")).strip(),
            evidence_path=str(payload.get("evidence_path", "")).strip(),
            assessment_type=str(payload.get("assessment_type", "full")).strip() or "full",
            modules=[str(m) for m in modules],
            group=str(payload.get("group", "")).strip(),
            assessment_id=str(payload.get("assessment_id", "")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "framework": self.framework,
            "evidence_path": self.evidence_path,
            "assessment_type": self.assessment_type,
            "modules": list(self.modules),
            "group": self.group,
            "assessment_id": self.assessment_id,
        }


def validate_assessment_request(request: AssessmentRequest) -> list[str]:
    errors: list[str] = []
    if not request.tenant_id:
        errors.append("tenant_id (or client_id) is required")
    if not request.framework:
        errors.append("framework is required")
    elif request.framework not in FRAMEWORK_ALIASES and not request.framework.endswith(".json"):
        errors.append(f"framework {request.framework!r} is not one of {sorted(FRAMEWORK_ALIASES)}")
    if request.assessment_type not in ASSESSMENT_TYPES:
        errors.append(f"assessment_type must be one of {list(ASSESSMENT_TYPES)}")
    if request.modules and request.group:
        errors.append("give either modules or group, not both")
    return errors


@dataclass
class ExceptionRequest:
    """Ask to record a risk acceptance."""

    tenant_id: str
    control_id: str
    justification: str
    requested_by: str
    compensating_controls: list[str] = field(default_factory=list)
    expires_in_days: int = 90

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ExceptionRequest:
        compensating = payload.get("compensating_controls") or []
        if isinstance(compensating, str):
            compensating = [c.strip() for c in compensating.split(",") if c.strip()]
        return cls(
            tenant_id=slugify(str(payload.get("tenant_id") or payload.get("client_id") or "")),
            control_id=str(payload.get("control_id", "")).strip(),
            justification=str(payload.get("justification", "")).strip(),
            requested_by=str(payload.get("requested_by", "")).strip(),
            compensating_controls=[str(c) for c in compensating],
            expires_in_days=int(payload.get("expires_in_days", 90) or 90),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "control_id": self.control_id,
            "justification": self.justification,
            "requested_by": self.requested_by,
            "compensating_controls": list(self.compensating_controls),
            "expires_in_days": self.expires_in_days,
        }


def validate_exception_request(request: ExceptionRequest) -> list[str]:
    errors: list[str] = []
    if not request.tenant_id:
        errors.append("tenant_id is required")
    if not request.control_id:
        errors.append("control_id is required")
    if not request.justification:
        errors.append("justification is required — an acceptance with no reason is just a gap")
    elif len(request.justification) > MAX_JUSTIFICATION:
        errors.append(f"justification must be under {MAX_JUSTIFICATION} characters")
    if not request.requested_by:
        errors.append("requested_by is required")
    if request.expires_in_days < 1:
        errors.append("expires_in_days must be at least 1")
    return errors


@dataclass
class ServiceResponse:
    """What every service call returns. Uniform so callers handle one shape."""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def failure(cls, *errors: str) -> ServiceResponse:
        return cls(ok=False, errors=list(errors))

    @classmethod
    def success(cls, **data: Any) -> ServiceResponse:
        return cls(ok=True, data=data)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "errors": list(self.errors)}
