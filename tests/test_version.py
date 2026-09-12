"""Guards that stop the repository from disagreeing with itself."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

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
