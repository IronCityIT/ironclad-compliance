"""The domain rules — scoring, freshness, weighting, prioritisation."""

from __future__ import annotations

from datetime import timedelta

import pytest

from ironclad.model.assessment import (
    Assessment,
    ControlAssessment,
    ControlStatus,
    blank_control_assessment,
    worst,
)
from ironclad.model.control import Control, Framework
from ironclad.model.evidence import EvidenceArtifact, EvidenceSet, validity_days_for
from ironclad.model.remediation import RemediationPlan, Severity, build_item, severity_for
from tests.conftest import NOW, make_artifact


class TestControlFamily:
    @pytest.mark.parametrize(
        ("control_id", "expected"),
        [
            ("CC6.1", "CC6"),
            ("CC1.5", "CC1"),
            ("PR.AA-05", "PR"),
            ("GV.OC-01", "GV"),
            ("10.2", "10"),
            ("1.1", "1"),
            ("12.10", "12"),
            ("164.312(a)(1)", "164.312"),
            ("164.308(a)(1)(ii)(A)", "164.308"),
        ],
    )
    def test_family_covers_every_id_shape(self, control_id: str, expected: str) -> None:
        assert Control(id=control_id, name="n", description="d").family == expected

    def test_access_control_outweighs_governance(self) -> None:
        access = Control(id="CC6.1", name="n", description="d")
        governance = Control(id="CC1.1", name="n", description="d")
        assert access.weight > governance.weight

    def test_keywords_exclude_boilerplate(self) -> None:
        control = Control(
            id="CC6.1",
            name="Logical Access",
            description="The entity restricts logical access.",
            common_evidence=("Access control policy",),
        )
        terms = control.keywords()
        assert "access" in terms
        # "policy" and "entity" appear in nearly every control; matching on them
        # would make every document look relevant to every control.
        assert "policy" not in terms
        assert "entity" not in terms


class TestFramework:
    def test_duplicate_control_ids_are_rejected(self) -> None:
        duplicate = Control(id="CC1.1", name="n", description="d")
        with pytest.raises(ValueError, match="duplicate control id"):
            Framework(id="f", name="F", version="1", controls=(duplicate, duplicate))


class TestEvidenceFreshness:
    def test_evidence_class_sets_the_window(self) -> None:
        # An access review ages far faster than a policy, and the engine has to
        # know that without being told per artifact.
        assert validity_days_for("Quarterly access review") == 90
        assert validity_days_for("Information security policy") == 365
        assert validity_days_for("Vulnerability scan") == 30

    def test_longest_matching_key_wins(self) -> None:
        # "access review" (90) must beat the bare "review" key, not race it.
        assert validity_days_for("User access review") == 90

    def test_explicit_valid_until_overrides_the_derived_window(self) -> None:
        artifact = make_artifact(
            "Policy", "text", evidence_type="policy", valid_until=NOW + timedelta(days=5)
        )
        assert artifact.effective_valid_until == NOW + timedelta(days=5)
        assert not artifact.is_stale(NOW)
        assert artifact.is_stale(NOW + timedelta(days=6))

    def test_expired_evidence_is_stale(self) -> None:
        artifact = make_artifact(
            "Old review",
            "text",
            evidence_type="access review",
            collected_at=NOW - timedelta(days=200),
        )
        assert artifact.is_stale(NOW)

    def test_evidence_set_refuses_another_tenants_artifact(self) -> None:
        evidence = EvidenceSet(tenant_id="acme")
        foreign = EvidenceArtifact(artifact_id="x", tenant_id="other-co", name="n", uri="u")
        with pytest.raises(ValueError, match="belongs to tenant"):
            evidence.add(foreign)


class TestScoring:
    def _assessment(self, statuses: list[tuple[str, ControlStatus, float]]) -> Assessment:
        framework = Framework(id="f", name="F", version="1")
        assessment = Assessment(assessment_id="a", tenant_id="acme", framework=framework)
        for control_id, status, weight in statuses:
            assessment.controls.append(
                ControlAssessment(
                    control_id=control_id,
                    control_name=control_id,
                    status=status,
                    weight=weight,
                )
            )
        return assessment

    def test_all_compliant_scores_100(self) -> None:
        assessment = self._assessment(
            [("a", ControlStatus.COMPLIANT, 1.0), ("b", ControlStatus.COMPLIANT, 1.5)]
        )
        assert assessment.recompute_summary().readiness_score == 100.0

    def test_all_gaps_score_zero(self) -> None:
        assessment = self._assessment(
            [("a", ControlStatus.GAP, 1.0), ("b", ControlStatus.GAP, 1.5)]
        )
        assert assessment.recompute_summary().readiness_score == 0.0

    def test_partial_earns_half_credit(self) -> None:
        assessment = self._assessment(
            [("a", ControlStatus.PARTIAL, 1.0), ("b", ControlStatus.PARTIAL, 1.0)]
        )
        assert assessment.recompute_summary().readiness_score == 50.0

    def test_a_heavy_gap_costs_more_than_a_light_one(self) -> None:
        heavy_gap = (
            self._assessment([("a", ControlStatus.GAP, 1.5), ("b", ControlStatus.COMPLIANT, 1.0)])
            .recompute_summary()
            .readiness_score
        )
        light_gap = (
            self._assessment([("a", ControlStatus.GAP, 1.0), ("b", ControlStatus.COMPLIANT, 1.5)])
            .recompute_summary()
            .readiness_score
        )
        assert heavy_gap < light_gap

    def test_not_applicable_leaves_the_denominator(self) -> None:
        # Scoping a control out must not silently penalise the tenant.
        assessment = self._assessment(
            [("a", ControlStatus.COMPLIANT, 1.0), ("b", ControlStatus.NOT_APPLICABLE, 1.0)]
        )
        summary = assessment.recompute_summary()
        assert summary.readiness_score == 100.0
        assert summary.not_applicable == 1

    def test_accepted_risk_scores_between_a_gap_and_a_pass(self) -> None:
        accepted = (
            self._assessment([("a", ControlStatus.ACCEPTED_RISK, 1.0)])
            .recompute_summary()
            .readiness_score
        )
        assert 0.0 < accepted < 100.0

    def test_an_assessment_with_no_scorable_controls_does_not_divide_by_zero(self) -> None:
        assessment = self._assessment([("a", ControlStatus.NOT_APPLICABLE, 1.0)])
        assert assessment.recompute_summary().readiness_score == 0.0

    def test_worst_picks_the_most_severe(self) -> None:
        assert worst([ControlStatus.COMPLIANT, ControlStatus.GAP]) is ControlStatus.GAP
        assert worst([]) is ControlStatus.PENDING

    def test_blank_verdict_carries_the_controls_weight_and_points(
        self, tiny_framework: Framework
    ) -> None:
        verdict = blank_control_assessment(tiny_framework.controls[0])
        assert verdict.status is ControlStatus.PENDING
        assert verdict.points_total == 2
        assert verdict.weight == 1.5


