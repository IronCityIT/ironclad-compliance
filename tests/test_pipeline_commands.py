"""Every `ironclad` command the pipelines run is one the CLI accepts.

`compliance-assessment.yml` and the Jenkinsfile call `python -m ironclad.cli`
in shell, and nothing but a real dispatch runs that shell. A flag renamed in
`ironclad/cli.py` would first fail on a client's assessment, after the evidence
was staged. Each command is parsed here, not run, by the parser `ironclad`
itself builds, as `tests/test_documented_commands.py` does for the runbooks.

The choices a dispatcher can pick are held to the engine the same way: a
framework, group or assessment type offered in the workflow or the Jenkinsfile
that the engine does not know fails at run time, and one the engine knows that
neither offers cannot be ordered.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import re
import shlex
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from ironclad import registry
from ironclad.cli import build_parser
from ironclad.frameworks.loader import FRAMEWORK_ALIASES
from ironclad.report.views import ASSESSMENT_TYPES

ROOT = Path(__file__).resolve().parent.parent

PIPELINES = (
    ".github/workflows/ci.yml",
    ".github/workflows/compliance-assessment.yml",
    ".github/workflows/framework-updates.yml",
    "Jenkinsfile",
)

_PROGRAM = re.compile(r"^(?:run:\s*)?python3? -m ironclad\.cli\s+")
_CONTINUED = re.compile(r"\\\n[ \t]*")
_SHELL_STOP = {"|", "||", "&&", ";", "<", ">", ">>", "2>", "2>&1"}
#: `previous="--previous previous/assessment.json"`: optional flags held in a
#: variable and expanded unquoted, so the command runs with them or without.
_OPTIONAL_FLAGS = re.compile(r'^\s*(\w+)="(--[^"]+)"\s*$', re.M)


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def _expansions(name: str, text: str) -> dict[str, list[list[str]]]:
    """What a word can stand for when the pipeline runs: word -> each expansion."""
    expansions: dict[str, list[list[str]]] = {
        f"${var}": [[], shlex.split(value)] for var, value in _OPTIONAL_FLAGS.findall(text)
    }
    # A dispatch choice reaches the command as any one of its options.
    # PyYAML reads the bare key `on` as True; a bare `workflow_dispatch:` is None.
    triggers = yaml.safe_load(text)[True] if name.endswith(".yml") else {}
    dispatch = (triggers.get("workflow_dispatch") if isinstance(triggers, dict) else None) or {}
    for field, spec in dispatch.get("inputs", {}).items():
        if spec.get("type") == "choice":
            expansions[f"${{{{ inputs.{field} }}}}"] = [[o] for o in spec["options"]]
    return expansions


def _variants(argv: list[str], expansions: dict[str, list[list[str]]]) -> list[list[str]]:
    """The argument lists a command can run with, one per expansion of its words."""
    choices = [expansions.get(word, [[word]]) for word in argv]
    return [
        [word for part in combination for word in part]
        for combination in itertools.product(*choices)
    ]


def pipeline_commands() -> list[tuple[str, str, list[str]]]:
    """Each command a pipeline runs: (file, as written, argv)."""
    found = []
    for name in PIPELINES:
        text = _text(name)
        expansions = _expansions(name, text)
        for line in _CONTINUED.sub(" ", text).split("\n"):
            match = _PROGRAM.match(line.strip())
            if not match:
                continue
            argv: list[str] = []
            for word in shlex.split(line.strip()[match.end() :], comments=True):
                if word in _SHELL_STOP:
                    break
                argv.append(word)
            for variant in _variants(argv, expansions):
                found.append((name, line.strip(), variant))
    return found


COMMANDS = pipeline_commands()


def _parse(argv: list[str]) -> str:
    """The parser's complaint, or "" if it accepted the arguments."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            build_parser().parse_args(argv)
    except SystemExit as exc:
        if exc.code:
            return err.getvalue().strip().splitlines()[-1]
    return ""


