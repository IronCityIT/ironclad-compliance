"""The service surface.

Every method takes a Principal and authorizes before it acts. Nothing here
trusts a tenant id that arrived in a request body: the tenant a caller may act
on comes from their verified token, and a request naming a different tenant is
refused rather than reinterpreted.

The store is an interface, not a database. In the pipeline it is backed by
Firestore through the Cloud Function; in tests it is a dict. Keeping the
authorization and workflow rules here rather than in the storage layer means
they hold whichever backing is in use.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from ironclad.api.schemas import (
    AssessmentRequest,
    ExceptionRequest,
    ServiceResponse,
    validate_assessment_request,
    validate_exception_request,
)
from ironclad.engine import RunResult, run_assessment
from ironclad.errors import AuthorizationError, ExceptionWorkflowError, IroncladError
from ironclad.frameworks.crosswalk import Crosswalk
from ironclad.ids import utc_now
from ironclad.model.audit import AuditLog
from ironclad.model.evidence import EvidenceSet
from ironclad.model.exception import ExceptionStatus, RiskException, new_exception_id
from ironclad.model.tenant import authorize


class Store(Protocol):
    """What the service needs from whatever holds the data."""

    def save_assessment(self, tenant_id: str, result: dict[str, Any]) -> None: ...

    def get_assessment(self, tenant_id: str, assessment_id: str) -> dict[str, Any] | None: ...

    def list_assessments(self, tenant_id: str, limit: int = 25) -> list[dict[str, Any]]: ...

    def save_exception(self, tenant_id: str, exception: RiskException) -> None: ...

    def list_exceptions(self, tenant_id: str) -> list[RiskException]: ...

    def append_audit(self, tenant_id: str, events: list[dict[str, Any]]) -> None: ...

    def list_audit(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]: ...


class InMemoryStore:
    """Reference implementation. Partitioned by tenant, like the real one."""

    def __init__(self) -> None:
        self._assessments: dict[str, dict[str, dict[str, Any]]] = {}
        self._exceptions: dict[str, dict[str, RiskException]] = {}
        self._audit: dict[str, list[dict[str, Any]]] = {}

    def save_assessment(self, tenant_id: str, result: dict[str, Any]) -> None:
        self._assessments.setdefault(tenant_id, {})[result["assessment_id"]] = result

    def get_assessment(self, tenant_id: str, assessment_id: str) -> dict[str, Any] | None:
        return self._assessments.get(tenant_id, {}).get(assessment_id)

    def list_assessments(self, tenant_id: str, limit: int = 25) -> list[dict[str, Any]]:
        items = list(self._assessments.get(tenant_id, {}).values())
        items.sort(key=lambda a: a.get("started_at", ""), reverse=True)
        return items[:limit]

    def save_exception(self, tenant_id: str, exception: RiskException) -> None:
        self._exceptions.setdefault(tenant_id, {})[exception.exception_id] = exception

    def get_exception(self, tenant_id: str, exception_id: str) -> RiskException | None:
        return self._exceptions.get(tenant_id, {}).get(exception_id)

    def list_exceptions(self, tenant_id: str) -> list[RiskException]:
        return list(self._exceptions.get(tenant_id, {}).values())

    def append_audit(self, tenant_id: str, events: list[dict[str, Any]]) -> None:
        self._audit.setdefault(tenant_id, []).extend(events)

    def list_audit(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        return self._audit.get(tenant_id, [])[-limit:]


class ComplianceService:
    """The authorized entry point to everything the engine does."""

    def __init__(self, store: Any | None = None, framework_dir: Path | None = None) -> None:
        self.store = store if store is not None else InMemoryStore()
        self.framework_dir = framework_dir

    # ---------------------------------------------------------------- assessments

    def run_assessment(
        self,
        principal: Any,
        request: AssessmentRequest,
        evidence: EvidenceSet,
        crosswalk: Crosswalk | None = None,
        as_of: datetime | None = None,
    ) -> ServiceResponse:
        """Run an assessment and store the result."""
        errors = validate_assessment_request(request)
        if errors:
            return ServiceResponse.failure(*errors)

        try:
            authorize(principal, "assessment:run", request.tenant_id)
        except AuthorizationError as exc:
            return ServiceResponse.failure(str(exc))

        # Exceptions in force are part of the input to an assessment, not
        # something applied to the report afterwards.
        exceptions = self.store.list_exceptions(request.tenant_id)

        try:
            result = run_assessment(
                tenant_id=request.tenant_id,
                framework=request.framework,
                evidence=evidence,
                modules=request.modules or None,
                group=request.group or None,
                exceptions=exceptions,
                crosswalk=crosswalk,
                assessment_type=request.assessment_type,
                assessment_id=request.assessment_id,
                actor=getattr(principal, "user_id", "unknown"),
                as_of=as_of,
                framework_dir=self.framework_dir,
            )
        except (IroncladError, ValueError) as exc:
            return ServiceResponse.failure(str(exc))

        self._persist(request.tenant_id, result)

        return ServiceResponse.success(
            assessment_id=result.assessment.assessment_id,
            summary=result.assessment.summary.to_dict(),
            findings=len(result.findings),
            remediation_items=len(result.plan),
            warnings=result.warnings,
            failed_modules=result.failed_modules,
        )

    def _persist(self, tenant_id: str, result: RunResult) -> None:
        """Store the result and its audit events.

        Exceptions are not re-saved here. The run mutates the same objects the
        store handed out (an expiry sweep can move one to EXPIRED), so writing
        them back is the store's own concern, not a copy made at persist time.
        """
        self.store.save_assessment(tenant_id, result.to_dict())
        self.store.append_audit(tenant_id, [e.to_dict() for e in result.audit.events])

    def get_assessment(self, principal: Any, tenant_id: str, assessment_id: str) -> ServiceResponse:
        try:
            authorize(principal, "assessment:read", tenant_id)
        except AuthorizationError as exc:
            return ServiceResponse.failure(str(exc))

        record = self.store.get_assessment(tenant_id, assessment_id)
        if record is None:
            return ServiceResponse.failure(f"no assessment {assessment_id!r} for this tenant")
        return ServiceResponse.success(assessment=record)

    def list_assessments(self, principal: Any, tenant_id: str, limit: int = 25) -> ServiceResponse:
        try:
            authorize(principal, "assessment:read", tenant_id)
        except AuthorizationError as exc:
            return ServiceResponse.failure(str(exc))
        return ServiceResponse.success(assessments=self.store.list_assessments(tenant_id, limit))

    # ----------------------------------------------------------------- exceptions

    def request_exception(self, principal: Any, request: ExceptionRequest) -> ServiceResponse:
        """Raise a risk acceptance for approval."""
        errors = validate_exception_request(request)
        if errors:
            return ServiceResponse.failure(*errors)

        try:
            authorize(principal, "exception:request", request.tenant_id)
        except AuthorizationError as exc:
            return ServiceResponse.failure(str(exc))

        now = utc_now()
        try:
            exception = RiskException(
                exception_id=new_exception_id(request.tenant_id, request.control_id, now),
                tenant_id=request.tenant_id,
                control_id=request.control_id,
                justification=request.justification,
                requested_by=request.requested_by or getattr(principal, "user_id", ""),
                compensating_controls=list(request.compensating_controls),
                requested_at=now,
                expires_at=now + timedelta(days=request.expires_in_days),
            )
            exception.submit()
        except ExceptionWorkflowError as exc:
            return ServiceResponse.failure(str(exc))

        self.store.save_exception(request.tenant_id, exception)
        self._audit(
            request.tenant_id,
            actor=getattr(principal, "user_id", "unknown"),
            action="exception.requested",
            object_id=exception.exception_id,
            metadata={"control_id": exception.control_id},
        )
        return ServiceResponse.success(exception=exception.to_dict())

    def approve_exception(
        self, principal: Any, tenant_id: str, exception_id: str
    ) -> ServiceResponse:
        """Approve a pending risk acceptance.

        The separation-of-duties rule lives in the model, so it holds no matter
        which surface calls this. The permission check only decides who may
        attempt an approval at all.
        """
        try:
            authorize(principal, "exception:approve", tenant_id)
        except AuthorizationError as exc:
            return ServiceResponse.failure(str(exc))

        exception = self._find_exception(tenant_id, exception_id)
        if exception is None:
            return ServiceResponse.failure(f"no risk acceptance {exception_id!r} for this tenant")

        approver = getattr(principal, "user_id", "")
        try:
            exception.approve(approver)
        except ExceptionWorkflowError as exc:
            return ServiceResponse.failure(str(exc))

        self.store.save_exception(tenant_id, exception)
        self._audit(
            tenant_id,
            actor=approver,
            action="exception.approved",
            object_id=exception.exception_id,
            metadata={
                "control_id": exception.control_id,
                "expires_at": exception.expires_at.isoformat() if exception.expires_at else None,
            },
        )
        return ServiceResponse.success(exception=exception.to_dict())

    def revoke_exception(
        self, principal: Any, tenant_id: str, exception_id: str, reason: str
    ) -> ServiceResponse:
        try:
            authorize(principal, "exception:approve", tenant_id)
        except AuthorizationError as exc:
            return ServiceResponse.failure(str(exc))

        exception = self._find_exception(tenant_id, exception_id)
        if exception is None:
            return ServiceResponse.failure(f"no risk acceptance {exception_id!r} for this tenant")

        actor = getattr(principal, "user_id", "")
        try:
            exception.revoke(actor, reason)
        except ExceptionWorkflowError as exc:
            return ServiceResponse.failure(str(exc))

        self.store.save_exception(tenant_id, exception)
        self._audit(
            tenant_id,
            actor=actor,
            action="exception.revoked",
            object_id=exception.exception_id,
            metadata={"reason": reason},
        )
        return ServiceResponse.success(exception=exception.to_dict())

    def list_exceptions(self, principal: Any, tenant_id: str, status: str = "") -> ServiceResponse:
        try:
            authorize(principal, "exception:read", tenant_id)
        except AuthorizationError as exc:
            return ServiceResponse.failure(str(exc))

        items = self.store.list_exceptions(tenant_id)
        if status:
            try:
                wanted = ExceptionStatus(status)
            except ValueError:
                return ServiceResponse.failure(f"unknown exception status {status!r}")
            items = [e for e in items if e.status is wanted]
        return ServiceResponse.success(exceptions=[e.to_dict() for e in items])

    def _find_exception(self, tenant_id: str, exception_id: str) -> RiskException | None:
        getter = getattr(self.store, "get_exception", None)
        if callable(getter):
            return getter(tenant_id, exception_id)
        for item in self.store.list_exceptions(tenant_id):
            if item.exception_id == exception_id:
                return item
        return None

    # ---------------------------------------------------------------------- audit

    def get_audit_trail(self, principal: Any, tenant_id: str, limit: int = 200) -> ServiceResponse:
        try:
            authorize(principal, "audit:read", tenant_id)
        except AuthorizationError as exc:
            return ServiceResponse.failure(str(exc))
        return ServiceResponse.success(events=self.store.list_audit(tenant_id, limit))

    def _audit(
        self,
        tenant_id: str,
        actor: str,
        action: str,
        object_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append one service-level event, chained onto what is already stored."""
        log = AuditLog(tenant_id=tenant_id)
        existing = self.store.list_audit(tenant_id, limit=1)
        if existing:
            # Continue the stored chain rather than starting a new one, so the
            # trail verifies end to end across separate service calls.
            log.events.append(_stub_from(existing[-1]))
        event = log.record(
            actor=actor,
            action=action,
            object_type="risk_exception",
            object_id=object_id,
            metadata=metadata or {},
        )
        self.store.append_audit(tenant_id, [event.to_dict()])


def _stub_from(record: dict[str, Any]) -> Any:
    """Rebuild just enough of a stored event to chain the next one onto it."""
    from ironclad.model.audit import AuditEvent  # noqa: PLC0415 — avoids a cycle

    return AuditEvent(
        event_id=str(record.get("event_id", "")),
        tenant_id=str(record.get("tenant_id", "")),
        actor=str(record.get("actor", "")),
        action=str(record.get("action", "")),
        object_type=str(record.get("object_type", "")),
        object_id=str(record.get("object_id", "")),
        at=datetime.fromisoformat(str(record["at"])),
        metadata=dict(record.get("metadata", {})),
        prev_hash=str(record.get("prev_hash", "")),
        hash=str(record.get("hash", "")),
    )
