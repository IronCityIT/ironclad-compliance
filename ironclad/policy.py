"""Tenant policy: the client-specific decisions an assessment must honour.

Three things a real compliance programme needs to say about itself, none of
which could reach the engine before this existed:

  scoping     "this control does not apply to us, and here is who decided that"
  acceptance  "this control is not met, we have signed for the risk, until when"
  ownership   "this control is the platform team's, route its work to them"

Without a policy file the pipeline could never produce a `not_applicable` or an
`accepted_risk` verdict, so the whole risk-acceptance model — approval, expiry,
compensating controls — was unreachable from `ironclad assess`.

Scoping is held to the same bar as acceptance, and deliberately so. "Not
applicable" is the cheapest way for a client to make a failing control disappear,
so it requires a written justification and a named approver, and every
determination is written to the audit trail. A scope-out nobody signed is not a
scope-out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ironclad.errors import ExceptionWorkflowError, ValidationError
from ironclad.ids import iso, slugify, utc_now
from ironclad.model.exception import ExceptionStatus, RiskException, new_exception_id

POLICY_VERSION = "1.0"
SUPPORTED_POLICY_VERSIONS = frozenset({"1.0"})

POLICY_FILENAMES = ("policy.json", "tenant-policy.json")


def _parse_moment(value: Any, field_name: str, errors: list[str]) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field_name} is not an ISO-8601 timestamp: {value!r}")
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class ScopeExclusion:
    """A control the tenant has determined does not apply to them."""

    control_id: str
    justification: str
    approved_by: str
    approved_at: datetime = field(default_factory=utc_now)
    review_by: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "justification": self.justification,
            "approved_by": self.approved_by,
            "approved_at": iso(self.approved_at),
            "review_by": iso(self.review_by) if self.review_by else None,
        }


@dataclass
class TenantPolicy:
    """Everything a tenant has decided about how it is assessed."""

    tenant_id: str
    exclusions: list[ScopeExclusion] = field(default_factory=list)
    exceptions: list[RiskException] = field(default_factory=list)
    owners: dict[str, str] = field(default_factory=dict)
    source: str = ""

    def exclusion_for(self, control_id: str) -> ScopeExclusion | None:
        for exclusion in self.exclusions:
            if exclusion.control_id == control_id:
                return exclusion
        return None

    def owner_for(self, control_id: str) -> str:
        """The owner of a control, falling back to a family-wide assignment.

        A programme assigns "all of CC6 belongs to the platform team" far more
        often than it assigns 33 controls one at a time.
        """
        if control_id in self.owners:
            return self.owners[control_id]
        for key, owner in self.owners.items():
            if key.endswith("*") and control_id.startswith(key[:-1]):
                return owner
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": POLICY_VERSION,
            "tenant_id": self.tenant_id,
            "source": self.source,
            "scope_exclusions": [e.to_dict() for e in self.exclusions],
            "exceptions": [e.to_dict() for e in self.exceptions],
            "owners": dict(self.owners),
        }


def validate_policy(document: Any) -> list[str]:
    """Every problem with a policy document. Empty list means it is loadable."""
    errors: list[str] = []

    if not isinstance(document, dict):
        return ["tenant policy must be a JSON object"]

    version = str(document.get("policy_version", "")).strip()
    if not version:
        errors.append("policy_version is required")
    elif version not in SUPPORTED_POLICY_VERSIONS:
        errors.append(
            f"policy_version {version!r} is not supported "
            f"(this engine speaks {', '.join(sorted(SUPPORTED_POLICY_VERSIONS))})"
        )

    if not str(document.get("tenant_id", "")).strip():
        errors.append("tenant_id is required")

    exclusions = document.get("scope_exclusions", [])
    if not isinstance(exclusions, list):
        errors.append("'scope_exclusions' must be an array")
    else:
        seen: set[str] = set()
        for index, raw in enumerate(exclusions):
            where = f"scope_exclusions[{index}]"
            if not isinstance(raw, dict):
                errors.append(f"{where} must be an object")
                continue
            control_id = str(raw.get("control_id", "")).strip()
            if not control_id:
                errors.append(f"{where}.control_id is required")
            elif control_id in seen:
                errors.append(f"{where}.control_id {control_id!r} is excluded twice")
            else:
                seen.add(control_id)
            # A scope-out with no reason and no name against it is how a failing
            # control quietly disappears. Both are mandatory.
            if not str(raw.get("justification", "")).strip():
                errors.append(
                    f"{where}({control_id}).justification is required — a control cannot be "
                    f"scoped out without a written reason"
                )
            if not str(raw.get("approved_by", "")).strip():
                errors.append(
                    f"{where}({control_id}).approved_by is required — someone must own the "
                    f"decision that this control does not apply"
                )
            _parse_moment(raw.get("approved_at"), f"{where}.approved_at", errors)
            _parse_moment(raw.get("review_by"), f"{where}.review_by", errors)

    raw_exceptions = document.get("exceptions", [])
    if not isinstance(raw_exceptions, list):
        errors.append("'exceptions' must be an array")
    else:
        seen_controls: set[str] = set()
        for index, raw in enumerate(raw_exceptions):
            where = f"exceptions[{index}]"
            if not isinstance(raw, dict):
                errors.append(f"{where} must be an object")
                continue
            control_id = str(raw.get("control_id", "")).strip()
            if not control_id:
                errors.append(f"{where}.control_id is required")
            elif control_id in seen_controls:
                errors.append(f"{where}.control_id {control_id!r} has two acceptances")
            else:
                seen_controls.add(control_id)
            for key in ("justification", "requested_by"):
                if not str(raw.get(key, "")).strip():
                    errors.append(f"{where}({control_id}).{key} is required")

            status = str(raw.get("status", "approved")).strip()
            valid_statuses = {member.value for member in ExceptionStatus}
            if status not in valid_statuses:
                errors.append(f"{where}.status {status!r} is not one of {sorted(valid_statuses)}")
            elif status == ExceptionStatus.APPROVED.value:
                # An approved acceptance in a policy file must carry the
                # evidence of its approval, or it is just an assertion.
                if not str(raw.get("approved_by", "")).strip():
                    errors.append(
                        f"{where}({control_id}).approved_by is required for an approved acceptance"
                    )
                if not raw.get("expires_at"):
                    errors.append(
                        f"{where}({control_id}).expires_at is required for an approved "
                        f"acceptance — an open-ended acceptance is an unfixed gap"
                    )

            _parse_moment(raw.get("requested_at"), f"{where}.requested_at", errors)
            _parse_moment(raw.get("approved_at"), f"{where}.approved_at", errors)
            _parse_moment(raw.get("expires_at"), f"{where}.expires_at", errors)

            compensating = raw.get("compensating_controls", [])
            if not isinstance(compensating, list):
                errors.append(f"{where}.compensating_controls must be an array")

    owners = document.get("owners", {})
    if not isinstance(owners, dict):
        errors.append("'owners' must be an object mapping control ids to owners")
    elif not all(isinstance(k, str) and isinstance(v, str) for k, v in owners.items()):
        errors.append("'owners' keys and values must all be strings")

    return errors


def policy_from_document(document: dict[str, Any]) -> TenantPolicy:
    """Build the policy. Assumes the document has already validated."""
    tenant_id = slugify(str(document["tenant_id"]))
    now = utc_now()

    exclusions = [
        ScopeExclusion(
            control_id=str(raw["control_id"]).strip(),
            justification=str(raw["justification"]).strip(),
            approved_by=str(raw["approved_by"]).strip(),
            approved_at=_parse_moment(raw.get("approved_at"), "", []) or now,
            review_by=_parse_moment(raw.get("review_by"), "", []),
        )
        for raw in document.get("scope_exclusions", [])
    ]

    exceptions: list[RiskException] = []
    for raw in document.get("exceptions", []):
        requested_at = _parse_moment(raw.get("requested_at"), "", []) or now
        control_id = str(raw["control_id"]).strip()
        expires_at = _parse_moment(raw.get("expires_at"), "", [])

        exception = RiskException(
            exception_id=str(
                raw.get("exception_id") or new_exception_id(tenant_id, control_id, requested_at)
            ),
            tenant_id=tenant_id,
            control_id=control_id,
            justification=str(raw["justification"]).strip(),
            requested_by=str(raw["requested_by"]).strip(),
            compensating_controls=[str(c) for c in raw.get("compensating_controls", [])],
            requested_at=requested_at,
            expires_at=expires_at,
        )

        # Replay the workflow rather than assigning the end state, so a policy
        # file cannot smuggle in an approval that the workflow would refuse —
        # a self-approval, most importantly.
        status = str(raw.get("status", "approved"))
        if status in (ExceptionStatus.PENDING_APPROVAL.value, ExceptionStatus.APPROVED.value):
            exception.submit()
        if status == ExceptionStatus.APPROVED.value:
            exception.approve(
                str(raw["approved_by"]).strip(),
                at=_parse_moment(raw.get("approved_at"), "", []) or requested_at,
            )
        elif status == ExceptionStatus.REJECTED.value:
            exception.reject(str(raw.get("approved_by", "")), str(raw.get("note", "rejected")))
        elif status == ExceptionStatus.REVOKED.value:
            exception.revoke(str(raw.get("approved_by", "")), str(raw.get("note", "revoked")))

        exceptions.append(exception)

    return TenantPolicy(
        tenant_id=tenant_id,
        exclusions=exclusions,
        exceptions=exceptions,
        owners={str(k): str(v) for k, v in document.get("owners", {}).items()},
    )


def load_policy(path: Path, expected_tenant: str = "") -> TenantPolicy:
    """Read, validate and build a tenant policy.

    A policy naming a different tenant is refused rather than adapted: applying
    one client's scope-outs and acceptances to another client's assessment is
    the kind of mistake that has to be impossible.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc

    errors = validate_policy(document)
    if errors:
        raise ValidationError(f"{path.name} is not a valid tenant policy", errors)

    try:
        policy = policy_from_document(document)
    except ExceptionWorkflowError as exc:
        raise ValidationError(
            f"{path.name} contains a risk acceptance the approval workflow refuses", [str(exc)]
        ) from exc

    if expected_tenant and policy.tenant_id != slugify(expected_tenant):
        raise ValidationError(
            f"{path.name} belongs to tenant {policy.tenant_id!r}, "
            f"but the assessment is for {slugify(expected_tenant)!r}"
        )

    policy.source = str(path)
    return policy


def find_policy(directory: Path) -> Path | None:
    """A policy file sitting alongside the evidence, if there is one."""
    for filename in POLICY_FILENAMES:
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None