@pytest.mark.parametrize(
    ("pipeline", "written", "argv"),
    COMMANDS,
    ids=[f"{Path(p).name}:{' '.join(a)}" for p, _, a in COMMANDS],
)
def test_a_pipeline_command_parses(pipeline: str, written: str, argv: list[str]) -> None:
    assert _parse(argv) == "", (pipeline, written, _parse(argv))


def test_the_pipeline_commands_are_found() -> None:
    # A change to how the pipelines are written must not leave this file
    # checking nothing. Every step that touches a client's assessment, in
    # both pipelines, is named here.
    ran = {(Path(p).name, " ".join(a[:2])) for p, _, a in COMMANDS}
    for pipeline in ("compliance-assessment.yml", "Jenkinsfile"):
        for step in ("assess --client", "report --input", "export --input"):
            assert (pipeline, step) in ran, (pipeline, step)
        for step in ("store latest", "store health", "store publish"):
            assert (pipeline, step) in ran, (pipeline, step)
    for pipeline in ("ci.yml", "Jenkinsfile"):
        assert (pipeline, "validate --framework") in ran, pipeline
    # With and without the previous assessment, in both pipelines.
    for pipeline in ("compliance-assessment.yml", "Jenkinsfile"):
        assess = [a for p, _, a in COMMANDS if Path(p).name == pipeline and a[0] == "assess"]
        assert {"--previous" in a for a in assess} == {True, False}, pipeline


def _dispatch_options(name: str) -> list[str]:
    workflow = yaml.safe_load(_text(".github/workflows/compliance-assessment.yml"))
    # PyYAML reads the bare key `on` as True.
    options: list[str] = workflow[True]["workflow_dispatch"]["inputs"][name]["options"]
    return options


def _jenkins_choices(name: str) -> list[str]:
    match = re.search(rf"choice\(\s*name: '{name}',\s*choices: \[([^\]]*)\]", _text("Jenkinsfile"))
    assert match, name
    return re.findall(r"'([^']*)'", match.group(1))


def _smoke_frameworks(name: str) -> list[str]:
    match = re.search(r"for framework in ([^;]+); do", _text(name))
    assert match, name
    return match.group(1).split()


FRAMEWORKS = set(FRAMEWORK_ALIASES)
GROUPS = registry.all_groups(registry.discover())

#: Where a pipeline lists values for the engine: (what it offers, what the engine knows).
OFFERED: dict[str, tuple[Callable[[], list[str]], set[str]]] = {
    "workflow framework": (lambda: _dispatch_options("framework"), FRAMEWORKS),
    "workflow group": (lambda: _dispatch_options("group"), GROUPS),
    "workflow assessment_type": (
        lambda: _dispatch_options("assessment_type"),
        set(ASSESSMENT_TYPES),
    ),
    "Jenkins FRAMEWORK": (lambda: _jenkins_choices("FRAMEWORK"), FRAMEWORKS),
    "Jenkins GROUP": (lambda: _jenkins_choices("GROUP"), GROUPS),
    "ci.yml smoke loop": (lambda: _smoke_frameworks(".github/workflows/ci.yml"), FRAMEWORKS),
    "Jenkins smoke loop": (lambda: _smoke_frameworks("Jenkinsfile"), FRAMEWORKS),
}


@pytest.mark.parametrize("offered_by", OFFERED)
def test_a_pipeline_offers_exactly_what_the_engine_knows(offered_by: str) -> None:
    offered, known = OFFERED[offered_by]
    listed = offered()
    assert len(listed) == len(set(listed)), (offered_by, "listed twice", listed)
    assert set(listed) - known == set(), (offered_by, "unknown to the engine")
    assert known - set(listed) == set(), (offered_by, "known but not offered")


def test_the_dispatch_defaults_are_among_the_options() -> None:
    inputs = yaml.safe_load(_text(".github/workflows/compliance-assessment.yml"))[True][
        "workflow_dispatch"
    ]["inputs"]
    for name, spec in inputs.items():
        if spec.get("type") == "choice" and "default" in spec:
            assert spec["default"] in spec["options"], name
