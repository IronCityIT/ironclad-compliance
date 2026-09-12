"""The service surface: authorization on every call, and the workflows it owns."""

from __future__ import annotations

import json
from pathlib import Path

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
        service.store.put_assessment(
            {"tenant_id": "other-co", "assessment_id": "a1", "summary": {}}
        )
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


class TestTheServiceWritesToARealStore:
    """The point of splitting the collaborators.

    `ComplianceService` used to declare one `Store` protocol that no shipped
    implementation satisfied. Handed a policy file it raised from inside a
    persist; handed nothing it forgot everything when the process ended. It can
    now be given a policy store and a result store, which is what an HTTP
    surface would need and what the CLI already has half of.
    """

    @staticmethod
    def _policy(tmp_path) -> Path:
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "policy_version": "1.0",
                    "tenant_id": "acme",
                    "scope_exclusions": [],
                    "exceptions": [],
                    "owners": {},
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_an_assessment_lands_on_a_volume(self, tmp_path, evidence) -> None:
        from ironclad.api.policy_store import PolicyStore
        from ironclad.store import FileResultStore

        service = ComplianceService(
            store=PolicyStore(self._policy(tmp_path)),
            results=FileResultStore(tmp_path / "volume"),
        )
        response = service.run_assessment(
            principal(Role.COMPLIANCE_MANAGER),
            AssessmentRequest(tenant_id="acme", framework="soc2", group="quick"),
            evidence=evidence,
        )
        assert response.ok, response.errors

        assessment_id = response.data["assessment_id"]
        stored = service.get_assessment(principal(Role.OWNER), "acme", assessment_id)
        assert stored.ok, stored.errors
        assert stored.data["assessment"]["assessment_id"] == assessment_id

    def test_the_trail_is_written_once_not_twice(self, evidence) -> None:
        # Every result store writes the audit events as part of the document.
        # Appending them separately, as the old two-protocol path did, would
        # double the trail on a volume and on a database.
        service = ComplianceService()
        response = service.run_assessment(
            principal(Role.COMPLIANCE_MANAGER),
            AssessmentRequest(tenant_id="acme", framework="soc2", group="quick"),
            evidence=evidence,
        )
        assert response.ok, response.errors
        events = service.store.list_audit("acme")
        assert len({e["event_id"] for e in events}) == len(events)

    def test_a_service_without_a_result_store_says_so(self, tmp_path) -> None:
        from ironclad.api.policy_store import PolicyStore

        service = ComplianceService(store=PolicyStore(self._policy(tmp_path)))
        assert service.results is None
        for response in (
            service.list_assessments(principal(Role.OWNER), "acme"),
            service.get_assessment(principal(Role.OWNER), "acme", "a1"),
        ):
            assert not response.ok
            assert any("no result store" in e for e in response.errors)

    def test_one_object_may_still_do_both(self) -> None:
        # InMemoryStore does, so the common case stays a single argument.
        service = ComplianceService()
        assert service.results is service.store


