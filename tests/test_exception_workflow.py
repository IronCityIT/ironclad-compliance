"""The risk-acceptance workflow, reachable.

`ComplianceService` implemented the whole workflow — request, approve with
separation of duties, revoke, every step audited — against a `Store` whose only
implementation forgot everything when the process ended. So the workflow was
reachable from tests and from nowhere else, and the one way an acceptance could
reach a real assessment was somebody hand-editing `policy.json`.

`PolicyStore` writes to that same policy file, which is what the next assessment
reads. The rules under test are the ones that keep the loop honest: the file is
the record, the trail is chained and separate, and nothing the workflow refuses
can be smuggled in by writing the file directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironclad.api.policy_store import PolicyStore
from ironclad.api.schemas import ExceptionRequest
from ironclad.api.service import ComplianceService
from ironclad.cli import main
from ironclad.errors import IroncladError
from ironclad.model.exception import ExceptionStatus
from ironclad.model.tenant import Principal, Role

TENANT = "acme-corp"
JUSTIFICATION = "Board-level training is scheduled next quarter; interim guidance issued."


def principal(*roles: Role, user: str = "alice") -> Principal:
    return Principal(user_id=user, tenant_id=TENANT, roles=frozenset(roles))


@pytest.fixture
def policy_path(tmp_path: Path) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "policy_version": "1.0",
                "tenant_id": TENANT,
                "scope_exclusions": [],
                "exceptions": [],
                "owners": {},
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def service(policy_path: Path) -> ComplianceService:
    return ComplianceService(store=PolicyStore(policy_path))


def request_for(control_id: str = "CC1.2", **overrides) -> ExceptionRequest:
    fields = {
        "tenant_id": TENANT,
        "control_id": control_id,
        "justification": JUSTIFICATION,
        "requested_by": "alice",
        "compensating_controls": ["Quarterly manager attestation"],
        "expires_in_days": 90,
    }
    fields.update(overrides)
    return ExceptionRequest(**fields)  # type: ignore[arg-type]


def document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestTheFileIsTheRecord:
    def test_a_request_lands_in_the_policy_file(self, service, policy_path: Path) -> None:
        response = service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        assert response.ok, response.errors
        stored = document(policy_path)["exceptions"]
        assert len(stored) == 1
        assert stored[0]["control_id"] == "CC1.2"
        assert stored[0]["status"] == "pending_approval"

    def test_an_approval_updates_the_same_entry(self, service, policy_path: Path) -> None:
        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        exception_id = document(policy_path)["exceptions"][0]["exception_id"]
        response = service.approve_exception(
            principal(Role.COMPLIANCE_MANAGER, user="bob"), TENANT, exception_id
        )
        assert response.ok, response.errors
        stored = document(policy_path)["exceptions"]
        assert len(stored) == 1, "the approval created a second entry"
        assert stored[0]["status"] == "approved"
        assert stored[0]["approved_by"] == "bob"

    def test_a_second_process_sees_the_first_one_s_work(self, policy_path: Path) -> None:
        # The file is the record, not a cache: every call re-reads it.
        first = ComplianceService(store=PolicyStore(policy_path))
        first.request_exception(principal(Role.CONTRIBUTOR), request_for())

        second = ComplianceService(store=PolicyStore(policy_path))
        found = second.list_exceptions(principal(Role.AUDITOR), TENANT)
        assert found.ok, found.errors
        assert len(found.data["exceptions"]) == 1

    def test_no_derived_field_is_written_to_the_file(self, service, policy_path: Path) -> None:
        # `active` and `days_remaining` are computed at read time and would be
        # wrong the moment they were written down.
        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        entry = document(policy_path)["exceptions"][0]
        assert "active" not in entry
        assert "days_remaining" not in entry

    def test_the_written_policy_still_loads(self, service, policy_path: Path) -> None:
        from ironclad.policy import load_policy

        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        exception_id = document(policy_path)["exceptions"][0]["exception_id"]
        service.approve_exception(
            principal(Role.COMPLIANCE_MANAGER, user="bob"), TENANT, exception_id
        )
        policy = load_policy(policy_path, expected_tenant=TENANT)
        assert len(policy.exceptions) == 1
        assert policy.exceptions[0].status is ExceptionStatus.APPROVED

    def test_a_store_refuses_another_tenant_s_file(self, policy_path: Path) -> None:
        # Fail closed, and loudly: a store pointed at the wrong tenant's policy
        # is a misconfiguration, and writing anyway would put one client's risk
        # acceptance in another client's file.
        service = ComplianceService(store=PolicyStore(policy_path))
        with pytest.raises(IroncladError, match="belongs to tenant"):
            service.request_exception(
                Principal(user_id="mallory", tenant_id="beta", roles=frozenset({Role.OWNER})),
                request_for(tenant_id="beta"),
            )
        assert document(policy_path)["exceptions"] == []

    def test_the_store_refuses_to_write_a_policy_that_would_not_load(
        self, policy_path: Path
    ) -> None:
        # One bad write must not leave a policy the next assessment cannot read.
        store = PolicyStore(policy_path)
        broken = document(policy_path)
        broken["policy_version"] = "99.0"
        policy_path.write_text(json.dumps(broken), encoding="utf-8")
        service = ComplianceService(store=store)
        with pytest.raises(IroncladError, match="would not load"):
            service.request_exception(principal(Role.CONTRIBUTOR), request_for())


class TestTheRulesHoldOnThisSurfaceToo:
    def test_the_requester_cannot_approve_their_own(self, service, policy_path: Path) -> None:
        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        exception_id = document(policy_path)["exceptions"][0]["exception_id"]
        response = service.approve_exception(
            principal(Role.COMPLIANCE_MANAGER, user="alice"), TENANT, exception_id
        )
        assert not response.ok
        assert any("may not approve" in e for e in response.errors)
        assert document(policy_path)["exceptions"][0]["status"] == "pending_approval"

    def test_a_viewer_cannot_approve(self, service, policy_path: Path) -> None:
        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        exception_id = document(policy_path)["exceptions"][0]["exception_id"]
        response = service.approve_exception(
            principal(Role.VIEWER, user="bob"), TENANT, exception_id
        )
        assert not response.ok
        assert any("exception:approve" in e for e in response.errors)

    def test_a_request_without_a_justification_is_refused(self, service, policy_path: Path) -> None:
        response = service.request_exception(
            principal(Role.CONTRIBUTOR), request_for(justification="   ")
        )
        assert not response.ok
        assert document(policy_path)["exceptions"] == []

    def test_a_revocation_is_recorded(self, service, policy_path: Path) -> None:
        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        exception_id = document(policy_path)["exceptions"][0]["exception_id"]
        service.approve_exception(
            principal(Role.COMPLIANCE_MANAGER, user="bob"), TENANT, exception_id
        )
        response = service.revoke_exception(
            principal(Role.COMPLIANCE_MANAGER, user="bob"), TENANT, exception_id, "Control now met."
        )
        assert response.ok, response.errors
        assert document(policy_path)["exceptions"][0]["status"] == "revoked"


class TestTheTrailIsChainedAndSeparate:
    def test_the_trail_lives_beside_the_policy_not_inside_it(
        self, service, policy_path: Path
    ) -> None:
        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        audit_path = policy_path.with_name(policy_path.name + ".audit.json")
        assert audit_path.exists()
        assert "events" not in document(policy_path)

    def test_every_step_is_recorded_with_its_actor(self, service, policy_path: Path) -> None:
        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        exception_id = document(policy_path)["exceptions"][0]["exception_id"]
        service.approve_exception(
            principal(Role.COMPLIANCE_MANAGER, user="bob"), TENANT, exception_id
        )
        service.revoke_exception(
            principal(Role.COMPLIANCE_MANAGER, user="bob"), TENANT, exception_id, "Control now met."
        )
        trail = json.loads(
            policy_path.with_name(policy_path.name + ".audit.json").read_text(encoding="utf-8")
        )
        assert [(e["actor"], e["action"]) for e in trail["events"]] == [
            ("alice", "exception.requested"),
            ("bob", "exception.approved"),
            ("bob", "exception.revoked"),
        ]

    def test_the_chain_links_across_separate_calls(self, service, policy_path: Path) -> None:
        # Each call is its own process in real use. The chain has to continue
        # from what is on disk, or the trail verifies only within one run.
        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        exception_id = document(policy_path)["exceptions"][0]["exception_id"]
        service.approve_exception(
            principal(Role.COMPLIANCE_MANAGER, user="bob"), TENANT, exception_id
        )
        trail = json.loads(
            policy_path.with_name(policy_path.name + ".audit.json").read_text(encoding="utf-8")
        )
        events = trail["events"]
        assert events[1]["prev_hash"] == events[0]["hash"]
        assert trail["head"] == events[-1]["hash"]

    def test_a_refused_action_writes_nothing(self, service, policy_path: Path) -> None:
        service.request_exception(principal(Role.CONTRIBUTOR), request_for())
        before = policy_path.with_name(policy_path.name + ".audit.json").read_text(encoding="utf-8")
        exception_id = document(policy_path)["exceptions"][0]["exception_id"]
        service.approve_exception(principal(Role.VIEWER, user="bob"), TENANT, exception_id)
        after = policy_path.with_name(policy_path.name + ".audit.json").read_text(encoding="utf-8")
        assert before == after


class TestTheStoreKnowsWhatItIsNot:
    def test_it_does_not_claim_to_hold_assessments(self, policy_path: Path) -> None:
        # A policy file is where a client's determinations belong and is
        # emphatically not where a hundred-kilobyte result document belongs.
        store = PolicyStore(policy_path)
        assert not hasattr(store, "put_assessment")

    def test_a_service_with_only_a_policy_store_says_so_plainly(self, service) -> None:
        # It used to raise from three frames down inside a persist. The message
        # names the fix rather than the symptom.
        response = service.list_assessments(principal(Role.OWNER), TENANT)
        assert not response.ok
        assert any("no result store" in e for e in response.errors)

    def test_the_exception_workflow_still_works_without_one(
        self, service, policy_path: Path
    ) -> None:
        # The two halves are independent: a policy store is all the risk
        # acceptance workflow has ever needed.
        assert service.request_exception(principal(Role.CONTRIBUTOR), request_for()).ok
        assert document(policy_path)["exceptions"]

    def test_a_missing_policy_file_reads_as_empty_rather_than_failing(self, tmp_path: Path) -> None:
        store = PolicyStore(tmp_path / "absent.json")
        assert store.list_exceptions(TENANT) == []
        assert store.tenant_id() == ""


class TestTheCommandLine:
    def _policy(self, tmp_path: Path) -> Path:
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "policy_version": "1.0",
                    "tenant_id": TENANT,
                    "scope_exclusions": [],
                    "exceptions": [],
                    "owners": {},
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_request_then_approve_leaves_an_active_acceptance(self, tmp_path: Path) -> None:
        path = self._policy(tmp_path)
        assert (
            main(
                [
                    "exception",
                    "request",
                    "--policy",
                    str(path),
                    "--actor",
                    "alice",
                    "--role",
                    "contributor",
                    "--control",
                    "CC1.2",
                    "--justification",
                    JUSTIFICATION,
                ]
            )
            == 0
        )
        exception_id = document(path)["exceptions"][0]["exception_id"]
        assert (
            main(
                [
                    "exception",
                    "approve",
                    "--policy",
                    str(path),
                    "--actor",
                    "bob",
                    "--role",
                    "compliance_manager",
                    "--id",
                    exception_id,
                ]
            )
            == 0
        )
        assert document(path)["exceptions"][0]["status"] == "approved"

    def test_a_self_approval_exits_non_zero(self, tmp_path: Path, capsys) -> None:
        path = self._policy(tmp_path)
        main(
            [
                "exception",
                "request",
                "--policy",
                str(path),
                "--actor",
                "alice",
                "--role",
                "contributor",
                "--control",
                "CC1.2",
                "--justification",
                JUSTIFICATION,
            ]
        )
        capsys.readouterr()
        exception_id = document(path)["exceptions"][0]["exception_id"]
        code = main(
            [
                "exception",
                "approve",
                "--policy",
                str(path),
                "--actor",
                "alice",
                "--role",
                "compliance_manager",
                "--id",
                exception_id,
            ]
        )
        assert code == 2
        assert "may not approve" in capsys.readouterr().err

    def test_a_policy_without_a_tenant_is_refused(self, tmp_path: Path, capsys) -> None:
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({"policy_version": "1.0", "exceptions": []}), encoding="utf-8")
        code = main(
            [
                "exception",
                "list",
                "--policy",
                str(path),
                "--actor",
                "alice",
                "--role",
                "viewer",
            ]
        )
        assert code == 2
        assert "names no tenant_id" in capsys.readouterr().err

    def test_list_reports_what_is_on_file(self, tmp_path: Path, capsys) -> None:
        path = self._policy(tmp_path)
        main(
            [
                "exception",
                "request",
                "--policy",
                str(path),
                "--actor",
                "alice",
                "--role",
                "contributor",
                "--control",
                "CC1.2",
                "--justification",
                JUSTIFICATION,
            ]
        )
        capsys.readouterr()
        assert (
            main(
                [
                    "exception",
                    "list",
                    "--policy",
                    str(path),
                    "--actor",
                    "carol",
                    "--role",
                    "auditor",
                ]
            )
            == 0
        )
        listed = json.loads(capsys.readouterr().out)["exceptions"]
        assert [e["control_id"] for e in listed] == ["CC1.2"]
