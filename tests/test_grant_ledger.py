"""The grant ledger: every issue and revocation on record, and a token file held to it."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ironclad.api import grant_ledger
from ironclad.api.http import hash_token
from ironclad.api.tokens import review_tokens
from ironclad.cli import main

AS_OF = date(2026, 9, 26)


@pytest.fixture
def cli(capsys):
    """Run the CLI and return (exit code, parsed stdout or None, stderr)."""

    def run(*args: str) -> tuple[int, object, str]:
        code = main(list(args))
        captured = capsys.readouterr()
        out = json.loads(captured.out) if captured.out.strip() else None
        return code, out, captured.err

    return run


ISSUE = ["--tenant", "sage-spine", "--role", "viewer", "--expires", "2026-12-31",
         "--actor", "bill", "--as-of", "2026-09-26"]  # fmt: skip


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _high(item: dict) -> list[str]:
    return [f["message"] for f in item["findings"] if f["level"] == "high"]


def _review(cli, tokens: Path, *extra: str) -> tuple[int, dict]:
    code, out, _ = cli(
        "tokens", "review", str(tokens), "--ledger", str(grant_ledger.default_path(tokens)),
        "--as-of", "2026-09-26", *extra,
    )  # fmt: skip
    return code, out  # type: ignore[return-value]


class TestRecording:
    def test_issue_and_revoke_are_chained_lines_without_the_token(self, tmp_path, cli) -> None:
        tokens = tmp_path / "tokens.json"
        code, issued, _ = cli(
            "tokens", "issue", str(tokens), "--user", "dana@partner.example", *ISSUE
        )
        assert code == 0
        token = issued["token"]  # type: ignore[index]
        ledger = grant_ledger.default_path(tokens)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["tokens.json", "tokens.json.ledger"]

        code, revoked, _ = cli(
            "tokens", "revoke", str(tokens), "--user", "dana@partner.example",
            "--tenant", "sage-spine", "--actor", "erin", "--as-of", "2026-10-01",
        )  # fmt: skip
        assert code == 0
        lines = _lines(ledger)
        assert [(line["seq"], line["action"], line["actor"]) for line in lines] == [
            (1, "issue", "bill"),
            (2, "revoke", "erin"),
        ]
        assert lines[0]["sha256"] == lines[1]["sha256"] == hash_token(token)
        assert lines[0]["roles"] == ["viewer"] and lines[0]["expires_at"] == "2026-12-31"
        assert lines[1]["as_of"] == "2026-10-01"
        assert token not in ledger.read_text(encoding="utf-8")
        verdict = grant_ledger.verify_file(ledger)
        assert verdict["verified"] and verdict["head"] == lines[1]["hash"]
        assert issued["ledger_head"] == lines[0]["hash"]  # type: ignore[index]
        assert revoked["ledger_head"] == lines[1]["hash"]  # type: ignore[index]

    def test_each_expired_entry_is_its_own_line(self, tmp_path, cli) -> None:
        tokens = tmp_path / "tokens.json"
        for user in ("a@p.example", "b@p.example", "c@p.example"):
            expires = "2026-12-31" if user.startswith("c") else "2026-09-30"
            args = [a if a != "2026-12-31" else expires for a in ISSUE]
            assert cli("tokens", "issue", str(tokens), "--user", user, *args)[0] == 0
        code, _, _ = cli(
            "tokens", "revoke", str(tokens), "--expired", "--actor", "bill", "--as-of", "2026-10-01"
        )
        assert code == 0
        revokes = [
            line for line in _lines(grant_ledger.default_path(tokens)) if line["action"] == "revoke"
        ]
        assert [line["user_id"] for line in revokes] == ["a@p.example", "b@p.example"]
        assert grant_ledger.verify_file(grant_ledger.default_path(tokens))["verified"]

    def test_an_explicit_ledger_path(self, tmp_path, cli) -> None:
        tokens = tmp_path / "tokens.json"
        elsewhere = tmp_path / "audit" / "grants.ledger"
        elsewhere.parent.mkdir()
        code, _, _ = cli(
            "tokens",
            "issue",
            str(tokens),
            "--user",
            "d@p.example",
            *ISSUE,
            "--ledger",
            str(elsewhere),
        )
        assert code == 0
        assert len(_lines(elsewhere)) == 1
        assert not grant_ledger.default_path(tokens).exists()

    def test_a_ledger_that_cannot_be_written_leaves_the_token_file(
        self, tmp_path, cli, monkeypatch
    ) -> None:
        tokens = tmp_path / "tokens.json"
        assert cli("tokens", "issue", str(tokens), "--user", "d@p.example", *ISSUE)[0] == 0
        before = tokens.read_bytes()
        ledger_before = grant_ledger.default_path(tokens).read_bytes()

        def refuse(self, *args, **kwargs):
            raise grant_ledger.GrantLedgerError("disk full")

        monkeypatch.setattr(grant_ledger.GrantLedger, "record", refuse)
        code, out, err = cli("tokens", "issue", str(tokens), "--user", "e@p.example", *ISSUE)
        assert (code, out) == (2, None)
        assert "disk full" in err and "nothing was written" in err
        revoke = ["--user", "d@p.example", "--tenant", "sage-spine", "--actor", "bill"]
        assert cli("tokens", "revoke", str(tokens), *revoke)[0] == 2
        assert tokens.read_bytes() == before
        assert grant_ledger.default_path(tokens).read_bytes() == ledger_before
        assert not (tmp_path / "tokens.json.lock").exists()

    def test_an_edited_ledger_refuses_further_edits(self, tmp_path, cli) -> None:
        tokens = tmp_path / "tokens.json"
        assert cli("tokens", "issue", str(tokens), "--user", "d@p.example", *ISSUE)[0] == 0
        ledger = grant_ledger.default_path(tokens)
        ledger.write_text(ledger.read_text().replace('"bill"', '"someone-else"'))
        before = tokens.read_bytes()
        code, _, err = cli("tokens", "issue", str(tokens), "--user", "e@p.example", *ISSUE)
        assert code == 2 and "not a whole chain at line 1" in err
        assert tokens.read_bytes() == before

    def test_a_revocation_must_name_who_made_it(self, tmp_path, cli) -> None:
        tokens = tmp_path / "tokens.json"
        assert cli("tokens", "issue", str(tokens), "--user", "d@p.example", *ISSUE)[0] == 0
        before = tokens.read_bytes()
        revoke = ["--user", "d@p.example", "--tenant", "sage-spine", "--actor", "  "]
        code, _, err = cli("tokens", "revoke", str(tokens), *revoke)
        assert code == 2 and "--actor" in err
        assert tokens.read_bytes() == before
        assert len(_lines(grant_ledger.default_path(tokens))) == 1


class TestReconcile:
    @pytest.fixture
    def issued(self, tmp_path, cli) -> Path:
        tokens = tmp_path / "tokens.json"
        for user in ("dana@partner.example", "sam@sage.example"):
            assert cli("tokens", "issue", str(tokens), "--user", user, *ISSUE)[0] == 0
        return tokens

    def _document(self, tokens: Path) -> dict:
        return json.loads(tokens.read_text())

    def test_issued_entries_carry_their_grant(self, issued, cli) -> None:
        code, review = _review(cli, issued, "--fail-on", "high")
        assert code == 0 and review["high"] == 0
        assert [i["granted_by"] for i in review["items"]] == ["bill", "bill"]
        ledger = review["ledger"]
        assert ledger["entries"] == 2 and ledger["unrecorded"] == []
        assert ledger["head"] == grant_ledger.verify_file(grant_ledger.default_path(issued))["head"]

    def test_a_hand_written_entry_is_high(self, issued, cli) -> None:
        document = self._document(issued)
        document["tokens"].append(
            {"sha256": hash_token("pasted"), "user_id": "mallory@p.example",
             "tenant_id": "sage-spine", "roles": ["owner"], "expires_at": "2026-12-31"}
        )  # fmt: skip
        issued.write_text(json.dumps(document))
        code, review = _review(cli, issued, "--fail-on", "high")
        assert code == 4 and review["high"] == 1
        pasted = review["items"][2]
        assert "no grant on record" in _high(pasted)[0]
        assert "granted_by" not in pasted

    @pytest.mark.parametrize(
        ("field", "value"),
        [("expires_at", "2027-12-31"), ("roles", ["owner", "viewer"]), ("tenant_id", "beta")],
    )
    def test_an_entry_edited_after_its_grant_is_high(self, issued, cli, field, value) -> None:
        document = self._document(issued)
        document["tokens"][0][field] = value
        issued.write_text(json.dumps(document))
        code, review = _review(cli, issued, "--fail-on", "high")
        assert code == 4
        messages = _high(review["items"][0])
        assert any(m.startswith("differs from its grant") and field in m for m in messages)
        assert _high(review["items"][1]) == []

    def test_a_revoked_entry_put_back_is_high(self, issued, cli) -> None:
        restored = self._document(issued)["tokens"][0]
        revoke = ["--user", "dana@partner.example", "--tenant", "sage-spine", "--actor", "erin"]
        assert cli("tokens", "revoke", str(issued), *revoke)[0] == 0
        document = self._document(issued)
        document["tokens"].append(restored)
        issued.write_text(json.dumps(document))
        code, review = _review(cli, issued, "--fail-on", "high")
        assert code == 4
        assert any("by erin and back in the file" in m for m in _high(review["items"][1]))

    def test_an_entry_removed_by_hand_is_a_notice(self, issued, cli) -> None:
        document = self._document(issued)
        del document["tokens"][0]
        issued.write_text(json.dumps(document))
        code, review = _review(cli, issued, "--fail-on", "high")
        assert code == 0
        (gone,) = review["ledger"]["unrecorded"]
        assert gone["user_id"] == "dana@partner.example" and gone["granted_by"] == "bill"
        assert len(gone["digest_prefix"]) == 12
        assert "without `tokens revoke`" in gone["message"]
        assert _review(cli, issued, "--fail-on", "any")[0] == 4

    def test_a_revoked_entry_is_not_unrecorded(self, issued, cli) -> None:
        revoke = ["--user", "dana@partner.example", "--tenant", "sage-spine", "--actor", "bill"]
        assert cli("tokens", "revoke", str(issued), *revoke)[0] == 0
        code, review = _review(cli, issued, "--fail-on", "high")
        assert code == 0 and review["ledger"]["unrecorded"] == []

    def test_a_broken_ledger_is_not_reviewed(self, issued, cli) -> None:
        ledger = grant_ledger.default_path(issued)
        lines = ledger.read_text().splitlines()
        ledger.write_text(lines[1] + "\n")  # the first grant removed
        code, out, err = cli(
            "tokens", "review", str(issued), "--ledger", str(ledger), "--as-of", "2026-09-26"
        )
        assert code == 4 and out is None
        assert "not a whole chain at line 1" in err

    def test_a_missing_ledger_is_bad_input(self, issued, tmp_path, cli) -> None:
        missing = tmp_path / "nowhere.ledger"
        code, out, err = cli("tokens", "review", str(issued), "--ledger", str(missing))
        assert (code, out) == (2, None) and "not found" in err

    def test_without_a_ledger_the_review_is_unchanged(self, issued) -> None:
        document = self._document(issued)
        review = review_tokens(document, AS_OF)
        assert "ledger" not in review
        assert all("granted_by" not in item for item in review["items"])
