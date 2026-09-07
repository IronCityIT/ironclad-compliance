"""The service surface: authorization on every call, and the workflows it owns."""

from __future__ import annotations

import pytest

from ironclad.api.schemas import (
    AssessmentRequest,
    ExceptionRequest,
    validate_assessment_request,
    validate_exception_request,
)
from ironclad.api.service import ComplianceService, InMemoryStore
from ironclad.model.exception import ExceptionStatus
from ironclad.model.tenant import Principal, Role
from tests.conftest import NOW


def principal(*roles: Role, tenant: str = "acme", user: str = "u1") -> Principal:
    return Principal(user_id=user, tenant_id=tenant, roles=frozenset(roles))


@pytest.fixture
def service() -> ComplianceService:
    return ComplianceService(store=InMemoryStore())


class TestRequestValidation:
    def test_the_standard_workflow_input_names_are_accepted(self) -> None:
        # client_id and client_name are what the ICIT workflow inputs are called.
        request = AssessmentRequest.from_dict({"client_id": "Acme Corp", "framework": "soc2"})
        assert request.tenant_id == "acme-corp"

    def test_an_unknown_framework_is_refused(self) -> None:
        request = AssessmentRequest.from_dict({"client_id": "acme", "framework": "iso-27001"})
        assert any("not one of" in e for e in validate_assessment_request(request))

    def test_modules_and_group_are_mutually_exclusive(self) -> None:
        request = AssessmentRequest.from_dict(
            {
                "client_id": "acme",
                "framework": "soc2",
                "modules": "control_mapping",
                "group": "deep",
            }
        )
        assert any("not both" in e for e in validate_assessment_request(request))

    def test_a_comma_separated_module_list_is_parsed(self) -> None:
        request = AssessmentRequest.from_dict(
            {"client_id": "acme", "framework": "soc2", "modules": "a, b ,c"}
        )
        assert request.modules == ["a", "b", "c"]

    def test_an_acceptance_without_a_reason_is_refused(self) -> None:
        request = ExceptionRequest.from_dict(
            {"tenant_id": "acme", "control_id": "CC6.1", "requested_by": "alice"}
        )
        assert any("just a gap" in e for e in validate_exception_request(request))


class TestAssessmentCalls:
    def test_a_compliance_manager_can_run_an_assessment(
        self, service: ComplianceService, tiny_framework, evidence, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "ironclad.api.service.run_assessment",
            lambda **kwargs: _fake_run(tiny_framework, kwargs),
        )
        response = service.run_assessment(
            principal(Role.COMPLIANCE_MANAGER),
            AssessmentRequest(tenant_id="acme", framework="soc2"),
            evidence,
        )
        assert response.ok

    def test_a_viewer_cannot_run_an_assessment(self, service: ComplianceService, evidence) -> None:
        response = service.run_assessment(
            principal(Role.VIEWER),
            AssessmentRequest(tenant_id="acme", framework="soc2"),
            evidence,
        )
        assert not response.ok
        assert any("lacks" in e for e in response.errors)

    def test_a_caller_cannot_run_an_assessment_for_another_tenant(
        self, service: ComplianceService, evidence
    ) -> None:
        response = service.run_assessment(
            principal(Role.OWNER, tenant="acme"),
            AssessmentRequest(tenant_id="other-co", framework="soc2"),
            evidence,
        )
        assert not response.ok
        assert any("another tenant" in e for e in response.errors)

    def test_a_caller_cannot_read_another_tenants_assessment(
        self, service: ComplianceService
    ) -> None:
        service.store.save_assessment("other-co", {"assessment_id": "a1", "summary": {}})
        response = service.get_assessment(principal(Role.OWNER, tenant="acme"), "other-co", "a1")
        assert not response.ok

    def test_a_missing_assessment_is_reported_not_invented(
        self, service: ComplianceService
    ) -> None:
        response = service.get_assessment(principal(Role.VIEWER), "acme", "nope")
        assert not response.ok
        assert any("no assessment" in e for e in response.errors)


