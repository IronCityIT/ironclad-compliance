"""What changed between two assessments.

A compliance programme is a trend, not a snapshot, and everything needed to
answer "what moved" has been stored since the first release without anything
reading it back.

The rules under test are the ones that stop a trend flattering the client by
accident. A control scoped out leaves the denominator and lifts the score, which
looks exactly like progress and is not. A framework version change moves the
control set underneath the comparison. A control that appears in only one of the
two runs is either a scope change or a defect, and dropping it hides which.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from ironclad.cli import main
from ironclad.compare import (
    ACCEPTANCE_LAPSED,
    IMPROVED,
    MOVEMENT_RANK,
    REGRESSED,
    RISK_ACCEPTED,
    SCOPED_IN,
    SCOPED_OUT,
    compare,
)
from ironclad.engine import run_assessment
from ironclad.model.assessment import ControlStatus
from ironclad.model.exception import RiskException
from ironclad.policy import ScopeExclusion, TenantPolicy
from tests.conftest import NOW


@pytest.fixture
def earlier(tiny_framework, evidence) -> dict[str, Any]:
    result = run_assessment(
        tenant_id="acme",
        framework=tiny_framework,
        evidence=evidence,
        group="deep",
        as_of=NOW,
        assessment_id="acme-q3",
    )
    return json.loads(json.dumps(result.to_dict()))


def revised(document: dict[str, Any], assessment_id: str = "acme-q4", **changes) -> dict[str, Any]:
    """The same assessment, later, with named controls moved."""
    later = json.loads(json.dumps(document))
    later["assessment_id"] = assessment_id
    later["started_at"] = "2026-12-01T00:00:00+00:00"
    for control in later["controls"]:
        if control["control_id"] in changes:
            control["status"] = changes[control["control_id"]]
    return later


class TestTheMovementRanking:
    def test_a_scoped_out_control_has_no_rank(self) -> None:
        # It is not a better or a worse outcome; it is out of scope. Ranking it
        # at all is what makes a scope change read as progress.
        assert ControlStatus.NOT_APPLICABLE not in MOVEMENT_RANK

    def test_an_accepted_risk_ranks_with_partial(self) -> None:
        # The control is still not met, and somebody decided about it — the same
        # 0.5 the readiness score gives it.
        assert MOVEMENT_RANK[ControlStatus.ACCEPTED_RISK] == MOVEMENT_RANK[ControlStatus.PARTIAL]

    def test_only_compliant_is_the_top(self) -> None:
        assert MOVEMENT_RANK[ControlStatus.COMPLIANT] == max(MOVEMENT_RANK.values())

    def test_a_gap_and_an_unassessed_control_rank_together(self) -> None:
        assert MOVEMENT_RANK[ControlStatus.PENDING] == MOVEMENT_RANK[ControlStatus.GAP]


class TestMovement:
    def test_a_control_that_was_met_and_now_is_not_is_a_regression(self, earlier) -> None:
        later = revised(earlier, **{"CC6.1": "gap"})
        result = compare(earlier, later)
        assert [c.control_id for c in result.regressed] == ["CC6.1"]
        assert result.regressed[0].movement == REGRESSED
        assert result.improved == []

    def test_a_gap_that_became_partial_is_an_improvement(self, earlier) -> None:
        later = revised(earlier, **{"CC9.9": "partial"})
        result = compare(earlier, later)
        assert [c.control_id for c in result.improved] == ["CC9.9"]

    def test_partial_to_accepted_risk_is_not_progress(self, earlier) -> None:
        # Deciding to accept a risk is a decision, not a fix. It must not appear
        # in a list a client reads as work done.
        later = revised(earlier, **{"CC1.1": "accepted_risk"})
        result = compare(earlier, later)
        assert result.improved == []
        assert result.regressed == []
        # Named for what it is, not folded into "unchanged": a reader should
        # see that a decision was taken, and that it was not progress.
        assert [c.control_id for c in result.risk_accepted] == ["CC1.1"]
        assert result.risk_accepted[0].movement == RISK_ACCEPTED

    def test_a_gap_accepted_as_risk_is_a_decision_not_an_improvement(self, earlier) -> None:
        # The first version ranked accepted_risk with partial, so gap → accepted
        # read as "improved" and closed the remediation item as if fixed.
        # Accepting every gap in the sample read as "11 improved, 27 closed".
        later = revised(earlier, **{"CC9.9": "accepted_risk"})
        later["remediation"]["items"] = [
            i for i in later["remediation"]["items"] if i["control_id"] != "CC9.9"
        ]
        result = compare(earlier, later)
        assert result.improved == []
        assert [c.control_id for c in result.risk_accepted] == ["CC9.9"]
        assert result.remediation_closed == []
        assert [i["control_id"] for i in result.remediation_set_aside] == ["CC9.9"]
        assert "1 accepted as risk" in result.headline()
        assert "0 remediation item(s) closed" in result.headline()

    def test_a_lapsed_acceptance_is_not_a_regression_but_is_named(self, earlier) -> None:
        accepted = revised(earlier, assessment_id="acme-q2", **{"CC9.9": "accepted_risk"})
        accepted["started_at"] = "2026-06-01T00:00:00+00:00"
        lapsed = revised(earlier, **{"CC9.9": "gap"})
        result = compare(accepted, lapsed)
        assert result.regressed == []
        assert [c.control_id for c in result.acceptance_lapsed] == ["CC9.9"]
        assert result.acceptance_lapsed[0].movement == ACCEPTANCE_LAPSED

    def test_an_accepted_control_that_is_then_fixed_is_an_improvement(self, earlier) -> None:
        accepted = revised(earlier, assessment_id="acme-q2", **{"CC9.9": "accepted_risk"})
        accepted["started_at"] = "2026-06-01T00:00:00+00:00"
        fixed = revised(earlier, **{"CC9.9": "compliant"})
        result = compare(accepted, fixed)
        assert [c.control_id for c in result.improved] == ["CC9.9"]
        assert result.acceptance_lapsed == []

    def test_a_met_control_accepted_as_risk_is_a_regression(self, earlier) -> None:
        # The mirror of the case above. Filed as a decision alone, the control
        # that stopped working read "0 regressed" while the score fell.
        later = revised(earlier, **{"CC6.1": "accepted_risk"})
        result = compare(earlier, later)
        assert [c.control_id for c in result.regressed] == ["CC6.1"]
        assert result.regressed[0].movement == REGRESSED
        assert result.regressed[0].was == "compliant"
        assert result.risk_accepted == []
        assert "1 regressed" in result.headline()

    def test_every_change_records_both_ends(self, earlier) -> None:
        later = revised(earlier, **{"CC9.9": "compliant"})
        change = compare(earlier, later).improved[0]
        assert change.was == "gap"
        assert change.now == "compliant"
        assert change.movement == IMPROVED
        assert change.control_name

    def test_an_unchanged_control_is_counted_not_listed(self, earlier) -> None:
        result = compare(earlier, revised(earlier))
        assert result.improved == [] and result.regressed == []
        assert len(result.unchanged) == len(earlier["controls"])
        assert result.to_dict()["controls"]["unchanged"] == len(earlier["controls"])


class TestAScopeChangeIsNotProgress:
    def test_scoping_a_control_out_is_reported_as_a_scope_change(self, earlier) -> None:
        # The one that matters: it leaves the denominator and lifts the score,
        # which looks exactly like the control being fixed.
        later = revised(earlier, **{"CC9.9": "not_applicable"})
        result = compare(earlier, later)
        assert result.improved == []
        assert [c.control_id for c in result.scoped_out] == ["CC9.9"]
        assert result.scoped_out[0].movement == SCOPED_OUT

    def test_scoping_a_control_back_in_is_reported_too(self, earlier) -> None:
        out = revised(earlier, **{"CC9.9": "not_applicable"})
        back = revised(out, assessment_id="acme-q5", **{"CC9.9": "gap"})
        result = compare(out, back)
        assert [c.control_id for c in result.scoped_in] == ["CC9.9"]
        assert result.scoped_in[0].movement == SCOPED_IN
        assert result.regressed == []

    def test_a_scope_change_never_lands_in_improved_or_regressed(self, earlier) -> None:
        later = revised(earlier, **{"CC6.1": "not_applicable", "CC1.1": "not_applicable"})
        result = compare(earlier, later)
        moved = {c.control_id for c in result.improved + result.regressed}
        assert moved == set()
        assert len(result.scoped_out) == 2


class TestTheComparisonRefusesToMislead:
    def test_two_tenants_cannot_be_compared(self, earlier) -> None:
        # Meaningless as a trend, and a cross-tenant read besides.
        other = json.loads(json.dumps(earlier))
        other["tenant_id"] = "beta"
        with pytest.raises(ValueError, match="different tenants"):
            compare(earlier, other)

    def test_a_swapped_pair_is_refused_rather_than_read_backwards(self, earlier) -> None:
        # The flags say which is which. Passed the wrong way round, every
        # improvement would have been reported as a regression.
        later = revised(earlier, **{"CC9.9": "partial"})
        with pytest.raises(ValueError, match="started after the later one"):
            compare(later, earlier)
        # the right way round still works, and the same moment is not "after"
        assert compare(earlier, later).improved
        same_moment = revised(earlier)
        same_moment["started_at"] = earlier["started_at"]
        assert compare(earlier, same_moment).comparable

    def test_an_assessment_is_not_compared_with_itself(self, earlier) -> None:
        # One record on both sides read "level 0.0, 0 improved, 0 regressed":
        # a trend of nothing, and a client report section saying so.
        with pytest.raises(ValueError, match="acme-q3; an assessment compared with itself"):
            compare(earlier, earlier)
        with pytest.raises(ValueError, match="compared with itself"):
            compare(earlier, revised(earlier, assessment_id="acme-q3"))

    def test_a_record_without_a_start_time_is_not_ordered(self, earlier) -> None:
        later = revised(earlier)
        del later["started_at"]
        assert compare(later, earlier).comparable

    def test_two_frameworks_are_marked_not_comparable(self, earlier) -> None:
        later = revised(earlier)
        later["framework"]["id"] = "hipaa"
        result = compare(earlier, later)
        assert result.comparable is False
        assert any("different frameworks" in c for c in result.caveats)

    def test_a_framework_version_change_is_marked_not_comparable(self, earlier) -> None:
        # The control set moved underneath the comparison. Saying so beats
        # quietly producing a number that looks like a trend.
        later = revised(earlier)
        later["framework"]["version"] = "2.0"
        result = compare(earlier, later)
        assert result.comparable is False
        assert any("moved from version" in c for c in result.caveats)

    def test_a_control_present_in_only_one_run_is_named(self, earlier) -> None:
        later = revised(earlier)
        later["controls"] = [c for c in later["controls"] if c["control_id"] != "CC9.9"]
        later["controls"].append(
            {"control_id": "CC9.10", "control_name": "New", "status": "gap", "points_covered": 0}
        )
        result = compare(earlier, later)
        assert result.only_earlier == ["CC9.9"]
        assert result.only_later == ["CC9.10"]
        assert any("appear only in the earlier" in c for c in result.caveats)

    def test_a_run_without_remediation_planning_is_not_a_remediation_trend(self, earlier) -> None:
        # A quick-group run plans nothing; against a deep run every item read
        # as opened — "27 opened" with no gap having appeared.
        quick = json.loads(json.dumps(earlier))
        quick["modules_run"] = ["evidence_inventory", "control_mapping"]
        quick["remediation"]["items"] = []
        deep = revised(earlier)
        result = compare(quick, deep)
        assert any("did not run remediation planning" in c for c in result.caveats)
        assert any("earlier assessment" in c for c in result.caveats)

    def test_an_earlier_run_without_remediation_planning_opens_nothing(
        self, earlier, tiny_framework, evidence
    ) -> None:
        # A quick run followed by a deep one: the quick run planned nothing, so
        # every item of the deep plan was new to it, and each read as newly
        # raised in the headline and on the report card. Nothing says any gap
        # appeared between the two.
        quick = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="quick",
            as_of=NOW,
            assessment_id="acme-q2",
        )
        first = json.loads(json.dumps(quick.to_dict()))
        first["started_at"] = "2026-01-01T00:00:00+00:00"
        later = revised(earlier)
        assert later["remediation"]["items"], "the fixture must plan something"
        result = compare(first, later)
        assert result.remediation_opened == []
        assert sorted(i["item_id"] for i in result.remediation_first_planned) == sorted(
            i["item_id"] for i in later["remediation"]["items"]
        )
        assert result.to_dict()["remediation"]["first_planned"] == result.remediation_first_planned
        assert result.headline().endswith(", 0 opened")
        assert any("not counted as opened" in c for c in result.caveats)

    def test_a_later_run_without_remediation_planning_closes_nothing(
        self, earlier, tiny_framework, evidence
    ) -> None:
        # A deep run followed by a quick one: the quick run planned nothing, so
        # every item left the plan, and each read as remediation closed in the
        # headline and on the report card. Nothing says any was fixed.
        quick = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="quick",
            as_of=NOW,
            assessment_id="acme-q4",
        )
        later = json.loads(json.dumps(quick.to_dict()))
        later["started_at"] = "2026-12-01T00:00:00+00:00"
        assert earlier["remediation"]["items"], "the fixture must plan something"
        result = compare(earlier, later)
        assert result.remediation_closed == []
        assert sorted(i["item_id"] for i in result.remediation_unplanned) == sorted(
            i["item_id"] for i in earlier["remediation"]["items"]
        )
        assert result.to_dict()["remediation"]["unplanned"] == result.remediation_unplanned
        assert "0 remediation item(s) closed" in result.headline()
        assert any("not counted as closed" in c for c in result.caveats)

    def test_an_identical_pair_carries_no_caveat(self, earlier) -> None:
        assert compare(earlier, revised(earlier)).caveats == []
        assert compare(earlier, revised(earlier)).comparable is True

    def test_a_later_run_without_exception_review_says_the_lapse_may_be_its_own(
        self, tiny_framework, evidence
    ) -> None:
        # A deep run with an acceptance in force, then a quick run the same
        # day: the quick run never reviews exceptions, so the control read as
        # "acceptance lapsed" with nothing saying the later run did not look.
        acceptance = RiskException(
            exception_id="ex-CC9.9",
            tenant_id="acme",
            control_id="CC9.9",
            justification="Compensating monitoring is in place until the next release.",
            requested_by="alice",
            requested_at=NOW,
            expires_at=NOW + timedelta(days=90),
            compensating_controls=["Daily review of privileged activity"],
        )
        acceptance.submit()
        acceptance.approve("bob", at=NOW)
        first, second = (
            json.loads(
                json.dumps(
                    run_assessment(
                        tenant_id="acme",
                        framework=tiny_framework,
                        evidence=evidence,
                        group=group,
                        exceptions=[acceptance],
                        as_of=NOW,
                        assessment_id=assessment_id,
                    ).to_dict()
                )
            )
            for assessment_id, group in (("acme-q3", "deep"), ("acme-q4", "quick"))
        )
        second["started_at"] = "2026-12-01T00:00:00+00:00"
        result = compare(first, second)
        assert [c.control_id for c in result.acceptance_lapsed] == ["CC9.9"]
        assert any(
            "later assessment did not run exception review" in c
            and "1 control(s) listed as acceptance lapsed" in c
            for c in result.caveats
        )
        assert any("later assessment did not run scope review" in c for c in result.caveats)

    @pytest.mark.parametrize(
        ("module", "listed"),
        [("exception_review", "risk accepted"), ("scope_review", "scoped out")],
    )
    def test_an_earlier_run_without_a_deciding_capability_is_named(
        self, earlier, module, listed
    ) -> None:
        first = json.loads(json.dumps(earlier))
        first["modules_run"] = [m for m in first["modules_run"] if m != module]
        result = compare(first, revised(earlier))
        caveat = [c for c in result.caveats if "earlier assessment did not run" in c]
        assert len(caveat) == 1
        assert module.replace("_", " ") in caveat[0]
        assert f"0 control(s) listed as {listed}" in caveat[0]

    def test_a_record_without_a_module_list_carries_no_capability_caveat(self, earlier) -> None:
        # Nothing says what the older record ran; guessing would invent a caveat.
        first = json.loads(json.dumps(earlier))
        del first["modules_run"]
        assert compare(first, revised(earlier)).caveats == []


class TestRemediationMovement:
    def test_an_item_that_went_away_is_closed(self, earlier) -> None:
        later = revised(earlier)
        dropped = later["remediation"]["items"].pop(0)
        result = compare(earlier, later)
        assert [i["item_id"] for i in result.remediation_closed] == [dropped["item_id"]]
        assert result.remediation_opened == []

    def test_an_item_whose_control_left_the_assessment_is_not_closed(self, earlier) -> None:
        # The control is in neither list of the later run, so its item went
        # with it. Nothing was fixed: it read as one more remediation closed.
        later = revised(earlier)
        later["controls"] = [c for c in later["controls"] if c["control_id"] != "CC9.9"]
        later["remediation"]["items"] = [
            i for i in later["remediation"]["items"] if i["control_id"] != "CC9.9"
        ]
        result = compare(earlier, later)
        assert result.remediation_closed == []
        assert [i["control_id"] for i in result.remediation_control_gone] == ["CC9.9"]
        assert result.remediation_set_aside == []
        assert result.to_dict()["remediation"]["control_gone"] == result.remediation_control_gone
        assert any("not counted as closed" in c for c in result.caveats)
        assert "0 remediation item(s) closed" in result.headline()

    def test_an_item_whose_control_joined_the_assessment_is_not_opened(self, earlier) -> None:
        # The control is not in the earlier run at all, so its item could not
        # have been there either. Nothing says the gap is new: it read as one
        # more item newly raised.
        first = json.loads(json.dumps(earlier))
        first["controls"] = [c for c in first["controls"] if c["control_id"] != "CC9.9"]
        first["remediation"]["items"] = [
            i for i in first["remediation"]["items"] if i["control_id"] != "CC9.9"
        ]
        later = revised(earlier)
        assert any(i["control_id"] == "CC9.9" for i in later["remediation"]["items"]), (
            "the fixture must plan an item for CC9.9"
        )
        result = compare(first, later)
        assert result.remediation_opened == []
        assert [i["control_id"] for i in result.remediation_control_new] == ["CC9.9"]
        assert result.to_dict()["remediation"]["control_new"] == result.remediation_control_new
        assert any("not counted as opened" in c for c in result.caveats)
        assert result.headline().endswith(", 0 opened")

    @pytest.mark.parametrize("decided", ["accepted_risk", "not_applicable"])
    def test_an_item_whose_decision_ended_is_not_opened(self, earlier, decided) -> None:
        # The mirror of set-aside. The control sat under an acceptance, or out
        # of scope, so the earlier run planned nothing for it. The acceptance
        # lapsed, or the control came back into scope, and its item returned:
        # the gap was there all along. It read as one more item newly raised.
        first = revised(earlier, assessment_id="acme-q2", **{"CC9.9": decided})
        first["started_at"] = "2026-06-01T00:00:00+00:00"
        first["remediation"]["items"] = [
            i for i in first["remediation"]["items"] if i["control_id"] != "CC9.9"
        ]
        later = revised(earlier)
        assert any(i["control_id"] == "CC9.9" for i in later["remediation"]["items"]), (
            "the fixture must plan an item for CC9.9"
        )
        result = compare(first, later)
        assert result.remediation_opened == []
        assert [i["control_id"] for i in result.remediation_resumed] == ["CC9.9"]
        assert result.to_dict()["remediation"]["resumed"] == result.remediation_resumed
        assert any("1 remediation item(s) returned" in c for c in result.caveats)
        assert ", 0 opened" in result.headline()

    def test_a_lapsed_acceptance_opens_nothing_with_the_real_engine(
        self, tiny_framework, evidence
    ) -> None:
        # The same case end to end: the acceptance is in force for the first
        # run and gone by the second, and the engine plans the gap again.
        acceptance = RiskException(
            exception_id="ex-CC9.9",
            tenant_id="acme",
            control_id="CC9.9",
            justification="Compensating monitoring is in place until the next release.",
            requested_by="alice",
            requested_at=NOW,
            expires_at=NOW + timedelta(days=20),
            compensating_controls=["Daily review of privileged activity"],
        )
        acceptance.submit()
        acceptance.approve("bob", at=NOW)
        runs = [
            json.loads(
                json.dumps(
                    run_assessment(
                        tenant_id="acme",
                        framework=tiny_framework,
                        evidence=evidence,
                        group="deep",
                        exceptions=[acceptance],
                        as_of=as_of,
                        assessment_id=assessment_id,
                    ).to_dict()
                )
            )
            for assessment_id, as_of in (("acme-q3", NOW), ("acme-q4", NOW + timedelta(days=30)))
        ]
        result = compare(*runs)
        assert [c.control_id for c in result.acceptance_lapsed] == ["CC9.9"]
        assert result.remediation_opened == []
        assert [i["control_id"] for i in result.remediation_resumed] == ["CC9.9"]

    def test_a_new_item_is_opened(self, earlier) -> None:
        later = revised(earlier)
        later["remediation"]["items"].append(
            {
                "item_id": "rm-new",
                "control_id": "CC9.9",
                "control_name": "Zeppelin Mooring",
                "severity": "high",
                "owner": "",
                "due_date": "",
            }
        )
        result = compare(earlier, later)
        assert [i["item_id"] for i in result.remediation_opened] == ["rm-new"]

    def test_items_present_in_both_are_counted_as_still_open(self, earlier) -> None:
        result = compare(earlier, revised(earlier))
        assert result.to_dict()["remediation"]["still_open"] == len(earlier["remediation"]["items"])

    def test_a_closed_item_carries_enough_to_be_recognised(self, earlier) -> None:
        later = revised(earlier)
        later["remediation"]["items"].pop(0)
        closed = compare(earlier, later).remediation_closed[0]
        assert set(closed) == {
            "item_id",
            "control_id",
            "control_name",
            "severity",
            "owner",
            "due_date",
        }


class TestTheHeadline:
    def test_it_names_the_direction_and_the_counts(self, earlier) -> None:
        later = revised(earlier, **{"CC9.9": "compliant"})
        later["summary"]["readiness_score"] = 80.0
        headline = compare(earlier, later).headline()
        assert "up" in headline
        assert "1 improved" in headline

    def test_a_fall_reads_as_down(self, earlier) -> None:
        later = revised(earlier)
        later["summary"]["readiness_score"] = 10.0
        assert "down" in compare(earlier, later).headline()

    def test_no_movement_reads_as_level(self, earlier) -> None:
        assert "level" in compare(earlier, revised(earlier)).headline()

    def test_a_control_scoped_back_in_explains_the_fall(self, tiny_framework, evidence) -> None:
        # Two real runs: CC9.9 excluded from scope, then the exclusion withdrawn.
        # The gap rejoins the denominator and readiness falls, and the headline
        # read "down 25.9, 0 improved, 0 regressed, 0 remediation item(s)
        # closed, 0 opened" — a fall with nothing named as its cause.
        exclusion = ScopeExclusion(
            control_id="CC9.9",
            justification="No zeppelins are operated from this site.",
            approved_by="bob",
            approved_at=NOW,
        )
        runs = [
            json.loads(
                json.dumps(
                    run_assessment(
                        tenant_id="acme",
                        framework=tiny_framework,
                        evidence=evidence,
                        group="deep",
                        policy=policy,
                        as_of=as_of,
                        assessment_id=assessment_id,
                    ).to_dict()
                )
            )
            for assessment_id, as_of, policy in (
                ("acme-q3", NOW, TenantPolicy(tenant_id="acme", exclusions=[exclusion])),
                ("acme-q4", NOW + timedelta(days=30), TenantPolicy(tenant_id="acme")),
            )
        ]
        result = compare(*runs)
        assert [c.control_id for c in result.scoped_in] == ["CC9.9"]
        assert result.readiness_change < 0
        headline = result.headline()
        assert "down" in headline
        assert headline.endswith("0 scoped out, 1 scoped back in")

    def test_a_pair_with_no_decision_names_none(self, earlier) -> None:
        later = revised(earlier, **{"CC9.9": "compliant"})
        assert "scoped" not in compare(earlier, later).headline()

    @pytest.mark.parametrize("field, value", [("id", "hipaa"), ("version", "2.0")])
    def test_a_pair_that_is_not_comparable_reports_no_movement(
        self, earlier, field: str, value: str
    ) -> None:
        # The report section states the reason and shows no numbers; the
        # headline printed "readiness 40.0% → 80.0% (up 40.0), 1 improved"
        # for the same pair, the figure that looks like a trend and is not.
        later = revised(earlier, **{"CC9.9": "compliant"})
        later["framework"][field] = value
        later["summary"]["readiness_score"] = 80.0
        headline = compare(earlier, later).headline()
        assert headline.startswith("not comparable with acme-q3")
        for movement in ("→", "up", "down", "level", "improved", "regressed", "closed", "opened"):
            assert movement not in headline


class TestTheCompareCommand:
    def _write(self, path: Path, document: dict[str, Any]) -> Path:
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_two_files_compare(self, earlier, tmp_path: Path, capsys) -> None:
        a = self._write(tmp_path / "q3.json", earlier)
        b = self._write(tmp_path / "q4.json", revised(earlier, **{"CC9.9": "compliant"}))
        assert main(["compare", "--from", str(a), "--to", str(b)]) == 0
        reported = json.loads(capsys.readouterr().out)
        assert [c["control_id"] for c in reported["controls"]["improved"]] == ["CC9.9"]

    def test_a_tenant_s_two_most_recent_compare_from_the_store(
        self, earlier, tmp_path: Path, capsys
    ) -> None:
        from ironclad.store import FileResultStore

        store = FileResultStore(tmp_path / "nas")
        store.put_assessment(earlier)
        store.put_assessment(revised(earlier, **{"CC9.9": "compliant"}))
        capsys.readouterr()

        assert main(["compare", "--client", "acme", "--store", str(tmp_path / "nas")]) == 0
        reported = json.loads(capsys.readouterr().out)
        assert reported["earlier"]["assessment_id"] == "acme-q3"
        assert reported["later"]["assessment_id"] == "acme-q4"

    def test_the_store_pair_is_two_runs_of_one_framework(
        self, earlier, tmp_path: Path, capsys
    ) -> None:
        # A tenant assessed against two frameworks has them interleaved in the
        # store. The two most recent were a HIPAA run and a test-fw run, and
        # the command compared those: "not comparable", while two test-fw runs
        # sat in the store. `store latest` already matches the framework.
        from ironclad.store import FileResultStore

        store = FileResultStore(tmp_path / "nas")
        store.put_assessment(earlier)
        other = revised(earlier, "acme-hipaa")
        other["started_at"] = "2026-11-01T00:00:00+00:00"
        other["framework"]["id"] = "hipaa"
        store.put_assessment(other)
        store.put_assessment(revised(earlier, **{"CC9.9": "compliant"}))
        capsys.readouterr()

        assert main(["compare", "--client", "acme", "--store", str(tmp_path / "nas")]) == 0
        reported = json.loads(capsys.readouterr().out)
        assert reported["earlier"]["assessment_id"] == "acme-q3"
        assert reported["later"]["assessment_id"] == "acme-q4"
        assert reported["comparable"] is True
        assert [c["control_id"] for c in reported["controls"]["improved"]] == ["CC9.9"]

    def test_one_run_of_the_latest_framework_is_not_a_trend(
        self, earlier, tmp_path: Path, capsys
    ) -> None:
        from ironclad.store import FileResultStore

        store = FileResultStore(tmp_path / "nas")
        store.put_assessment(earlier)
        other = revised(earlier, "acme-hipaa")
        other["framework"]["id"] = "hipaa"
        store.put_assessment(other)
        capsys.readouterr()

        code = main(["compare", "--client", "acme", "--store", str(tmp_path / "nas")])
        assert code == 2
        err = capsys.readouterr().err
        assert "1 stored hipaa assessment(s)" in err
        assert "two are needed" in err

    def test_one_assessment_is_not_a_trend(self, earlier, tmp_path: Path, capsys) -> None:
        from ironclad.store import FileResultStore

        FileResultStore(tmp_path / "nas").put_assessment(earlier)
        code = main(["compare", "--client", "acme", "--store", str(tmp_path / "nas")])
        assert code == 2
        assert "two are needed" in capsys.readouterr().err

    def test_neither_form_of_input_is_refused(self, capsys) -> None:
        assert main(["compare"]) == 2
        assert "--from and --to, or --client" in capsys.readouterr().err

    def test_the_caveats_reach_the_operator(self, earlier, tmp_path: Path, capsys) -> None:
        later = revised(earlier)
        later["framework"]["version"] = "2.0"
        a = self._write(tmp_path / "q3.json", earlier)
        b = self._write(tmp_path / "q4.json", later)
        main(["compare", "--from", str(a), "--to", str(b)])
        assert "caveat:" in capsys.readouterr().err

    @pytest.mark.parametrize("field, value", [("id", "hipaa"), ("version", "2.0")])
    def test_the_record_of_a_pair_not_comparable_carries_no_trend(
        self, earlier, tmp_path: Path, capsys, field: str, value: str
    ) -> None:
        # The headline on stderr said "no readiness change, control movement or
        # remediation counts are reported"; the JSON on stdout reported them:
        # "change": 25.9 and CC9.9 under "improved", for a pair across versions.
        later = revised(earlier, **{"CC9.9": "compliant"})
        later["framework"][field] = value
        later["summary"]["readiness_score"] = 80.0
        a = self._write(tmp_path / "q3.json", earlier)
        b = self._write(tmp_path / "q4.json", later)
        assert main(["compare", "--from", str(a), "--to", str(b)]) == 0
        reported = json.loads(capsys.readouterr().out)
        assert reported["comparable"] is False
        assert reported["not_comparable_because"]
        assert reported["readiness"]["change"] is None
        assert reported["readiness"]["after"] == 80.0
        # Null, not empty: an empty list would say nothing moved, which is a
        # claim about the pair as much as "1 improved" is.
        assert reported["controls"] is None
        assert reported["remediation"] is None
        assert reported["caveats"]

    def test_the_record_of_a_comparable_pair_names_no_reason(
        self, earlier, tmp_path: Path, capsys
    ) -> None:
        a = self._write(tmp_path / "q3.json", earlier)
        b = self._write(tmp_path / "q4.json", revised(earlier, **{"CC9.9": "compliant"}))
        assert main(["compare", "--from", str(a), "--to", str(b)]) == 0
        reported = json.loads(capsys.readouterr().out)
        assert reported["not_comparable_because"] == ""
        assert reported["readiness"]["change"] is not None

    def test_the_report_command_prints_no_trend_across_frameworks(
        self, earlier, tmp_path: Path, capsys
    ) -> None:
        # The report it writes shows no numbers for this pair; the line it
        # printed to the operator showed the movement anyway (§16.7).
        other = revised(earlier)
        other["framework"]["id"] = "hipaa"
        a = self._write(tmp_path / "q3.json", other)
        b = self._write(tmp_path / "q4.json", revised(earlier, "acme-q5"))
        out = tmp_path / "report.html"
        code = main(["report", "--input", str(b), "--compare-to", str(a), "--out", str(out)])
        assert code == 0
        err = capsys.readouterr().err
        assert "not comparable with acme-q4" in err
        assert "→" not in err

    def test_the_report_command_prints_the_caveats_beside_the_headline(
        self, earlier, tiny_framework, evidence, tmp_path: Path, capsys
    ) -> None:
        # Both pipelines run `report --compare-to`. After a deep run, a quick
        # one printed "0 remediation item(s) closed, 0 opened" and nothing
        # else: the reason every earlier item had left the plan was only in
        # the HTML. `ironclad compare` printed it; this command did not.
        quick = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="quick",
            as_of=NOW,
            assessment_id="acme-q4",
        )
        later = json.loads(json.dumps(quick.to_dict()))
        later["started_at"] = "2026-12-01T00:00:00+00:00"
        assert earlier["remediation"]["items"], "the fixture must plan something"
        a = self._write(tmp_path / "q3.json", earlier)
        b = self._write(tmp_path / "q4.json", later)
        out = tmp_path / "report.html"
        code = main(["report", "--input", str(b), "--compare-to", str(a), "--out", str(out)])
        assert code == 0
        err = capsys.readouterr().err
        assert "0 remediation item(s) closed" in err
        assert "caveat:" in err
        assert "did not run remediation planning" in err
        assert "not counted as closed" in err

    def test_the_report_command_prints_no_caveat_for_a_clean_pair(
        self, earlier, tmp_path: Path, capsys
    ) -> None:
        a = self._write(tmp_path / "q3.json", earlier)
        b = self._write(tmp_path / "q4.json", revised(earlier, **{"CC9.9": "compliant"}))
        out = tmp_path / "report.html"
        assert main(["report", "--input", str(b), "--compare-to", str(a), "--out", str(out)]) == 0
        assert "caveat:" not in capsys.readouterr().err

    def test_a_record_compared_with_itself_is_refused_and_no_report_written(
        self, earlier, tmp_path: Path, capsys
    ) -> None:
        # The report gained a "Since the last assessment" section measuring
        # the run against itself: nothing moved, which nothing had claimed.
        a = self._write(tmp_path / "q3.json", earlier)
        b = self._write(tmp_path / "copy.json", earlier)
        assert main(["compare", "--from", str(a), "--to", str(b)]) == 2
        assert "compared with itself" in capsys.readouterr().err
        out = tmp_path / "report.html"
        code = main(["report", "--input", str(a), "--compare-to", str(b), "--out", str(out)])
        assert code == 2
        assert "compared with itself" in capsys.readouterr().err
        assert not out.exists()


class TestTheTrendReachesTheClient:
    """The comparison existed as JSON and never reached the deliverable.

    At a second assessment the client's first question is whether the work they
    did in between showed up, and the answer was available only to whoever ran
    the CLI. It is a section in the report now — high in the document, because
    an answer buried under thirty control rows is an answer nobody reads.

    What matters here is that the honesty rules survive the trip to the page. A
    scope change that reads as an improvement in a JSON blob nobody opens is a
    latent problem; the same thing in a client's report is a wrong statement
    about their compliance position.
    """

    @staticmethod
    def _rendered(earlier: dict, later: dict) -> str:
        from ironclad.cli import _StoredResult
        from ironclad.report.render import render_html

        return render_html(_StoredResult(later), "Acme Corp", comparison=compare(earlier, later))

    def test_the_section_is_absent_without_a_comparison(self, earlier) -> None:
        from ironclad.cli import _StoredResult
        from ironclad.report.render import render_html

        html = render_html(_StoredResult(earlier), "Acme Corp")
        assert "Since the last assessment" not in html

    def test_it_names_the_movement_and_the_earlier_assessment(self, earlier) -> None:
        later = revised(earlier, **{"CC9.9": "compliant"})
        later["summary"]["readiness_score"] = 80.0
        html = self._rendered(earlier, later)
        assert "Since the last assessment" in html
        assert "acme-q3" in html
        assert "Readiness change" in html

    def test_an_improvement_names_the_control_and_both_ends(self, earlier) -> None:
        later = revised(earlier, **{"CC9.9": "compliant"})
        html = self._rendered(earlier, later)
        assert "CC9.9" in html
        assert "Improved (1)" in html

    def test_a_regression_is_shown_as_one(self, earlier) -> None:
        later = revised(earlier, **{"CC6.1": "gap"})
        html = self._rendered(earlier, later)
        assert "Regressed (1)" in html
        assert "CC6.1" in html

    def test_a_scope_change_is_not_presented_as_an_improvement(self, earlier) -> None:
        # The rule that matters most on a client-facing page.
        later = revised(earlier, **{"CC9.9": "not_applicable"})
        html = self._rendered(earlier, later)
        assert "Improved" not in html
        assert "Scope changed" in html
        assert "leaves the readiness denominator" in html

    def test_each_decision_is_credited_only_with_the_items_it_set_aside(self, earlier) -> None:
        # One gap accepted, one scoped out, both items gone from the plan. The
        # acceptance callout said "the 2 remediation item(s) it set aside", one
        # of them set aside by the exclusion, and the scope callout said none.
        planned = sorted({i["control_id"] for i in earlier["remediation"]["items"]})
        assert len(planned) >= 2, "the fixture must plan items for two controls"
        accepted, excluded = planned[0], planned[1]
        later = revised(earlier, **{accepted: "accepted_risk", excluded: "not_applicable"})
        later["remediation"]["items"] = [
            i for i in later["remediation"]["items"] if i["control_id"] not in (accepted, excluded)
        ]
        result = compare(earlier, later)
        assert sorted(i["control_id"] for i in result.remediation_set_aside) == [
            accepted,
            excluded,
        ]
        html = " ".join(self._rendered(earlier, later).split())
        assert "the 1 remediation item(s) it set aside are not counted as closed" in html
        assert "the 1 remediation item(s) those exclusions set aside" in html
        assert "the 2 remediation item(s)" not in html

    def test_an_incomparable_pair_says_so_and_shows_no_figure(self, earlier) -> None:
        # A movement figure across two framework versions is a number that looks
        # like a trend and is not.
        later = revised(earlier)
        later["framework"]["version"] = "2.0"
        later["summary"]["readiness_score"] = 99.0
        html = self._rendered(earlier, later)
        assert "Since the last assessment" in html
        assert "Read with care" in html
        assert "Readiness change" not in html

    def test_client_text_in_a_comparison_cannot_inject_markup(self, earlier) -> None:
        later = revised(earlier, **{"CC9.9": "compliant"})
        for control in later["controls"]:
            if control["control_id"] == "CC9.9":
                control["control_name"] = "<script>alert(1)</script>"
        html = self._rendered(earlier, later)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_the_section_names_no_underlying_tool(self, earlier) -> None:
        later = revised(earlier, **{"CC9.9": "compliant"})
        html = self._rendered(earlier, later).lower()
        for name in ("zap", "nuclei", "wazuh", "prowler", "openai", "anthropic", "groq"):
            assert name not in html

    def test_the_report_command_takes_a_previous_assessment(
        self, earlier, tmp_path: Path, capsys
    ) -> None:
        previous = tmp_path / "q3.json"
        previous.write_text(json.dumps(earlier), encoding="utf-8")
        current = tmp_path / "q4.json"
        current.write_text(json.dumps(revised(earlier, **{"CC9.9": "compliant"})), encoding="utf-8")
        out = tmp_path / "report.html"
        code = main(
            [
                "report",
                "--input",
                str(current),
                "--compare-to",
                str(previous),
                "--out",
                str(out),
            ]
        )
        assert code == 0
        assert "Since the last assessment" in out.read_text(encoding="utf-8")
        assert "improved" in capsys.readouterr().err
