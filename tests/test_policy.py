"""Tenant policy: scoping, acceptance and ownership reaching the pipeline.

Before this existed, `ironclad assess` had no way to load a risk acceptance and
no way to scope a control out — so `accepted_risk` and `not_applicable` could
never appear in a production assessment, and the whole approval workflow was
unreachable from the shipped path.

The rules that matter here are the ones that stop a policy file being a way to
make failing controls disappear quietly.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from ironclad.cli import main
from ironclad.engine import run_assessment
from ironclad.errors import ValidationError
from ironclad.model.assessment import ControlStatus
from ironclad.model.exception import ExceptionStatus
from ironclad.policy import (
    POLICY_VERSION,
    TenantPolicy,
    find_policy,
    load_policy,
    policy_from_document,
    validate_policy,
)
from tests.conftest import NOW, verdict_for


def policy_doc(**overrides) -> dict:
    document = {
        "policy_version": POLICY_VERSION,
        "tenant_id": "acme",
        "scope_exclusions": [],
        "exceptions": [],
        "owners": {},
    }
    document.update(overrides)
    return document


def exclusion(**overrides) -> dict:
    item = {
        "control_id": "CC9.9",
        "justification": "The organisation operates no facility of its own.",
        "approved_by": "j.reyes",
        "approved_at": "2026-03-01T00:00:00+00:00",
    }
    item.update(overrides)
    return item


def acceptance(**overrides) -> dict:
    item = {
        "control_id": "CC1.1",
        "justification": "Remediation is scheduled for the next release train.",
        "requested_by": "alice",
        "approved_by": "bob",
        "approved_at": "2026-08-15T00:00:00+00:00",
        "expires_at": "2026-11-15T00:00:00+00:00",
        "compensating_controls": ["Monthly manual review"],
        "status": "approved",
    }
    item.update(overrides)
    return item


class TestPolicyValidation:
    def test_a_complete_policy_validates(self) -> None:
        document = policy_doc(scope_exclusions=[exclusion()], exceptions=[acceptance()])
        assert validate_policy(document) == []

    def test_an_unsupported_version_is_refused(self) -> None:
        assert any("not supported" in e for e in validate_policy(policy_doc(policy_version="2.0")))

    def test_a_scope_out_without_a_reason_is_refused(self) -> None:
        # "Not applicable" is the cheapest way to make a failing control vanish.
        errors = validate_policy(policy_doc(scope_exclusions=[exclusion(justification="  ")]))
        assert any("written reason" in e for e in errors)

    def test_a_scope_out_without_an_approver_is_refused(self) -> None:
        errors = validate_policy(policy_doc(scope_exclusions=[exclusion(approved_by="")]))
        assert any("must own the decision" in e for e in errors)

    def test_a_control_cannot_be_excluded_twice(self) -> None:
        errors = validate_policy(policy_doc(scope_exclusions=[exclusion(), exclusion()]))
        assert any("excluded twice" in e for e in errors)

    def test_a_control_cannot_have_two_acceptances(self) -> None:
        errors = validate_policy(policy_doc(exceptions=[acceptance(), acceptance()]))
        assert any("two acceptances" in e for e in errors)

    def test_an_approved_acceptance_must_name_its_approver(self) -> None:
        errors = validate_policy(policy_doc(exceptions=[acceptance(approved_by="")]))
        assert any("approved_by is required" in e for e in errors)

    def test_an_approved_acceptance_must_expire(self) -> None:
        errors = validate_policy(policy_doc(exceptions=[acceptance(expires_at=None)]))
        assert any("unfixed gap" in e for e in errors)

    def test_a_bad_timestamp_is_refused(self) -> None:
        errors = validate_policy(policy_doc(scope_exclusions=[exclusion(approved_at="soon")]))
        assert any("ISO-8601" in e for e in errors)

    def test_every_fault_is_reported_at_once(self) -> None:
        errors = validate_policy(
            policy_doc(
                policy_version="",
                tenant_id="",
                scope_exclusions=[exclusion(justification="", approved_by="")],
            )
        )
        assert len(errors) >= 4

    def test_owners_must_be_strings(self) -> None:
        assert any("strings" in e for e in validate_policy(policy_doc(owners={"CC6.1": 7})))


class TestPolicyWorkflowReplay:
    def test_a_policy_cannot_smuggle_in_a_self_approval(self, tmp_path: Path) -> None:
        # The approval workflow is replayed rather than the end state assigned,
        # so a hand-written file cannot assert an approval the workflow refuses.
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(
                policy_doc(exceptions=[acceptance(requested_by="alice", approved_by="alice")])
            )
        )
        with pytest.raises(ValidationError, match="approval workflow refuses"):
            load_policy(path)

    def test_a_policy_cannot_assert_an_over_long_acceptance(self, tmp_path: Path) -> None:
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(
                policy_doc(
                    exceptions=[
                        acceptance(
                            requested_at="2026-01-01T00:00:00+00:00",
                            expires_at="2028-01-01T00:00:00+00:00",
                        )
                    ]
                )
            )
        )
        with pytest.raises(ValidationError):
            load_policy(path)

    def test_an_approved_acceptance_comes_out_active(self) -> None:
        policy = policy_from_document(policy_doc(exceptions=[acceptance()]))
        assert policy.exceptions[0].status is ExceptionStatus.APPROVED
        assert policy.exceptions[0].is_active(NOW)

    def test_a_pending_acceptance_stays_pending(self) -> None:
        policy = policy_from_document(
            policy_doc(exceptions=[acceptance(status="pending_approval", approved_by="")])
        )
        assert policy.exceptions[0].status is ExceptionStatus.PENDING_APPROVAL
        assert not policy.exceptions[0].is_active(NOW)


class TestTenantBinding:
    def test_a_policy_for_another_tenant_is_refused(self, tmp_path: Path) -> None:
        # Applying one client's scope-outs to another client's assessment has to
        # be impossible, not merely unlikely.
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(policy_doc(tenant_id="other-co")))
        with pytest.raises(ValidationError, match="belongs to tenant"):
            load_policy(path, expected_tenant="acme")

    def test_the_engine_refuses_a_mismatched_policy(self, tiny_framework, evidence) -> None:
        with pytest.raises(ValueError, match="tenant policy belongs to"):
            run_assessment(
                tenant_id="acme",
                framework=tiny_framework,
                evidence=evidence,
                policy=TenantPolicy(tenant_id="other-co"),
                group="quick",
                as_of=NOW,
            )

    def test_the_tenant_id_is_slugified_on_both_sides(self, tmp_path: Path) -> None:
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(policy_doc(tenant_id="Acme Corp")))
        assert load_policy(path, expected_tenant="ACME  Corp").tenant_id == "acme-corp"


class TestOwnership:
    def test_an_exact_control_assignment_wins(self) -> None:
        policy = policy_from_document(policy_doc(owners={"CC6.1": "exact", "CC6.*": "wildcard"}))
        assert policy.owner_for("CC6.1") == "exact"

    def test_a_family_wildcard_covers_the_family(self) -> None:
        policy = policy_from_document(policy_doc(owners={"CC6.*": "platform"}))
        assert policy.owner_for("CC6.7") == "platform"
        assert policy.owner_for("CC1.1") == ""


class TestScopeReviewInARun:
    def _policy(self, **overrides) -> TenantPolicy:
        return policy_from_document(policy_doc(scope_exclusions=[exclusion(**overrides)]))

    def test_an_excluded_control_leaves_the_score(self, tiny_framework, evidence) -> None:
        with_policy = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=self._policy(),
            group="standard",
            as_of=NOW,
        )
        assert verdict_for(with_policy, "CC9.9").status is ControlStatus.NOT_APPLICABLE
        assert with_policy.assessment.summary.not_applicable == 1

        # CC9.9 was an unevidenced gap; removing it from the denominator must
        # raise the score rather than leave it unchanged.
        without_policy = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            as_of=NOW,
        )
        assert (
            with_policy.assessment.summary.readiness_score
            > without_policy.assessment.summary.readiness_score
        )

    def test_the_exclusion_is_written_to_the_audit_trail(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=self._policy(),
            group="standard",
            as_of=NOW,
        )
        excluded = [e for e in result.audit.events if e.action == "scope.excluded"]
        assert len(excluded) == 1
        assert excluded[0].metadata["approved_by"] == "j.reyes"
        assert result.audit.is_valid()

    def test_the_rationale_names_who_decided(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=self._policy(),
            group="standard",
            as_of=NOW,
        )
        assert "j.reyes" in verdict_for(result, "CC9.9").rationale

    def test_an_overdue_review_is_flagged(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=self._policy(review_by="2026-01-01T00:00:00+00:00"),
            group="standard",
            as_of=NOW,
        )
        assert any("overdue for review" in f.title for f in result.findings)

    def test_an_imminent_review_is_flagged(self, tiny_framework, evidence) -> None:
        review = (NOW + timedelta(days=10)).isoformat()
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=self._policy(review_by=review),
            group="standard",
            as_of=NOW,
        )
        assert any("falls due for review" in f.title for f in result.findings)

    def test_excluding_a_control_that_has_evidence_is_flagged(
        self, tiny_framework, evidence
    ) -> None:
        # Usually means the exclusion has outlived its business reason.
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=self._policy(control_id="CC6.1"),
            group="standard",
            as_of=NOW,
        )
        assert any("has supporting evidence" in f.title for f in result.findings)

    def test_excluding_an_unknown_control_warns(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=self._policy(control_id="NOT-A-CONTROL"),
            group="standard",
            as_of=NOW,
        )
        assert any("not in" in w for w in result.warnings)

    def test_no_remediation_work_is_raised_for_an_excluded_control(
        self, tiny_framework, evidence
    ) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=self._policy(),
            group="standard",
            as_of=NOW,
        )
        assert "CC9.9" not in {item.control_id for item in result.plan.items}

    def test_scope_takes_precedence_over_an_acceptance(self, tiny_framework, evidence) -> None:
        # Both name CC9.9. The exclusion must win, or the control would return
        # to the denominator as accepted_risk.
        policy = policy_from_document(
            policy_doc(
                scope_exclusions=[exclusion(control_id="CC9.9")],
                exceptions=[acceptance(control_id="CC9.9")],
            )
        )
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=policy,
            group="standard",
            as_of=NOW,
        )
        assert verdict_for(result, "CC9.9").status is ControlStatus.NOT_APPLICABLE
        assert any("scope exclusion takes precedence" in w for w in result.warnings)


class TestAcceptanceReachesTheRun:
    def test_a_policy_acceptance_converts_a_gap(self, tiny_framework, evidence) -> None:
        # The whole point: before the policy file, this could never happen from
        # the pipeline.
        policy = policy_from_document(policy_doc(exceptions=[acceptance(control_id="CC9.9")]))
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=policy,
            group="standard",
            as_of=NOW,
        )
        assert verdict_for(result, "CC9.9").status is ControlStatus.ACCEPTED_RISK

    def test_an_explicit_exception_list_overrides_the_policy(
        self, tiny_framework, evidence
    ) -> None:
        # The service layer reads acceptances from its own store instead.
        policy = policy_from_document(policy_doc(exceptions=[acceptance(control_id="CC9.9")]))
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            policy=policy,
            exceptions=[],
            group="standard",
            as_of=NOW,
        )
        assert verdict_for(result, "CC9.9").status is ControlStatus.GAP


class TestPolicyThroughTheCli:
    def _evidence_dir(self, tmp_path: Path) -> Path:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "Access Control Policy.md").write_text(
            "Access control policy. Least privilege, role definitions, separation of duties, "
            "user access review, privileged access register."
        )
        return evidence_dir

    def test_a_policy_beside_the_evidence_is_discovered(self, tmp_path: Path) -> None:
        evidence_dir = self._evidence_dir(tmp_path)
        (evidence_dir / "policy.json").write_text(
            json.dumps(
                policy_doc(tenant_id="acme", scope_exclusions=[exclusion(control_id="CC6.4")])
            )
        )
        out = tmp_path / "out"
        assert (
            main(
                [
                    "assess",
                    "--client",
                    "acme",
                    "--framework",
                    "soc2",
                    "--evidence-dir",
                    str(evidence_dir),
                    "--group",
                    "standard",
                    "--out",
                    str(out),
                ]
            )
            == 0
        )
        document = json.loads((out / "assessment.json").read_text())
        statuses = {c["control_id"]: c["status"] for c in document["controls"]}
        assert statuses["CC6.4"] == "not_applicable"

    def test_find_policy_returns_nothing_when_there_is_none(self, tmp_path: Path) -> None:
        assert find_policy(self._evidence_dir(tmp_path)) is None

    def test_an_explicit_policy_that_does_not_exist_is_an_error(self, tmp_path: Path) -> None:
        assert (
            main(
                [
                    "assess",
                    "--client",
                    "acme",
                    "--framework",
                    "soc2",
                    "--evidence-dir",
                    str(self._evidence_dir(tmp_path)),
                    "--policy",
                    str(tmp_path / "absent.json"),
                    "--out",
                    str(tmp_path / "out"),
                ]
            )
            == 2
        )

    def test_validate_accepts_a_good_policy(self, tmp_path: Path) -> None:
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(policy_doc(exceptions=[acceptance()])))
        assert main(["validate", "--policy", str(path)]) == 0

    def test_validate_rejects_a_self_approved_acceptance(self, tmp_path: Path, capsys) -> None:
        # Structurally valid, but the workflow refuses it — validate must catch
        # that, not just the schema.
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(policy_doc(exceptions=[acceptance(requested_by="x", approved_by="x")]))
        )
        assert main(["validate", "--policy", str(path)]) == 2
        assert "second person" in capsys.readouterr().out