class TestExceptionCalls:
    def _request(self) -> ExceptionRequest:
        return ExceptionRequest(
            tenant_id="acme",
            control_id="CC6.1",
            justification="Remediation is scheduled for the next release train.",
            requested_by="alice",
            compensating_controls=["Daily privileged activity review"],
        )

    def test_a_contributor_can_raise_an_acceptance(self, service: ComplianceService) -> None:
        response = service.request_exception(
            principal(Role.CONTRIBUTOR, user="alice"), self._request()
        )
        assert response.ok
        assert response.data["exception"]["status"] == ExceptionStatus.PENDING_APPROVAL.value

    def test_a_viewer_cannot_raise_an_acceptance(self, service: ComplianceService) -> None:
        response = service.request_exception(principal(Role.VIEWER), self._request())
        assert not response.ok

    def test_a_contributor_cannot_approve_one(self, service: ComplianceService) -> None:
        raised = service.request_exception(
            principal(Role.CONTRIBUTOR, user="alice"), self._request()
        )
        exception_id = raised.data["exception"]["exception_id"]
        response = service.approve_exception(
            principal(Role.CONTRIBUTOR, user="bob"), "acme", exception_id
        )
        assert not response.ok
        assert any("lacks" in e for e in response.errors)

    def test_the_requester_cannot_approve_their_own(self, service: ComplianceService) -> None:
        # The separation-of-duties rule lives in the model, so it holds even for
        # a caller who does hold the approval permission.
        raised = service.request_exception(
            principal(Role.COMPLIANCE_MANAGER, user="alice"), self._request()
        )
        exception_id = raised.data["exception"]["exception_id"]
        response = service.approve_exception(
            principal(Role.COMPLIANCE_MANAGER, user="alice"), "acme", exception_id
        )
        assert not response.ok
        assert any("second person" in e for e in response.errors)

    def test_a_second_manager_can_approve(self, service: ComplianceService) -> None:
        raised = service.request_exception(
            principal(Role.CONTRIBUTOR, user="alice"), self._request()
        )
        exception_id = raised.data["exception"]["exception_id"]
        response = service.approve_exception(
            principal(Role.COMPLIANCE_MANAGER, user="bob"), "acme", exception_id
        )
        assert response.ok
        assert response.data["exception"]["approved_by"] == "bob"
        assert response.data["exception"]["active"] is True

    def test_an_auditor_cannot_approve(self, service: ComplianceService) -> None:
        raised = service.request_exception(
            principal(Role.CONTRIBUTOR, user="alice"), self._request()
        )
        response = service.approve_exception(
            principal(Role.AUDITOR, user="ext"), "acme", raised.data["exception"]["exception_id"]
        )
        assert not response.ok

    def test_approving_an_unknown_acceptance_is_reported(self, service: ComplianceService) -> None:
        response = service.approve_exception(principal(Role.OWNER), "acme", "ex-nope")
        assert not response.ok

    def test_an_acceptance_can_be_revoked(self, service: ComplianceService) -> None:
        raised = service.request_exception(
            principal(Role.CONTRIBUTOR, user="alice"), self._request()
        )
        exception_id = raised.data["exception"]["exception_id"]
        service.approve_exception(principal(Role.OWNER, user="bob"), "acme", exception_id)
        response = service.revoke_exception(
            principal(Role.OWNER, user="bob"), "acme", exception_id, "control was remediated"
        )
        assert response.ok
        assert response.data["exception"]["status"] == ExceptionStatus.REVOKED.value

    def test_acceptances_can_be_filtered_by_status(self, service: ComplianceService) -> None:
        service.request_exception(principal(Role.CONTRIBUTOR, user="alice"), self._request())
        response = service.list_exceptions(
            principal(Role.CONTRIBUTOR), "acme", status="pending_approval"
        )
        assert response.ok
        assert len(response.data["exceptions"]) == 1

    def test_an_unknown_status_filter_is_refused(self, service: ComplianceService) -> None:
        response = service.list_exceptions(principal(Role.CONTRIBUTOR), "acme", status="maybe")
        assert not response.ok


class TestAuditAccess:
    def test_service_actions_are_recorded_in_a_verifiable_chain(
        self, service: ComplianceService
    ) -> None:
        from datetime import datetime

        from ironclad.model.audit import AuditEvent, AuditLog

        request = ExceptionRequest(
            tenant_id="acme",
            control_id="CC6.1",
            justification="Scheduled for the next release.",
            requested_by="alice",
        )
        raised = service.request_exception(principal(Role.CONTRIBUTOR, user="alice"), request)
        service.approve_exception(
            principal(Role.COMPLIANCE_MANAGER, user="bob"),
            "acme",
            raised.data["exception"]["exception_id"],
        )

        response = service.get_audit_trail(principal(Role.AUDITOR), "acme")
        assert response.ok
        events = response.data["events"]
        assert [e["action"] for e in events] == ["exception.requested", "exception.approved"]

        # The stored events chain: the second follows the first.
        log = AuditLog(tenant_id="acme")
        for record in events:
            log.events.append(
                AuditEvent(
                    event_id=record["event_id"],
                    tenant_id=record["tenant_id"],
                    actor=record["actor"],
                    action=record["action"],
                    object_type=record["object_type"],
                    object_id=record["object_id"],
                    at=datetime.fromisoformat(record["at"]),
                    metadata=record["metadata"],
                    prev_hash=record["prev_hash"],
                    hash=record["hash"],
                )
            )
        assert log.is_valid()

    def test_a_viewer_cannot_read_the_audit_trail(self, service: ComplianceService) -> None:
        response = service.get_audit_trail(principal(Role.VIEWER), "acme")
        assert not response.ok


def _fake_run(framework, kwargs):
    """A minimal RunResult, so the service test does not re-test the engine."""
    from ironclad.engine import RunResult
    from ironclad.model.assessment import Assessment
    from ironclad.model.audit import AuditLog
    from ironclad.model.remediation import RemediationPlan

    assessment = Assessment(
        assessment_id="a-1", tenant_id=kwargs["tenant_id"], framework=framework, started_at=NOW
    )
    assessment.recompute_summary()
    return RunResult(
        assessment=assessment,
        plan=RemediationPlan(tenant_id=kwargs["tenant_id"], assessment_id="a-1"),
        audit=AuditLog(tenant_id=kwargs["tenant_id"]),
    )
