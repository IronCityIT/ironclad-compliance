"""Every `ironclad` command the operator docs show is one the CLI accepts.

The runbooks Sage staff follow to grant, review and revoke a partner's access
(`HANDOFF.md` §17, `docs/http-api.md`) are copied and pasted, not read. A flag
renamed or a subcommand moved would leave them failing at the terminal with
nothing here noticing. Each command in a `sh` block is parsed, not run, by the
parser `ironclad` itself builds. A command named in prose is often partial
(`ironclad serve`, `--anchor N:DIGEST` in brackets), so there the subcommands
and flags it names must exist, and nothing more.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import shlex
from pathlib import Path

import pytest

from ironclad.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent

#: The documents an operator works from. STATUS.md and PRODUCTIZE_NOTES.md are
#: history: a command they quote is what was run then, not what to run now.
DOCS = ("README.md", "HANDOFF.md", "docs/http-api.md", "docs/ingestion-contract.md")

_PROGRAM = re.compile(r"^(?:ironclad|python3? -m ironclad\.cli)\s+")
_CONTINUED = re.compile(r"\\\n[ \t]*")
_SHELL_STOP = {"|", "||", "&&", ";", "<", ">", ">>", "2>", "2>&1"}

#: Stands for arguments shown in full elsewhere; the rest of the line still parses.
ELIDED = "..."


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def _sh_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] | None = None
    for line in text.split("\n"):
        if current is None:
            if line.strip() == "```sh":
                current = []
        elif line.strip().startswith("```"):
            blocks.append("\n".join(current))
            current = None
        else:
            current.append(line)
    return blocks


def _argv(written: str) -> list[str]:
    """The words after the program name, up to the first shell operator."""
    match = _PROGRAM.match(written)
    assert match, written
    argv: list[str] = []
    for word in shlex.split(written[match.end() :], comments=True):
        if word in _SHELL_STOP:
            break
        argv.append(word)
    return argv


def documented_commands() -> list[tuple[str, str, list[str]]]:
    """Each command in a `sh` block: (document, as written, argv)."""
    found = []
    for name in DOCS:
        for block in _sh_blocks(_text(name)):
            for line in _CONTINUED.sub(" ", block).split("\n"):
                if _PROGRAM.match(line.strip()):
                    found.append((name, line.strip(), _argv(line.strip())))
    return found


def mentioned_commands() -> list[tuple[str, str]]:
    """Each `ironclad ...` code span in prose: (document, as written)."""
    found = []
    for name in DOCS:
        prose = re.sub(r"```.*?```", "", _text(name), flags=re.S)
        for span in re.findall(r"`((?:ironclad|python3? -m ironclad\.cli) [^`\n]+)`", prose):
            found.append((name, span))
    return found


COMMANDS = documented_commands()
MENTIONS = mentioned_commands()


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


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _unknown_names(written: str) -> list[str]:
    """Subcommands and flags a mention names that the CLI does not have."""
    parser = build_parser()
    words = [w.strip("[]") for w in _PROGRAM.sub("", written).split()]
    unknown: list[str] = []
    rest = words
    while rest and _subcommands(parser) and not rest[0].startswith("-"):
        choices = _subcommands(parser)
        # `store health|init|publish` names several; each must exist.
        named = rest[0].split("|")
        unknown += [n for n in named if n not in choices]
        if any(n not in choices for n in named) or len(named) > 1:
            return unknown
        parser, rest = choices[named[0]], rest[1:]
    for word in rest:
        flag = word.split("=")[0]
        if re.fullmatch(r"--[a-z][a-z0-9-]*", flag) and flag not in parser._option_string_actions:
            unknown.append(flag)
    return unknown


@pytest.mark.parametrize(
    ("doc", "written", "argv"),
    COMMANDS,
    ids=[f"{doc}:{' '.join(argv[:2])}" for doc, _, argv in COMMANDS],
)
def test_a_documented_command_parses(doc: str, written: str, argv: list[str]) -> None:
    if ELIDED in argv:
        # Only what was left out may be missing; every flag shown must exist.
        complaint = _parse([word for word in argv if word != ELIDED])
        assert complaint == "" or "arguments are required" in complaint, (doc, written, complaint)
    else:
        assert _parse(argv) == "", (doc, written, _parse(argv))


@pytest.mark.parametrize(("doc", "written"), MENTIONS, ids=[f"{d}:{w}" for d, w in MENTIONS])
def test_a_command_named_in_prose_exists(doc: str, written: str) -> None:
    assert _unknown_names(written) == [], (doc, written)


def test_the_runbooks_are_all_checked() -> None:
    # A change to how the docs quote commands must not leave this file
    # checking nothing.
    assert len(COMMANDS) >= 50
    assert len(MENTIONS) >= 40
    shown = {" ".join(argv[:2]) for _, _, argv in COMMANDS}
    for runbook in (
        "tokens issue",
        "tokens revoke",
        "tokens review",
        "oversight access",
        "oversight review-packet",
        "oversight verify-packet",
        "access-log rotate",
        "access-log verify",
    ):
        assert runbook in shown, runbook
    assert any(w.startswith("ironclad tokens verify-ledger") for _, w in MENTIONS)


def test_a_continued_line_is_one_command() -> None:
    block = "```sh\nironclad tokens issue f --user u \\\n    --tenant t  # note\n```\n"
    (body,) = _sh_blocks(block)
    assert _argv(_CONTINUED.sub(" ", body)) == [
        "tokens", "issue", "f", "--user", "u", "--tenant", "t",
    ]  # fmt: skip


def test_a_renamed_flag_or_subcommand_would_be_caught() -> None:
    issue = ["tokens", "issue", "f", "--user", "u", "--tenant", "t", "--role", "viewer"]
    issue += ["--expires", "2027-01-01", "--actor", "a"]
    assert _parse(issue) == ""
    assert "unrecognized" in _parse([*issue, "--nope", "x"])
    assert "invalid choice" in _parse(["tokens", "grant", "f"])
    assert _unknown_names("ironclad tokens verify-ledger L [--anchr N:D]") == ["--anchr"]
    assert _unknown_names("ironclad store health|mend") == ["mend"]
    assert _unknown_names("ironclad oversight verfy") == ["verfy"]
    assert _unknown_names("ironclad store health|init|publish|list") == []
