"""Service-token expiry and the access review (`ironclad tokens review`)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ironclad.api.http import TokenFileAuthenticator, hash_token
from ironclad.api.tokens import (
    EXPIRY_WARNING_DAYS,
    InvalidExpiryError,
    is_expired,
    parse_expiry,
    review_tokens,
)
from ironclad.cli import main

AS_OF = date(2026, 9, 26)


def _entry(token: str, **extra: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "sha256": hash_token(token),
        "user_id": f"{token}@sage.example",
        "tenant_id": "sage-spine",
        "roles": ["viewer"],
    }
    entry.update(extra)
    return entry


def _item(review: dict, user: str) -> dict:
    return next(i for i in review["items"] if i.get("user_id") == user)


def _messages(item: dict, level: str) -> list[str]:
    return [f["message"] for f in item["findings"] if f["level"] == level]


# ------------------------------------------------------------------ expiry


class TestExpiry:
    def test_no_expiry_is_none(self) -> None:
        assert parse_expiry(None) is None
        assert parse_expiry("") is None

    @pytest.mark.parametrize("value", ["2026-02-30", "26-09-30", "2026-9-30", "tomorrow", 20261231])
    def test_anything_but_a_calendar_date_is_invalid(self, value: object) -> None:
        with pytest.raises(InvalidExpiryError):
            parse_expiry(value)

    def test_a_token_works_through_its_last_day_in_utc(self) -> None:
        last = date(2026, 9, 30)
        assert not is_expired(last, datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc))
        assert is_expired(last, datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc))
        assert not is_expired(None, datetime(9999, 1, 1, tzinfo=timezone.utc))

    def test_the_last_day_is_read_in_utc_not_local_time(self) -> None:
        from datetime import timedelta

        # 20:00 on the 30th in New York is 00:00 on the 1st in UTC: expired.
        eastern = timezone(timedelta(hours=-4))
        assert is_expired(date(2026, 9, 30), datetime(2026, 9, 30, 20, 0, tzinfo=eastern))

    def test_the_authenticator_follows_its_clock(self, tmp_path: Path) -> None:
        path = tmp_path / "tokens.json"
        path.write_text(json.dumps({"tokens": [_entry("partner", expires_at="2026-09-30")]}))
        now = [datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)]
        auth = TokenFileAuthenticator(path, clock=lambda: now[0])
        principal = auth.principal_for("partner")
        assert principal is not None and principal.tenant_id == "sage-spine"
        now[0] = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        assert auth.principal_for("partner") is None


# ------------------------------------------------------------------ review


class TestReview:
    def test_each_state_and_its_findings(self) -> None:
        document = {
            "tokens": [
                _entry("current", expires_at="2027-06-30"),
                _entry("soon", expires_at="2026-10-10"),
                _entry("forever"),
                _entry("lapsed", expires_at="2026-09-25"),
                _entry("typo", expires_at="2026-13-01"),
            ]
        }
        review = review_tokens(document, AS_OF)
        states = {i["user_id"]: i["state"] for i in review["items"]}
        assert states == {
            "current@sage.example": "active",
            "soon@sage.example": "expiring",
            "forever@sage.example": "active",
            "lapsed@sage.example": "expired",
            "typo@sage.example": "refused",
        }
        assert _item(review, "current@sage.example")["findings"] == []
        assert _messages(_item(review, "forever@sage.example"), "notice") == [
            "no expires_at; this token works until the entry is removed"
        ]
        assert "remove the entry" in _messages(_item(review, "lapsed@sage.example"), "high")[0]
        assert review["entries"] == 5
        assert review["active"] == 3
        assert review["high"] == 2
        assert review["notices"] == 2
        assert review["tenants"] == ["sage-spine"]

    def test_the_warning_window_edges(self) -> None:
        inside = date.fromordinal(AS_OF.toordinal() + EXPIRY_WARNING_DAYS).isoformat()
        outside = date.fromordinal(AS_OF.toordinal() + EXPIRY_WARNING_DAYS + 1).isoformat()
        review = review_tokens(
            {
                "tokens": [
                    _entry("last-day", expires_at=AS_OF.isoformat()),
                    _entry("inside", expires_at=inside),
                    _entry("outside", expires_at=outside),
                ]
            },
            AS_OF,
        )
        # The last day is still a working day, as the authenticator reads it.
        assert _item(review, "last-day@sage.example")["state"] == "expiring"
        assert _item(review, "inside@sage.example")["state"] == "expiring"
        assert _item(review, "outside@sage.example")["state"] == "active"

    def test_broken_entries_are_high(self) -> None:
        review = review_tokens(
            {
                "tokens": [
                    _entry("dup"),
                    _entry("dup", tenant_id="other"),
                    _entry("no-tenant", tenant_id=""),
                    _entry("unslugged", tenant_id="Sage Spine"),
                    _entry("typo-role", roles=["veiwer"]),
                    {**_entry("short-digest"), "sha256": "abc123"},
                    {**_entry("anonymous"), "user_id": ""},
                    "not an object",
                ]
            },
            AS_OF,
        )
        dups = [i for i in review["items"] if i.get("user_id") == "dup@sage.example"]
        assert [i["state"] for i in dups] == ["refused", "refused"]
        assert "listed 2 times" in _messages(dups[0], "high")[0]
        assert _item(review, "no-tenant@sage.example")["state"] == "refused"
        assert _item(review, "unslugged@sage.example")["state"] == "refused"
        typo = _item(review, "typo-role@sage.example")
        assert _messages(typo, "high") == [
            "unrecognised roles dropped: veiwer",
            "no recognised role; the token can reach nothing",
        ]
        assert _item(review, "short-digest@sage.example")["state"] == "refused"
        assert "no user_id" in _messages(_item(review, ""), "high")[0]
        assert review["items"][-1]["state"] == "refused"
        # Every entry here has a high finding; none is counted as access.
        assert review["high"] == len(review["items"])
        assert review["tenants"] == ["sage-spine"]

    def test_only_a_digest_prefix_is_shown(self) -> None:
        review = review_tokens({"tokens": [_entry("partner")]}, AS_OF)
        text = json.dumps(review)
        assert hash_token("partner") not in text
        assert review["items"][0]["digest_prefix"] == hash_token("partner")[:12]

    def test_the_review_agrees_with_the_authenticator(self, tmp_path: Path) -> None:
        # Whatever the review calls active or expiring, the server serves;
        # whatever it calls expired or refused, the server refuses.
        tokens = ["ok", "soon", "old", "bad-date", "dup", "no-tenant"]
        document = {
            "tokens": [
                _entry("ok"),
                _entry("soon", expires_at="2026-10-01"),
                _entry("old", expires_at="2026-09-25"),
                _entry("bad-date", expires_at="2026-09-31"),
                _entry("dup"),
                _entry("dup", roles=["owner"]),
                _entry("no-tenant", tenant_id=""),
            ]
        }
        path = tmp_path / "tokens.json"
        path.write_text(json.dumps(document))
        auth = TokenFileAuthenticator(
            path, clock=lambda: datetime(2026, 9, 26, tzinfo=timezone.utc)
        )
        review = review_tokens(document, AS_OF)
        for token in tokens:
            states = {
                i["state"] for i in review["items"] if i["user_id"] == f"{token}@sage.example"
            }
            served = auth.principal_for(token) is not None
            assert served == (states <= {"active", "expiring"}), token

    def test_not_a_token_file_is_refused(self) -> None:
        with pytest.raises(ValueError):
            review_tokens({"tokens": "yes"}, AS_OF)


# --------------------------------------------------------------------- cli


class TestReviewCommand:
    @pytest.fixture
    def token_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "tokens.json"
        path.write_text(
            json.dumps(
                {
                    "tokens": [
                        _entry("current", expires_at="2027-06-30"),
                        _entry("forever"),
                    ]
                }
            )
        )
        return path

    def test_prints_the_review(self, token_file: Path, capsys) -> None:
        assert main(["tokens", "review", str(token_file), "--as-of", "2026-09-26"]) == 0
        review = json.loads(capsys.readouterr().out)
        assert review["as_of"] == "2026-09-26"
        assert review["active"] == 2

    def test_fail_on(self, token_file: Path, capsys) -> None:
        args = ["tokens", "review", str(token_file), "--as-of", "2026-09-26"]
        assert main([*args, "--fail-on", "high"]) == 0
        assert main([*args, "--fail-on", "any"]) == 4
        # A year on, the dated token has lapsed and is still in the file.
        assert (
            main(
                ["tokens", "review", str(token_file), "--as-of", "2027-07-01", "--fail-on", "high"]
            )
            == 4
        )
        capsys.readouterr()

    def test_bad_input_is_exit_2(self, tmp_path: Path, token_file: Path, capsys) -> None:
        assert main(["tokens", "review", str(tmp_path / "missing.json")]) == 2
        (tmp_path / "junk.json").write_text("{not json")
        assert main(["tokens", "review", str(tmp_path / "junk.json")]) == 2
        (tmp_path / "shape.json").write_text('{"tokens": {}}')
        assert main(["tokens", "review", str(tmp_path / "shape.json")]) == 2
        assert main(["tokens", "review", str(token_file), "--as-of", "2026-02-30"]) == 2
        capsys.readouterr()