class TestEveryCallIsAuthorized:
    """The permission surface, refusal by refusal.

    `ComplianceService` exists so that no surface — the CLI, a future HTTP
    endpoint — can act on a tenant without the permission for it. Most of those
    refusal branches were the uncovered half of this module: the paths that run
    when somebody is told no.

    A refusal that silently succeeds is a viewer revoking a risk acceptance, so
    each is asserted to return a failure naming the permission rather than
    raising, which is what a caller can turn into a 403.
    """

    def _service_with_an_acceptance(self):
        service = ComplianceService()
        raised = service.request_exception(
            principal(Role.CONTRIBUTOR),
            ExceptionRequest(
                tenant_id="acme",
                control_id="CC1.1",
                justification="Remediation is scheduled for the next release train.",
                requested_by="alice",
            ),
        )
        assert raised.ok, raised.errors
        return service, raised.data["exception"]["exception_id"]

    def test_a_viewer_cannot_run_an_assessment(self, evidence) -> None:
        response = ComplianceService().run_assessment(
            principal(Role.VIEWER),
            AssessmentRequest(tenant_id="acme", framework="soc2", group="quick"),
            evidence=evidence,
        )
        assert not response.ok
        assert any("assessment:run" in e for e in response.errors)

    def test_an_auditor_cannot_run_one_either(self, evidence) -> None:
        # An auditor sees everything and changes nothing.
        response = ComplianceService().run_assessment(
            principal(Role.AUDITOR),
            AssessmentRequest(tenant_id="acme", framework="soc2", group="quick"),
            evidence=evidence,
        )
        assert not response.ok

    def test_an_invalid_request_is_refused_before_authorization(self, evidence) -> None:
        # Both would refuse it; the validation message is the more useful one.
        response = ComplianceService().run_assessment(
            principal(Role.OWNER),
            AssessmentRequest(tenant_id="", framework="", group="quick"),
            evidence=evidence,
        )
        assert not response.ok
        assert any("tenant_id" in e for e in response.errors)

    def test_an_unknown_framework_is_refused_by_validation(self, evidence) -> None:
        response = ComplianceService().run_assessment(
            principal(Role.OWNER),
            AssessmentRequest(tenant_id="acme", framework="iso-27001", group="quick"),
            evidence=evidence,
        )
        assert not response.ok
        assert any("iso-27001" in e for e in response.errors)

    def test_an_engine_failure_is_reported_not_raised(self, evidence) -> None:
        # The engine refuses to assess one tenant's evidence into another's
        # record. That fault has to come back as a failure a caller can render,
        # not as a traceback out of the service.
        response = ComplianceService().run_assessment(
            Principal(user_id="u1", tenant_id="beta", roles=frozenset({Role.OWNER})),
            AssessmentRequest(tenant_id="beta", framework="soc2", group="quick"),
            evidence=evidence,  # belongs to acme
        )
        assert not response.ok
        assert any("evidence set belongs to" in e for e in response.errors)

    def test_an_invalid_acceptance_request_is_refused(self) -> None:
        response = ComplianceService().request_exception(
            principal(Role.CONTRIBUTOR),
            ExceptionRequest(tenant_id="acme", control_id="", justification="  ", requested_by=""),
        )
        assert not response.ok
        assert len(response.errors) >= 2

    def test_a_service_with_no_result_store_refuses_to_run_one(self, tmp_path, evidence) -> None:
        from ironclad.api.policy_store import PolicyStore

        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps({"policy_version": "1.0", "tenant_id": "acme"}), "utf-8")
        response = ComplianceService(store=PolicyStore(policy)).run_assessment(
            principal(Role.OWNER),
            AssessmentRequest(tenant_id="acme", framework="soc2", group="quick"),
            evidence=evidence,
        )
        assert not response.ok
        assert any("no result store" in e for e in response.errors)

    def test_a_tenant_reads_its_own_assessments(self) -> None:
        # The success path, which nothing reached: every other test of
        # list_assessments asserted a refusal, so "returns the assessments" was
        # the one thing about it never checked.
        store = InMemoryStore()
        store.put_assessment(
            {"tenant_id": "acme", "assessment_id": "acme-1", "started_at": "2026-01-01"}
        )
        service = ComplianceService(store=store)
        response = service.list_assessments(principal(Role.AUDITOR), "acme")
        assert response.ok, response.errors
        assert [a["assessment_id"] for a in response.data["assessments"]] == ["acme-1"]

    def test_a_stranger_cannot_read_a_tenant_s_assessments(self) -> None:
        response = ComplianceService().list_assessments(
            Principal(user_id="mallory", tenant_id="beta", roles=frozenset({Role.OWNER})),
            "acme",
        )
        assert not response.ok

    def test_a_viewer_cannot_read_the_exception_register(self) -> None:
        # A viewer sees the readiness position, not who accepted which risk.
        response = ComplianceService().list_exceptions(principal(Role.VIEWER), "acme")
        assert not response.ok
        assert any("exception:read" in e for e in response.errors)

    def test_a_viewer_cannot_request_an_acceptance(self) -> None:
        response = ComplianceService().request_exception(
            principal(Role.VIEWER),
            ExceptionRequest(
                tenant_id="acme",
                control_id="CC1.1",
                justification="A long enough justification to pass validation.",
                requested_by="v",
            ),
        )
        assert not response.ok

    def test_a_contributor_cannot_revoke(self) -> None:
        service, exception_id = self._service_with_an_acceptance()
        response = service.revoke_exception(
            principal(Role.CONTRIBUTOR), "acme", exception_id, "no longer needed"
        )
        assert not response.ok
        assert any("exception:approve" in e for e in response.errors)

    def test_revoking_something_that_is_not_there_says_so(self) -> None:
        response = ComplianceService().revoke_exception(
            principal(Role.OWNER), "acme", "ex-nothing", "reason"
        )
        assert not response.ok
        assert any("no risk acceptance" in e for e in response.errors)

    def test_revoking_twice_is_refused_by_the_workflow(self) -> None:
        # The state machine, not the service, decides this — and the service
        # reports it rather than letting it raise.
        service, exception_id = self._service_with_an_acceptance()
        first = service.revoke_exception(
            principal(Role.OWNER, user="bob"), "acme", exception_id, "withdrawn"
        )
        assert first.ok, first.errors
        second = service.revoke_exception(
            principal(Role.OWNER, user="bob"), "acme", exception_id, "again"
        )
        assert not second.ok

    def test_an_unknown_exception_status_filter_is_named(self) -> None:
        response = ComplianceService().list_exceptions(
            principal(Role.AUDITOR), "acme", status="half-approved"
        )
        assert not response.ok
        assert any("unknown exception status" in e for e in response.errors)

    def test_a_known_status_filters(self) -> None:
        service, _ = self._service_with_an_acceptance()
        pending = service.list_exceptions(
            principal(Role.AUDITOR), "acme", status="pending_approval"
        )
        assert pending.ok, pending.errors
        assert len(pending.data["exceptions"]) == 1
        assert (
            service.list_exceptions(principal(Role.AUDITOR), "acme", status="approved").data[
                "exceptions"
            ]
            == []
        )


