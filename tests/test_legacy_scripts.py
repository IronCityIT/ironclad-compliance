"""The scripts the original pipeline called.

`scripts/*.py` predate the package. Their logic moved into `ironclad/`, the
files stayed as wrappers, and `STATUS.md` promises that anything which called
them before still works. That promise had nothing behind it: none of them had a
test, and one of them had quietly stopped agreeing with the engine.

`assess_controls.py` had no `--policy` flag and did not look for a policy beside
the evidence, so a client's scope exclusions and risk acceptances were silently
not applied. A control the client had formally accepted came back as a gap, and
the only way to notice was to compare two entry points by hand.

So what is tested here is not that the wrappers run. It is that they agree with
`ironclad`, because a second entry point that disagrees is worse than no second
entry point.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from ironclad.cli import main as ironclad_main
from ironclad.ids import iso, utc_now

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "examples" / "evidence"


def _script(name: str):
    """Load one of `scripts/` by path.

    `scripts/` is a directory of scripts rather than a package, which is what it
    should be — they are invoked as `python scripts/x.py` and nothing imports
    them. Loading by path tests what is actually run instead of changing the
    repository's shape to suit the test.
    """
    import importlib.util

    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assess_controls = _script("assess_controls")
generate_report = _script("generate_report")
check_framework_updates = _script("check_framework_updates")

ACCEPTED_CONTROL = "CC1.4"


def policy_document() -> dict:
    """A live risk acceptance, dated relative to now.

    Relative because the wrapper assesses against the wall clock — there is no
    --as-of to pass — so a fixed date would make this test pass until it
    silently did not. And inside 365 days, because the model refuses an
    acceptance that runs longer: the first version of this fixture asserted ten
    years and was correctly rejected.
    """
    approved = utc_now() - timedelta(days=10)
    return {
        "policy_version": "1.0",
        "tenant_id": "icit-internal",
        "scope_exclusions": [],
        "exceptions": [
            {
                "control_id": ACCEPTED_CONTROL,
                "justification": "Recruitment controls sit with the outsourced HR provider.",
                "requested_by": "alice",
                "approved_by": "bob",
                "requested_at": iso(approved),
                "approved_at": iso(approved),
                "expires_at": iso(approved + timedelta(days=300)),
                "status": "approved",
            }
        ],
        "owners": {},
    }


@pytest.fixture
def evidence_dir(tmp_path: Path) -> Path:
    """The sample evidence, with a tenant policy beside it."""
    directory = tmp_path / "evidence"
    directory.mkdir()
    for source in EVIDENCE.glob("*.txt"):
        (directory / source.name).write_text(source.read_text("utf-8"), "utf-8")
    (directory / "policy.json").write_text(json.dumps(policy_document()), encoding="utf-8")
    return directory


def verdict(document: dict, control_id: str) -> str:
    return next(c["status"] for c in document["controls"] if c["control_id"] == control_id)


class TestTheAssessmentWrapperAgreesWithTheEngine:
    def test_it_honours_a_policy_beside_the_evidence(
        self, evidence_dir: Path, tmp_path: Path
    ) -> None:
        # The regression. Without this the acceptance is ignored and the control
        # reads as a gap, which is a client being told they fail a control they
        # formally accepted.
        output = tmp_path / "wrapper.json"
        code = assess_controls.main(
            [
                "--client-id",
                "icit-internal",
                "--framework",
                "soc2",
                "--evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            ]
        )
        assert code == 0
        assert verdict(json.loads(output.read_text("utf-8")), ACCEPTED_CONTROL) == "accepted_risk"

    def test_it_reaches_the_same_verdicts_as_ironclad_assess(
        self, evidence_dir: Path, tmp_path: Path
    ) -> None:
        # A second entry point that disagrees is worse than no second entry point.
        wrapper_out = tmp_path / "wrapper.json"
        assess_controls.main(
            [
                "--client-id",
                "icit-internal",
                "--framework",
                "soc2",
                "--evidence-dir",
                str(evidence_dir),
                "--group",
                "deep",
                "--output",
                str(wrapper_out),
            ]
        )
        cli_out = tmp_path / "cli"
        ironclad_main(
            [
                "assess",
                "--client",
                "icit-internal",
                "--framework",
                "soc2",
                "--evidence-dir",
                str(evidence_dir),
                "--group",
                "deep",
                "--out",
                str(cli_out),
            ]
        )

        wrapper = json.loads(wrapper_out.read_text("utf-8"))
        cli = json.loads((cli_out / "assessment.json").read_text("utf-8"))

        assert wrapper["summary"]["readiness_score"] == cli["summary"]["readiness_score"]
        assert {c["control_id"]: c["status"] for c in wrapper["controls"]} == {
            c["control_id"]: c["status"] for c in cli["controls"]
        }

    def test_an_explicit_policy_that_is_missing_is_an_error(
        self, evidence_dir: Path, tmp_path: Path, capsys
    ) -> None:
        code = assess_controls.main(
            [
                "--client-id",
                "icit-internal",
                "--framework",
                "soc2",
                "--evidence-dir",
                str(evidence_dir),
                "--policy",
                str(tmp_path / "absent.json"),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )
        assert code == 2
        assert "tenant policy not found" in capsys.readouterr().err

    def test_no_policy_at_all_is_not_an_error(self, tmp_path: Path) -> None:
        # A client with no determinations to make is a legitimate state.
        bare = tmp_path / "bare"
        bare.mkdir()
        for source in EVIDENCE.glob("*.txt"):
            (bare / source.name).write_text(source.read_text("utf-8"), "utf-8")
        output = tmp_path / "out.json"
        assert (
            assess_controls.main(
                [
                    "--client-id",
                    "icit-internal",
                    "--framework",
                    "soc2",
                    "--evidence-dir",
                    str(bare),
                    "--output",
                    str(output),
                ]
            )
            == 0
        )
        assert json.loads(output.read_text("utf-8"))["controls"]

    def test_a_mistyped_assessment_type_is_refused(
        self, evidence_dir: Path, tmp_path: Path
    ) -> None:
        # Unconstrained it accepted anything and the report fell back to the
        # full view, so a typo produced the wrong deliverable in silence.
        with pytest.raises(SystemExit) as exit_info:
            assess_controls.main(
                [
                    "--client-id",
                    "icit-internal",
                    "--framework",
                    "soc2",
                    "--evidence-dir",
                    str(evidence_dir),
                    "--assessment-type",
                    "gaponly",
                    "--output",
                    str(tmp_path / "out.json"),
                ]
            )
        assert exit_info.value.code == 2

    def test_a_missing_evidence_directory_is_refused(self, tmp_path: Path, capsys) -> None:
        code = assess_controls.main(
            [
                "--client-id",
                "acme",
                "--framework",
                "soc2",
                "--evidence-dir",
                str(tmp_path / "absent"),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )
        assert code == 2
        assert "evidence directory not found" in capsys.readouterr().err


class TestTheReportWrapper:
    def _assessment(self, evidence_dir: Path, tmp_path: Path) -> Path:
        output = tmp_path / "assessment.json"
        assess_controls.main(
            [
                "--client-id",
                "icit-internal",
                "--framework",
                "soc2",
                "--evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            ]
        )
        return output

    def test_it_renders_the_same_report_the_cli_does(
        self, evidence_dir: Path, tmp_path: Path
    ) -> None:
        stored = self._assessment(evidence_dir, tmp_path)
        assert (
            generate_report.main(
                [
                    "--input",
                    str(stored),
                    "--output",
                    str(tmp_path / "report.html"),
                    "--client-name",
                    "Iron City Internal",
                ]
            )
            == 0
        )
        wrapper_html = (tmp_path / "report.html").read_text("utf-8")

        ironclad_main(
            [
                "report",
                "--input",
                str(stored),
                "--out",
                str(tmp_path / "cli.html"),
                "--client-name",
                "Iron City Internal",
            ]
        )
        cli_html = (tmp_path / "cli.html").read_text("utf-8")

        # The generated timestamp differs by run; the substance must not.
        assert "Iron City Internal" in wrapper_html
        assert wrapper_html.count('<td class="cid">') == cli_html.count('<td class="cid">')
        assert ("Basis of assessment" in wrapper_html) == ("Basis of assessment" in cli_html)

    def test_a_pdf_request_still_leaves_the_html(self, evidence_dir: Path, tmp_path: Path) -> None:
        # WeasyPrint is optional. A missing PDF toolchain must degrade the
        # deliverable, not lose it.
        stored = self._assessment(evidence_dir, tmp_path)
        assert (
            generate_report.main(["--input", str(stored), "--output", str(tmp_path / "report.pdf")])
            == 0
        )
        assert (tmp_path / "report.html").exists()


class TestTheUpdateCheckWrapper:
    def test_it_writes_the_report_and_the_state(self, tmp_path: Path, monkeypatch) -> None:
        from ironclad.frameworks import updates

        page = (
            '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
            + ("The criteria remain current and are described at length. " * 20)
            + "</body></html>"
        )
        monkeypatch.setattr(updates, "_fetch", lambda url: (page, ""))

        output = tmp_path / "updates.json"
        state = tmp_path / "state.json"
        assert (
            check_framework_updates.main(
                ["--framework", "all", "--output", str(output), "--state", str(state)]
            )
            == 0
        )
        report = json.loads(output.read_text("utf-8"))
        assert report["updates_found"] is False
        assert state.exists()

    def test_an_unknown_framework_exits_two(self, tmp_path: Path, capsys) -> None:
        code = check_framework_updates.main(
            ["--framework", "iso-27001", "--output", str(tmp_path / "u.json")]
        )
        assert code == 2
        assert "unknown framework" in capsys.readouterr().err
