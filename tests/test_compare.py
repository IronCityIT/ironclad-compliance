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
from pathlib import Path
from typing import Any

import pytest

from ironclad.cli import main
from ironclad.compare import (
    IMPROVED,
    MOVEMENT_RANK,
    REGRESSED,
    SCOPED_IN,
    SCOPED_OUT,
    UNCHANGED,
    compare,
)
from ironclad.engine import run_assessment
from ironclad.model.assessment import ControlStatus
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
        moved = {c.control_id: c.movement for c in result.unchanged}
        assert moved["CC1.1"] == UNCHANGED

    def test_every_change_records_both_ends(self, earlier) -> None:
        later = revised(earlier, **{"CC9.9": "compliant"})
        change = compare(earlier, later).improved[0]
        assert change.was == "gap"
        assert change.now == "compliant"
        assert change.movement == IMPROVED
        assert change.control_name

    def test_an_unchanged_control_is_counted_not_listed(self, earlier) -> None:
        result = compare(earlier, earlier)
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

    def test_an_identical_pair_carries_no_caveat(self, earlier) -> None:
        assert compare(earlier, earlier).caveats == []
        assert compare(earlier, earlier).comparable is True


class TestRemediationMovement:
    def test_an_item_that_went_away_is_closed(self, earlier) -> None:
        later = revised(earlier)
        dropped = later["remediation"]["items"].pop(0)
        result = compare(earlier, later)
        assert [i["item_id"] for i in result.remediation_closed] == [dropped["item_id"]]
        assert result.remediation_opened == []

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
        result = compare(earlier, earlier)
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
        assert "level" in compare(earlier, earlier).headline()


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
