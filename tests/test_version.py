"""Guards that stop the repository from disagreeing with itself."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_package_version_matches_the_project_metadata() -> None:
    from ironclad.version import __version__

    declared = re.search(
        r'^version\s*=\s*"([^"]+)"', (REPO_ROOT / "pyproject.toml").read_text(), re.MULTILINE
    )
    assert declared, "pyproject.toml declares no version"
    assert declared.group(1) == __version__


def test_the_dashboard_catalog_matches_the_registry() -> None:
    # The dashboard renders its capability checkboxes from catalog.json. If it
    # drifts from the registry, a UI selection stops mapping onto --modules.
    completed = subprocess.run(
        [sys.executable, "tools/build_catalog.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_the_workflow_framework_choices_match_the_loader_aliases() -> None:
    from ironclad.frameworks.loader import FRAMEWORK_ALIASES

    workflow = (REPO_ROOT / ".github/workflows/compliance-assessment.yml").read_text()
    for alias in FRAMEWORK_ALIASES:
        assert f"- {alias}\n" in workflow, f"{alias} is missing from the workflow choices"


def test_every_declared_framework_file_exists() -> None:
    versions = json.loads((REPO_ROOT / "frameworks/framework-versions.json").read_text())
    for entry in versions["frameworks"]:
        assert (REPO_ROOT / "frameworks" / entry["local_file"]).exists(), entry["local_file"]
    for entry in versions["crosswalks"]:
        assert (REPO_ROOT / "frameworks" / entry["local_file"]).exists(), entry["local_file"]


def test_the_loader_aliases_match_the_version_register() -> None:
    from ironclad.frameworks.loader import FRAMEWORK_ALIASES

    versions = json.loads((REPO_ROOT / "frameworks/framework-versions.json").read_text())
    registered = {entry["alias"]: entry["local_file"] for entry in versions["frameworks"]}
    assert registered == FRAMEWORK_ALIASES


def test_committed_artifacts_pass_the_commit_gate() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/validate_artifacts.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_control_mapping_doc_matches_the_crosswalk_data() -> None:
    # A crosswalk document that disagrees with the engine is worse than none:
    # it is the version a client would be shown.
    completed = subprocess.run(
        [sys.executable, "tools/build_control_mapping.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_a_dry_run_of_the_assessment_workflow_can_publish_nothing() -> None:
    # `dry_run` exists so the pipeline can be proven on a real runner with the
    # sample evidence. Its whole value is that it cannot touch a client's data
    # or a store, so every step that publishes or reads client evidence must be
    # gated on it — checked here, because nothing tests a workflow file but a
    # dispatch, and a dispatch that publishes is the failure being prevented.
    import yaml

    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/compliance-assessment.yml").read_text()
    )
    assert workflow[True]["workflow_dispatch"]["inputs"]["dry_run"]["default"] is False

    def steps(job: str) -> dict[str, dict]:
        return {
            s.get("name") or s.get("id") or s["uses"]: s for s in workflow["jobs"][job]["steps"]
        }

    gated = [
        ("assess", "Stage the client evidence"),
        ("assess", "Fetch the client evidence from storage"),
        ("assess", "Refuse to assess with no evidence source"),
        ("report", "Publish to the store"),
        ("report", "Publish to the legacy ingest"),
    ]
    for job, name in gated:
        condition = str(steps(job)[name].get("if", ""))
        assert "!inputs.dry_run" in condition, (
            f"{job}/{name} is not gated on dry_run: {condition!r}"
        )

    sample = steps("assess")["Use the bundled sample evidence"]
    assert sample["if"] == "inputs.dry_run"
    assert "examples/evidence" in sample["run"]


def test_the_workflow_fold_step_runs_verbatim_against_a_stored_result(tmp_path: Path) -> None:
    # The report job's "Fold in the AI consensus" step is inline Python in
    # YAML, so nothing but a dispatch runs it — and the first dispatch is where
    # the engine's list output was discovered to be rejected. Extract the
    # script from the workflow as committed and run it against a real stored
    # assessment with a payload in the engine's real shape.
    import base64
    import os
    import shutil
    import subprocess
    import sys

    import yaml

    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/compliance-assessment.yml").read_text()
    )
    steps = {s.get("name"): s for s in workflow["jobs"]["report"]["steps"]}
    script = steps["Fold in the AI consensus"]["run"]
    heredoc = script.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    heredoc = "\n".join(
        line[10:] if line.startswith(" " * 10) else line for line in heredoc.splitlines()
    )

    out = tmp_path / "out"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ironclad.cli",
            "assess",
            "--client",
            "Fold Test",
            "--framework",
            "soc2",
            "--evidence-dir",
            str(REPO_ROOT / "examples/evidence"),
            "--group",
            "deep",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    document = json.loads((out / "assessment.json").read_text())
    from ironclad.engine import consensus_findings

    sent = consensus_findings(document["findings"])
    answers = [
        {
            "consensus_severity": "High",
            "confidence_percent": 77.0,
            "total_models": 15,
            "successful_models": 9,
            "aggregated_remediation": ["do the thing"],
            "engine_version": "5.0",
        }
        for _ in sent
    ]
    events_before = document["audit"]["event_count"]

    workdir = tmp_path / "work"
    workdir.mkdir()
    shutil.copytree(out, workdir / "out")
    # The artifact path wins over the job output: the artifact carries the
    # real answers here and the env carries a decoy, so a fold that read the
    # env would report one result, not len(sent).
    (workdir / "consensus").mkdir()
    (workdir / "consensus" / "result.json").write_text(json.dumps(answers))
    decoy = base64.b64encode(json.dumps([answers[0]]).encode()).decode()
    (workdir / "github-output").write_text("")
    env = {
        **os.environ,
        "CONSENSUS_B64": decoy,
        "GITHUB_OUTPUT": str(workdir / "github-output"),
        "PYTHONPATH": str(REPO_ROOT),
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-",
        ],
        input=heredoc,
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "consensus from the run artifact" in completed.stdout
    assert f"consensus status: ok analysed: {len(sent)} of {len(sent)}" in completed.stdout

    outputs = (workdir / "github-output").read_text()
    assert "status=ok\n" in outputs and f"analysed={len(sent)}\n" in outputs
    folded = json.loads((workdir / "out" / "assessment.json").read_text())
    assert folded["consensus"]["status"] == "ok"
    assert folded["consensus"]["severity"] == "high"
    assert len(folded["consensus"]["results"]) == len(sent)
    assert folded["warnings"] == document["warnings"], "the fold must not duplicate warnings"
    assert folded["audit"]["event_count"] == events_before + 1
    assert folded["audit"]["events"][-1]["action"] == "assessment.consensus_merged"
    assert folded["audit"]["verified"] is True


class TestThePrepareJobResolvesTheStandardInputs:
    """`client_name` and `scan_id` are the ICIT standard dispatch inputs; this
    workflow took `client_id`. Both are accepted now, resolved once in the
    prepare job's shell. The shell is extracted from the workflow as committed
    and run, because nothing else tests shell."""

    @staticmethod
    def _run(step_name: str, env: dict[str, str], outputs_from: dict[str, str] | None = None):
        import os
        import subprocess
        import tempfile

        import yaml

        workflow = yaml.safe_load(
            (REPO_ROOT / ".github/workflows/compliance-assessment.yml").read_text()
        )
        steps = {s.get("name"): s for s in workflow["jobs"]["prepare"]["steps"]}
        with tempfile.NamedTemporaryFile("w+", delete=False) as handle:
            output_file = handle.name
        completed = subprocess.run(
            ["bash", "-c", steps[step_name]["run"]],
            env={
                "PATH": os.environ["PATH"],
                "GITHUB_OUTPUT": output_file,
                # the step's declared env, as GitHub would set it for an empty input
                **{k: "" for k in ("CLIENT_NAME", "CLIENT_ID_ALIAS", "SCAN_ID", "CLIENT_ID")},
                "FRAMEWORK": "soc2",
                "DRY_RUN": "false",
                **(outputs_from or {}),
                **env,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        outputs = dict(
            line.split("=", 1) for line in Path(output_file).read_text().splitlines() if "=" in line
        )
        return completed.returncode, completed.stdout + completed.stderr, outputs

    def test_client_name_is_the_standard_and_client_id_its_alias(self) -> None:
        code, _, out = self._run("Validate the client identifier", {"CLIENT_NAME": "Acme Corp"})
        assert (code, out["client_id"]) == (0, "Acme Corp")
        code, _, out = self._run("Validate the client identifier", {"CLIENT_ID_ALIAS": "Acme Corp"})
        assert (code, out["client_id"]) == (0, "Acme Corp")
        code, _, out = self._run(
            "Validate the client identifier",
            {"CLIENT_NAME": "Acme Corp", "CLIENT_ID_ALIAS": "Acme Corp"},
        )
        assert code == 0

    def test_neither_or_a_disagreement_is_refused(self) -> None:
        code, log, _ = self._run("Validate the client identifier", {})
        assert code == 1 and "client_name is required" in log
        code, log, _ = self._run(
            "Validate the client identifier", {"CLIENT_NAME": "acme", "CLIENT_ID_ALIAS": "beta"}
        )
        assert code == 1 and "disagree" in log

    @pytest.mark.parametrize("bad", ["../x", "a/b", "x;rm -rf /", "a" * 129, "sp ace"])
    def test_a_scan_id_that_cannot_be_an_assessment_id_is_refused(self, bad: str) -> None:
        code, log, _ = self._run(
            "Validate the client identifier", {"CLIENT_NAME": "acme", "SCAN_ID": bad}
        )
        assert code == 1, bad
        assert "scan_id must be" in log

    def test_a_scan_id_becomes_the_assessment_id_and_a_dry_run_still_says_so(self) -> None:
        code, _, out = self._run(
            "Plan the run",
            {"CLIENT_ID": "Acme Corp", "SCAN_ID": "scan-2026-09-17-abc", "FRAMEWORK": "soc2"},
        )
        assert (code, out["assessment_id"]) == (0, "scan-2026-09-17-abc")
        code, _, out = self._run(
            "Plan the run",
            {
                "CLIENT_ID": "Acme Corp",
                "SCAN_ID": "scan-2026-09-17-abc",
                "FRAMEWORK": "soc2",
                "DRY_RUN": "true",
            },
        )
        assert out["assessment_id"] == "scan-2026-09-17-abc-dry-run"
        code, _, out = self._run("Plan the run", {"CLIENT_ID": "Acme Corp", "FRAMEWORK": "soc2"})
        assert out["assessment_id"].startswith("acme-corp-soc2-")