class TestFindingAnExceptionWithoutAGetter:
    """A store need not offer `get_exception`.

    `ResultStore` and `PolicyRecords` both describe listing; a single-item getter
    is an optimisation a store may or may not have. The service falls back to a
    scan, and that fallback had never run — so a store without the getter would
    have failed to find anything to approve or revoke.
    """

    class ListOnlyStore:
        """A policy store with no `get_exception`."""

        def __init__(self) -> None:
            self._exceptions: list = []
            self._audit: list = []

        def save_exception(self, tenant_id: str, exception) -> None:
            self._exceptions = [
                e for e in self._exceptions if e.exception_id != exception.exception_id
            ]
            self._exceptions.append(exception)

        def list_exceptions(self, tenant_id: str) -> list:
            return list(self._exceptions)

        def append_audit(self, tenant_id: str, events: list) -> None:
            self._audit.extend(events)

        def list_audit(self, tenant_id: str, limit: int = 200) -> list:
            return self._audit[-limit:]

    def test_an_acceptance_is_found_by_scanning(self) -> None:
        service = ComplianceService(store=self.ListOnlyStore())
        raised = service.request_exception(
            principal(Role.CONTRIBUTOR),
            ExceptionRequest(
                tenant_id="acme",
                control_id="CC1.1",
                justification="Remediation is scheduled for the next release train.",
                requested_by="alice",
            ),
        )
        assert raised.ok, raised.errors
        approved = service.approve_exception(
            principal(Role.OWNER, user="bob"), "acme", raised.data["exception"]["exception_id"]
        )
        assert approved.ok, approved.errors
        assert approved.data["exception"]["status"] == "approved"

    def test_an_unknown_id_still_reports_cleanly(self) -> None:
        service = ComplianceService(store=self.ListOnlyStore())
        response = service.approve_exception(principal(Role.OWNER), "acme", "ex-nothing")
        assert not response.ok


class TestTheReferenceStore:
    """InMemoryStore is what the service uses when given nothing, and what the
    tests above run against. Its own behaviour was mostly uncovered."""

    def test_assessments_come_back_most_recent_first(self) -> None:
        store = InMemoryStore()
        for stamp, name in (("2026-01-01", "a"), ("2026-06-01", "b"), ("2026-03-01", "c")):
            store.put_assessment({"tenant_id": "acme", "assessment_id": name, "started_at": stamp})
        assert [a["assessment_id"] for a in store.list_assessments("acme")] == ["b", "c", "a"]

    def test_the_limit_is_honoured(self) -> None:
        store = InMemoryStore()
        for n in range(5):
            store.put_assessment(
                {"tenant_id": "acme", "assessment_id": str(n), "started_at": f"2026-0{n + 1}-01"}
            )
        assert len(store.list_assessments("acme", limit=2)) == 2

    def test_the_queue_is_the_latest_assessment_s(self) -> None:
        store = InMemoryStore()
        store.put_assessment(
            {
                "tenant_id": "acme",
                "assessment_id": "old",
                "started_at": "2026-01-01",
                "remediation": {"items": [{"item_id": "rm-1"}, {"item_id": "rm-2"}]},
            }
        )
        store.put_assessment(
            {
                "tenant_id": "acme",
                "assessment_id": "new",
                "started_at": "2026-06-01",
                "remediation": {"items": [{"item_id": "rm-1"}]},
            }
        )
        assert [i["item_id"] for i in store.list_remediation("acme")] == ["rm-1"]

    def test_an_unknown_tenant_reads_empty(self) -> None:
        store = InMemoryStore()
        assert store.list_assessments("nobody") == []
        assert store.list_remediation("nobody") == []

    def test_it_says_plainly_that_it_forgets(self) -> None:
        # A store that claims to be writable and loses everything at exit should
        # say the second part.
        health = InMemoryStore().health()
        assert health["writable"] is True
        assert "survives" in health["detail"]
