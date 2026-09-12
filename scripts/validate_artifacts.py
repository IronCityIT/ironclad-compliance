#!/usr/bin/env python3
"""Artifact validation gate.

Enforces the ICIT commit gate before anything is committed or published:

  JSON  first byte is `{` or `[`, the last two bytes are the closing bracket
        plus a newline, and the document parses. The byte checks catch a file
        that was truncated mid-write or had a shell banner prepended — both of
        which still parse as "not JSON" only after something downstream has
        already failed on them.
  YAML  parses with a real YAML parser, and a workflow file declares the keys
        that make it a workflow. A broken workflow file is a failed run.

    python scripts/validate_artifacts.py                 # every tracked artifact
    python scripts/validate_artifacts.py out/result.json # specific paths

Exit code 0 clean, 1 if anything failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Checked when no paths are given.
DEFAULT_JSON_GLOBS = ("frameworks/**/*.json", "dashboard/public/*.json", "functions/*.json")
DEFAULT_YAML_GLOBS = (".github/workflows/*.yml", ".github/workflows/*.yaml")

SKIP_DIRS = {"node_modules", ".git", ".venv", "__pycache__", "dist", "build"}

OPENERS = {"{": "}", "[": "]"}


def _skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def check_json(path: Path) -> list[str]:
    problems: list[str] = []
    raw = path.read_bytes()

    if not raw:
        return ["file is empty"]

    first = raw[:1].decode("utf-8", "replace")
    if first not in OPENERS:
        problems.append(f"first byte is {first!r}, expected '{{' or '['")

    tail = raw[-2:]
    if first in OPENERS:
        expected = (OPENERS[first] + "\n").encode("utf-8")
        if tail != expected:
            problems.append(
                f"last two bytes are {tail!r}, expected {expected!r} "
                f"(closing bracket plus a trailing newline)"
            )

    try:
        json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        problems.append(f"not valid UTF-8: {exc}")
    except json.JSONDecodeError as exc:
        problems.append(f"does not parse: {exc}")

    return problems


def check_yaml(path: Path) -> list[str]:
    try:
        import yaml  # noqa: PLC0415 — dev dependency, absent in the runtime image
    except ImportError:
        return ["__skip__: PyYAML is not installed"]

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"does not parse: {exc}"]

    if document is None:
        return ["file is empty"]
    if not isinstance(document, dict):
        return ["top level is not a mapping"]

    if ".github/workflows" in str(path):
        problems = []
        if "jobs" not in document:
            problems.append("a workflow must declare 'jobs'")
        # PyYAML resolves a bare `on:` key to the boolean True. Accept either,
        # because the file on disk is correct in both cases.
        if "on" not in document and True not in document:
            problems.append("a workflow must declare 'on'")
        for name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict):
                problems.append(f"job {name!r} is not a mapping")
            elif "uses" not in job and "runs-on" not in job:
                problems.append(f"job {name!r} declares neither 'runs-on' nor 'uses'")
        return problems

    return []


def collect(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p) for p in paths]

    found: list[Path] = []
    for pattern in DEFAULT_JSON_GLOBS + DEFAULT_YAML_GLOBS:
        found.extend(p for p in REPO_ROOT.glob(pattern) if p.is_file() and not _skip(p))
    return sorted(set(found))


def main(argv: list[str] | None = None) -> int:
    targets = collect(list(argv if argv is not None else sys.argv[1:]))
    if not targets:
        print("nothing to validate")
        return 0

    failures = 0
    skipped = 0

    for path in targets:
        label = (
            path.relative_to(REPO_ROOT)
            if path.is_absolute() and REPO_ROOT in path.parents
            else path
        )

        if not path.exists():
            print(f"FAIL {label}\n       does not exist")
            failures += 1
            continue

        suffix = path.suffix.lower()
        if suffix == ".json":
            problems = check_json(path)
        elif suffix in (".yml", ".yaml"):
            problems = check_yaml(path)
        else:
            print(f"skip {label} (not a JSON or YAML artifact)")
            continue

        if problems and problems[0].startswith("__skip__"):
            print(f"skip {label} ({problems[0].removeprefix('__skip__: ')})")
            skipped += 1
        elif problems:
            print(f"FAIL {label}")
            for problem in problems:
                print(f"       {problem}")
            failures += 1
        else:
            print(f"ok   {label}")

    checked = len(targets) - skipped
    print(
        f"\n{checked - failures}/{checked} artifact(s) valid"
        + (f", {skipped} skipped" if skipped else "")
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