class TestRemediationPriority:
    def _verdict(
        self, control_id: str, status: ControlStatus, weight: float, coverage: float = 0.0
    ):
        covered = int(coverage * 4)
        return ControlAssessment(
            control_id=control_id,
            control_name=control_id,
            status=status,
            weight=weight,
            points_covered=covered,
            points_total=4,
        )

    def test_a_gap_in_a_heavy_family_is_critical(self) -> None:
        assert severity_for(self._verdict("CC6.1", ControlStatus.GAP, 1.5)) is Severity.CRITICAL

    def test_a_gap_in_a_light_family_is_high(self) -> None:
        assert severity_for(self._verdict("CC1.1", ControlStatus.GAP, 1.0)) is Severity.HIGH

    def test_a_partial_ranks_below_the_gap_it_would_have_been(self) -> None:
        gap = severity_for(self._verdict("CC6.1", ControlStatus.GAP, 1.5))
        partial = severity_for(self._verdict("CC6.1", ControlStatus.PARTIAL, 1.5))
        assert gap is Severity.CRITICAL
        assert partial is Severity.HIGH

    def test_a_nearly_covered_control_ranks_below_an_untouched_one(self) -> None:
        untouched = build_item(
            "acme", self._verdict("CC6.1", ControlStatus.PARTIAL, 1.5, 0.0), "g", [], NOW
        )
        nearly = build_item(
            "acme", self._verdict("CC6.2", ControlStatus.PARTIAL, 1.5, 0.75), "g", [], NOW
        )
        assert untouched.priority > nearly.priority

    def test_severity_drives_the_due_date(self) -> None:
        critical = build_item("acme", self._verdict("CC6.1", ControlStatus.GAP, 1.5), "g", [], NOW)
        low_risk = build_item("acme", self._verdict("CC1.1", ControlStatus.GAP, 1.0), "g", [], NOW)
        assert critical.due_date is not None and low_risk.due_date is not None
        assert critical.due_date < low_risk.due_date

    def test_item_ids_are_stable_across_runs(self) -> None:
        first = build_item("acme", self._verdict("CC6.1", ControlStatus.GAP, 1.5), "g", [], NOW)
        second = build_item("acme", self._verdict("CC6.1", ControlStatus.GAP, 1.5), "g", [], NOW)
        assert first.item_id == second.item_id

    def test_item_ids_differ_between_tenants(self) -> None:
        acme = build_item("acme", self._verdict("CC6.1", ControlStatus.GAP, 1.5), "g", [], NOW)
        other = build_item("other-co", self._verdict("CC6.1", ControlStatus.GAP, 1.5), "g", [], NOW)
        assert acme.item_id != other.item_id

    def test_the_plan_orders_by_priority_then_control_id(self) -> None:
        plan = RemediationPlan(tenant_id="acme", assessment_id="a")
        for control_id, weight in (("CC1.1", 1.0), ("CC6.1", 1.5), ("CC6.2", 1.5)):
            plan.add(
                build_item(
                    "acme", self._verdict(control_id, ControlStatus.GAP, weight), "g", [], NOW
                )
            )
        ordered = [item.control_id for item in plan.ordered()]
        assert ordered == ["CC6.1", "CC6.2", "CC1.1"]

    def test_overdue_excludes_completed_work(self) -> None:
        from ironclad.model.remediation import RemediationStatus

        plan = RemediationPlan(tenant_id="acme", assessment_id="a")
        item = build_item("acme", self._verdict("CC6.1", ControlStatus.GAP, 1.5), "g", [], NOW)
        plan.add(item)
        assert len(plan.overdue(NOW + timedelta(days=999))) == 1
        item.status = RemediationStatus.COMPLETE
        assert plan.overdue(NOW + timedelta(days=999)) == []
