"""The basis of assessment: whose rule each verdict rests on.

Every judgment in an assessment comes from the framework, from Iron City's own
policy, or from the client's determinations, and the report used to present all
three in the same voice. An auditor asking where SOC 2 requires two corroborating
documents needs to be told plainly that it does not — that bar is ours.

The rules here are the ones that keep the disclosure honest: it is generated
from the constants the engine actually applies, it names Iron City's bars as
Iron City's, and it reaches every deliverable.
"""

from __future__ import annotations

import json

import pytest

from ironclad.engine import run_assessment
from ironclad.method import (
    FRAMEWORK,
    ICIT_POLICY,
    SOURCE_LABELS,
    TENANT_POLICY,
    method_dict,
    method_rules,
)
from ironclad.model.assessment import STATUS_CREDIT, ControlStatus
from ironclad.model.control import FAMILY_WEIGHT
from ironclad.model.evidence import DEFAULT_VALIDITY_DAYS, VALIDITY_DAYS
from ironclad.modules.control_mapping import CORROBORATION_MIN, RELEVANCE_THRESHOLD
from ironclad.report.render import render_html
from ironclad.report.views import ASSESSMENT_TYPES
from tests.conftest import NOW


@pytest.fixture
def result(tiny_framework, evidence):
    return run_assessment(
        tenant_id="acme",
        framework=tiny_framework,
        evidence=evidence,
        group="deep",
        as_of=NOW,
        assessment_id="acme-method-1",
    )


class TestEveryRuleNamesItsSource:
    def test_every_rule_has_a_known_source(self) -> None:
        for rule in method_rules():
            assert rule.source in SOURCE_LABELS, rule.name
            assert rule.source_label == SOURCE_LABELS[rule.source]

    def test_every_rule_says_something(self) -> None:
        for rule in method_rules():
            assert rule.name.strip()
            assert len(rule.statement) > 40, rule.name

    def test_all_three_sources_are_represented(self) -> None:
        sources = {rule.source for rule in method_rules()}
        assert sources == {FRAMEWORK, ICIT_POLICY, TENANT_POLICY}

    def test_the_control_set_is_the_framework_s(self) -> None:
        # If this ever reads as Iron City policy, the product is inventing
        # controls, which is the one thing it must never do.
        control_set = next(r for r in method_rules() if r.name == "Control set")
        assert control_set.source == FRAMEWORK

    @pytest.mark.parametrize(
        "name",
        ["Corroboration", "Evidence relevance", "Evidence freshness", "Readiness score"],
    )
    def test_our_own_bars_are_declared_as_ours(self, name: str) -> None:
        rule = next(r for r in method_rules() if r.name == name)
        assert rule.source == ICIT_POLICY, f"{name} is Iron City's bar, not the framework's"

    def test_the_corroboration_rule_says_no_framework_requires_it(self) -> None:
        rule = next(r for r in method_rules() if r.name == "Corroboration")
        assert "No framework requires this" in rule.statement


class TestTheStatedRulesAreTheAppliedRules:
    """Generated from the engine's constants, so it cannot describe a rule the
    engine stopped applying."""

    def test_the_corroboration_number_is_the_one_in_the_matcher(self) -> None:
        rule = next(r for r in method_rules() if r.name == "Corroboration")
        assert str(CORROBORATION_MIN) in rule.value

    def test_the_relevance_threshold_is_the_one_in_the_matcher(self) -> None:
        rule = next(r for r in method_rules() if r.name == "Evidence relevance")
        assert f"{RELEVANCE_THRESHOLD:.0%}" in rule.value

    def test_every_freshness_window_appears(self) -> None:
        rule = next(r for r in method_rules() if r.name == "Evidence freshness")
        for evidence_type, days in VALIDITY_DAYS.items():
            assert evidence_type in rule.value, evidence_type
            assert f"{days} days" in rule.value, evidence_type
        assert f"{DEFAULT_VALIDITY_DAYS} days for anything else" in rule.value

    def test_every_weighted_family_appears(self) -> None:
        rule = next(r for r in method_rules() if r.name == "Risk weighting")
        for family, weight in FAMILY_WEIGHT.items():
            assert family in rule.value, family
            assert f"×{weight:g}" in rule.value, family

    def test_the_credit_for_each_status_appears(self) -> None:
        rule = next(r for r in method_rules() if r.name == "Readiness score")
        for status in (
            ControlStatus.COMPLIANT,
            ControlStatus.PARTIAL,
            ControlStatus.ACCEPTED_RISK,
            ControlStatus.GAP,
        ):
            assert f"{str(status)} {STATUS_CREDIT[status]:g}" in rule.value, status

    def test_the_ai_rule_states_that_commentary_never_scores(self) -> None:
        rule = next(r for r in method_rules() if r.name == "AI commentary")
        assert "never moves the score" in rule.statement


class TestItReachesTheDeliverables:
    @pytest.mark.parametrize("assessment_type", ASSESSMENT_TYPES)
    def test_every_report_states_the_basis(
        self, tiny_framework, evidence, assessment_type: str
    ) -> None:
        # Including the readiness summary, which shows no register: an abridged
        # report still has to say what the verdicts rest on.
        run = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="deep",
            as_of=NOW,
            assessment_type=assessment_type,
            assessment_id=f"acme-{assessment_type}",
        )
        html = render_html(run, "Acme Corp")
        assert "Basis of assessment" in html
        assert "Iron City policy" in html

    def test_the_report_marks_which_rules_are_ours(self, result) -> None:
        html = render_html(result, "Acme Corp")
        ours = sum(1 for rule in method_rules() if rule.source == ICIT_POLICY)
        assert html.count('class="ours"') == ours

    def test_the_stored_record_carries_the_basis(self, result) -> None:
        document = json.loads(json.dumps(result.to_dict()))
        assert [r["name"] for r in document["method"]["rules"]] == [r.name for r in method_rules()]
        assert document["method"]["sources"] == SOURCE_LABELS

    def test_the_basis_survives_a_round_trip(self, result) -> None:
        # The machine record is what an auditor reads back years later, with no
        # report beside it.
        document = json.loads(json.dumps(result.to_dict()))
        corroboration = next(r for r in document["method"]["rules"] if r["name"] == "Corroboration")
        assert corroboration["source"] == ICIT_POLICY
        assert str(CORROBORATION_MIN) in corroboration["value"]

    def test_the_basis_names_no_underlying_tool(self, result) -> None:
        text = json.dumps(method_dict()).lower()
        for name in ("zap", "nuclei", "wazuh", "prowler", "openai", "anthropic", "groq"):
            assert name not in text, f"the basis names {name}"
