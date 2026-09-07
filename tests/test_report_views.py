"""What each assessment type issues.

`full`, `gap-only` and `readiness` were offered on every surface, validated on
the way in, stored on the record — and then produced byte-identical output. The
rules that matter here are the ones that keep an abridged deliverable honest:
the assessment behind it is always complete, and the report says what it left
out.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ironclad.api.schemas import ASSESSMENT_TYPES as API_TYPES
from ironclad.api.schemas import AssessmentRequest, validate_assessment_request
from ironclad.cli import build_parser, main
from ironclad.engine import run_assessment
from ironclad.model.assessment import ControlStatus
from ironclad.policy import policy_from_document
from ironclad.report.export import export_audit_package, export_control_register_csv
from ironclad.report.render import render_html
from ironclad.report.views import (
    ASSESSMENT_TYPES,
    DEFAULT_VIEW,
    OUTSTANDING,
    VIEWS,
    catalog,
    view_for,
)
from tests.conftest import NOW

REPO_ROOT = Path(__file__).resolve().parents[1]


def assessed(framework, evidence, assessment_type: str, policy=None):
    return run_assessment(
        tenant_id="acme",
        framework=framework,
        evidence=evidence,
        policy=policy,
        group="deep",
        as_of=NOW,
        assessment_type=assessment_type,
        assessment_id=f"acme-{assessment_type}",
    )


def register_of(html: str) -> str:
    """Just the control register table — the remediation table uses the same row
    markup, so counting control cells across the whole document counts twice."""
    start = html.find("<h2>Control register</h2>")
    if start < 0:
        return ""
    return html[start : html.index("</table>", start)]


def registered(html: str) -> list[str]:
    return re.findall(r'<td class="cid">([^<]+)</td>', register_of(html))


def text_of(html: str) -> str:
    """The rendered document with its markup stripped, as a reader sees it."""
    body = re.sub(r"(?s)<(script|style).*?</\1>", " ", html)
    return re.sub(r"<[^>]+>", " ", body)


@pytest.fixture
def accepted_policy():
    """CC1.1 accepted as a risk, CC9.9 scoped out — the two abridging edge cases."""
    return policy_from_document(
        {
            "policy_version": "1.0",
            "tenant_id": "acme",
            "scope_exclusions": [
                {
                    "control_id": "CC9.9",
                    "justification": "The organisation operates no facility of its own.",
                    "approved_by": "j.reyes",
                    "approved_at": "2026-03-01T00:00:00+00:00",
                }
            ],
            "exceptions": [
                {
                    "control_id": "CC1.1",
                    "justification": "Remediation is scheduled for the next release train.",
                    "requested_by": "alice",
                    "approved_by": "bob",
                    "approved_at": "2026-08-15T00:00:00+00:00",
                    "expires_at": "2026-11-15T00:00:00+00:00",
                    "compensating_controls": ["Monthly manual review"],
                    "status": "approved",
                }
            ],
            "owners": {},
        }
    )


class TestOneListOfAssessmentTypes:
    """Every surface that offers a type must offer one the engine can render."""

    def test_the_api_validates_against_the_views(self) -> None:
        assert API_TYPES == ASSESSMENT_TYPES
        assert set(ASSESSMENT_TYPES) == set(VIEWS)

    @pytest.mark.parametrize("name", ASSESSMENT_TYPES)
    def test_the_cli_accepts_every_view(self, name: str, tmp_path: Path) -> None:
        args = build_parser().parse_args(
            [
                "assess",
                "--client",
                "acme",
                "--framework",
                "soc2",
                "--evidence-dir",
                str(tmp_path),
                "--assessment-type",
                name,
                "--out",
                str(tmp_path / "out"),
            ]
        )
        assert args.assessment_type == name

    def test_the_cli_refuses_a_type_with_no_view(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exit_info:
            build_parser().parse_args(
                [
                    "assess",
                    "--client",
                    "acme",
                    "--framework",
                    "soc2",
                    "--evidence-dir",
                    str(tmp_path),
                    "--assessment-type",
                    "summary",
                    "--out",
                    str(tmp_path / "out"),
                ]
            )
        assert exit_info.value.code == 2

    def test_the_dashboard_catalog_offers_exactly_the_views(self) -> None:
        document = json.loads(
            (REPO_ROOT / "dashboard" / "public" / "catalog.json").read_text(encoding="utf-8")
        )
        assert [t["name"] for t in document["assessment_types"]] == list(ASSESSMENT_TYPES)
        # The dropdown labels come from the engine, not from the dashboard.
        assert [t["title"] for t in document["assessment_types"]] == [
            VIEWS[name].title for name in ASSESSMENT_TYPES
        ]

    def test_the_trigger_function_accepts_exactly_the_views(self) -> None:
        # trigger.js cannot import Python, so it repeats the set. This is the
        # test that stops the two drifting: a type the dashboard offers but the
        # function rejects silently becomes a full report.
        source = (REPO_ROOT / "functions" / "trigger.js").read_text(encoding="utf-8")
        declared = re.search(r"TYPES\s*=\s*new Set\(\[(.*?)\]\)", source, re.S)
        assert declared is not None, "functions/trigger.js no longer declares a TYPES set"
        assert set(re.findall(r'"([^"]+)"', declared.group(1))) == set(ASSESSMENT_TYPES)

    def test_an_offered_type_is_a_valid_request(self) -> None:
        for name in ASSESSMENT_TYPES:
            request = AssessmentRequest(tenant_id="acme", framework="soc2", assessment_type=name)
            assert validate_assessment_request(request) == []

    def test_the_catalog_describes_every_view(self) -> None:
        entries = catalog()
        assert [e["name"] for e in entries] == list(ASSESSMENT_TYPES)
        for entry in entries:
            assert entry["title"] and entry["description"]


class TestViewSelection:
    def test_an_unknown_type_gets_the_full_report(self) -> None:
        # Never abridge on a value nobody recognised.
        for unknown in ("", "  ", "summary", "gap only", None):
            assert view_for(unknown).name == DEFAULT_VIEW  # type: ignore[arg-type]

    def test_a_type_is_matched_case_and_space_insensitively(self) -> None:
        assert view_for("  Gap-Only ").name == "gap-only"

    def test_the_default_view_hides_nothing(self) -> None:
        view = VIEWS[DEFAULT_VIEW]
        assert view.show_register and view.show_remediation and view.show_crosswalk
        assert view.register_statuses is None
        assert view.omission_note == ""

    def test_every_abridged_view_states_its_omission(self) -> None:
        for view in VIEWS.values():
            abridged = not view.show_register or view.register_statuses is not None
            assert bool(view.omission_note) == abridged, f"{view.name} omits without saying so"


class TestTheAssessmentIsAlwaysComplete:
    """A view shapes the deliverable. It must never change what was judged."""

    def test_the_readiness_score_does_not_depend_on_the_view(
        self, tiny_framework, evidence
    ) -> None:
        scores = {
            name: assessed(tiny_framework, evidence, name).assessment.summary.readiness_score
            for name in ASSESSMENT_TYPES
        }
        assert len(set(scores.values())) == 1, scores

    def test_every_control_is_stored_whatever_the_view(self, tiny_framework, evidence) -> None:
        for name in ASSESSMENT_TYPES:
            result = assessed(tiny_framework, evidence, name)
            assert len(result.assessment.controls) == len(tiny_framework.controls)
            assert len(json.loads(json.dumps(result.to_dict()))["controls"]) == len(
                tiny_framework.controls
            )

    def test_the_stored_record_keeps_the_type_it_was_run_as(self, tiny_framework, evidence) -> None:
        result = assessed(tiny_framework, evidence, "gap-only")
        assert result.assessment.to_dict()["assessment_type"] == "gap-only"


class TestTheGapAnalysis:
    def test_it_lists_only_the_outstanding_controls(self, tiny_framework, evidence) -> None:
        result = assessed(tiny_framework, evidence, "gap-only")
        html = render_html(result, "Acme Corp")
        outstanding = [c for c in result.assessment.controls if c.status in OUTSTANDING]
        met = [c for c in result.assessment.controls if c.status not in OUTSTANDING]
        assert outstanding and met, "the fixture must produce both, or this proves nothing"
        assert sorted(registered(html)) == sorted(c.control_id for c in outstanding)

    def test_it_says_what_it_left_out(self, tiny_framework, evidence) -> None:
        reader_sees = text_of(render_html(assessed(tiny_framework, evidence, "gap-only")))
        assert "gap analysis" in reader_sees
        assert "not listed individually" in reader_sees

    def test_it_still_counts_every_control_in_the_summary(self, tiny_framework, evidence) -> None:
        result = assessed(tiny_framework, evidence, "gap-only")
        html = render_html(result)
        assert f"{result.assessment.summary.total_controls} controls were assessed" in html

    def test_an_accepted_risk_is_listed_as_outstanding(
        self, tiny_framework, evidence, accepted_policy
    ) -> None:
        # An accepted risk is still not met. Dropping it from the gap analysis
        # would hide the one control somebody made a decision about.
        result = assessed(tiny_framework, evidence, "gap-only", policy=accepted_policy)
        accepted = [
            c for c in result.assessment.controls if c.status == ControlStatus.ACCEPTED_RISK
        ]
        assert accepted, "the policy fixture no longer produces an accepted risk"
        assert set(c.control_id for c in accepted) <= set(registered(render_html(result)))

    def test_a_scoped_out_control_is_not_listed(
        self, tiny_framework, evidence, accepted_policy
    ) -> None:
        result = assessed(tiny_framework, evidence, "gap-only", policy=accepted_policy)
        excluded = [
            c for c in result.assessment.controls if c.status == ControlStatus.NOT_APPLICABLE
        ]
        assert excluded, "the policy fixture no longer scopes a control out"
        assert excluded[0].control_id not in registered(render_html(result))

    def test_it_keeps_the_remediation_plan(self, tiny_framework, evidence) -> None:
        html = render_html(assessed(tiny_framework, evidence, "gap-only"))
        assert "Remediation plan" in html


class TestTheReadinessSummary:
    def test_it_has_no_control_register(self, tiny_framework, evidence) -> None:
        html = render_html(assessed(tiny_framework, evidence, "readiness"))
        assert "Control register" not in html
        assert registered(html) == []

    def test_it_says_the_register_is_missing(self, tiny_framework, evidence) -> None:
        reader_sees = text_of(render_html(assessed(tiny_framework, evidence, "readiness")))
        assert "readiness summary" in reader_sees
        assert "without the control-by-control register" in reader_sees

    def test_it_still_carries_the_score_and_the_plan(self, tiny_framework, evidence) -> None:
        result = assessed(tiny_framework, evidence, "readiness")
        html = render_html(result)
        assert str(result.assessment.summary.readiness_score) in html
        assert "Remediation plan" in html


class TestTheFullReport:
    def test_it_lists_every_control(self, tiny_framework, evidence) -> None:
        result = assessed(tiny_framework, evidence, "full")
        html = render_html(result)
        assert sorted(registered(html)) == sorted(c.control_id for c in result.assessment.controls)

    def test_it_claims_no_omission(self, tiny_framework, evidence) -> None:
        html = render_html(assessed(tiny_framework, evidence, "full"))
        assert "What this report covers" not in html

    def test_it_titles_itself_as_an_assessment(self, tiny_framework, evidence) -> None:
        html = render_html(assessed(tiny_framework, evidence, "full"))
        assert "Compliance readiness assessment" in html


class TestEveryViewRemainsAReport:
    @pytest.mark.parametrize("name", ASSESSMENT_TYPES)
    def test_it_is_a_complete_document(self, tiny_framework, evidence, name: str) -> None:
        html = render_html(assessed(tiny_framework, evidence, name), "Acme Corp")
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")

    @pytest.mark.parametrize("name", ASSESSMENT_TYPES)
    def test_it_names_the_client_and_the_framework(
        self, tiny_framework, evidence, name: str
    ) -> None:
        html = render_html(assessed(tiny_framework, evidence, name), "Acme Corp")
        assert "Acme Corp" in html and "Test Framework" in html

    @pytest.mark.parametrize("name", ASSESSMENT_TYPES)
    def test_it_carries_the_view_title(self, tiny_framework, evidence, name: str) -> None:
        html = render_html(assessed(tiny_framework, evidence, name))
        assert VIEWS[name].title in html

    @pytest.mark.parametrize("name", ASSESSMENT_TYPES)
    def test_it_names_the_owner_of_each_remediation_item(
        self, tiny_framework, evidence, name: str
    ) -> None:
        result = assessed(tiny_framework, evidence, name)
        assert result.plan, "the fixture must produce remediation items"
        assert "<th>Owner</th>" in render_html(result)


class TestReIssuingAStoredAssessment:
    def test_the_report_command_follows_the_stored_type(
        self, tiny_framework, evidence, tmp_path: Path
    ) -> None:
        stored = tmp_path / "assessment.json"
        stored.write_text(
            json.dumps(assessed(tiny_framework, evidence, "readiness").to_dict()),
            encoding="utf-8",
        )
        out = tmp_path / "report.html"
        assert main(["report", "--input", str(stored), "--out", str(out)]) == 0
        assert "Control register" not in out.read_text(encoding="utf-8")

    def test_a_view_override_re_issues_without_re_running(
        self, tiny_framework, evidence, tmp_path: Path
    ) -> None:
        # The same stored record, issued as a different deliverable.
        stored = tmp_path / "assessment.json"
        stored.write_text(
            json.dumps(assessed(tiny_framework, evidence, "full").to_dict()), encoding="utf-8"
        )
        out = tmp_path / "gaps.html"
        code = main(["report", "--input", str(stored), "--out", str(out), "--view", "gap-only"])
        assert code == 0
        assert "Compliance gap analysis" in out.read_text(encoding="utf-8")


class TestTheAuditorPackageIsNeverAbridged:
    def test_the_register_csv_carries_every_control(
        self, tiny_framework, evidence, tmp_path: Path
    ) -> None:
        result = assessed(tiny_framework, evidence, "gap-only")
        rows = export_control_register_csv(result, evidence).strip().splitlines()
        assert len(rows) == len(result.assessment.controls) + 1

    def test_the_package_records_the_deliverable_it_issued(
        self, tiny_framework, evidence, tmp_path: Path
    ) -> None:
        result = assessed(tiny_framework, evidence, "gap-only")
        export_audit_package(result, evidence, tmp_path / "pkg")
        manifest = json.loads((tmp_path / "pkg" / "package.json").read_text(encoding="utf-8"))
        assert manifest["assessment_type"] == "gap-only"
        assert manifest["report_view"]["name"] == "gap-only"

    def test_the_package_report_is_the_deliverable_as_issued(
        self, tiny_framework, evidence, tmp_path: Path
    ) -> None:
        result = assessed(tiny_framework, evidence, "readiness")
        export_audit_package(result, evidence, tmp_path / "pkg")
        report = (tmp_path / "pkg" / "report.html").read_text(encoding="utf-8")
        assert "Compliance readiness summary" in report
        assert "Control register" not in report

    def test_the_package_readme_warns_that_the_report_may_be_abridged(
        self, tiny_framework, evidence, tmp_path: Path
    ) -> None:
        result = assessed(tiny_framework, evidence, "gap-only")
        export_audit_package(result, evidence, tmp_path / "pkg")
        readme = (tmp_path / "pkg" / "README.txt").read_text(encoding="utf-8")
        assert "THE CSV FILES ARE COMPLETE" in readme
        assert "gap-only" in readme


class TestTheGeneratedCatalogIsCommitted:
    def test_the_committed_catalog_is_current(self) -> None:
        # build_catalog.py now derives the assessment types from the views, so a
        # new view that nobody regenerated for would leave the dashboard stale.
        completed = subprocess.run(
            [sys.executable, "tools/build_catalog.py", "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
