"""The access log's chain, without a server: written, reopened, tampered with."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ironclad.api.access_log import (
    GENESIS_HASH,
    AccessLog,
    AccessLogError,
    verify_file,
)
from ironclad.cli import main

AT = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, count: int) -> AccessLog:
    log = AccessLog(path)
    for n in range(count):
        log.record(
            user=f"user{n}@sage.example",
            user_tenant="sage-spine",
            method="GET",
            path="/api/v1/tenants/sage-spine/oversight/partners",
            status=200,
            at=AT,
        )
    return log


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _rewrite(path: Path, lines: list[str]) -> None:
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def test_a_written_log_verifies_and_its_head_is_the_last_line(tmp_path: Path) -> None:
    path = tmp_path / "access.log"
    log = _write(path, 3)
    log.close()
    verdict = verify_file(path)
    assert verdict == {
        "entries": 3,
        "verified": True,
        "broken_at": None,
        "reason": "",
        "head": json.loads(_lines(path)[-1])["hash"],
    }
    first = json.loads(_lines(path)[0])
    assert (first["seq"], first["prev_hash"], first["at"]) == (
        1,
        GENESIS_HASH,
        "2026-09-26T12:00:00.000Z",
    )


def test_a_missing_file_is_an_empty_whole_chain(tmp_path: Path) -> None:
    verdict = verify_file(tmp_path / "none.log")
    assert (verdict["entries"], verdict["verified"], verdict["head"]) == (0, True, GENESIS_HASH)


def test_reopening_continues_the_chain_rather_than_starting_another(tmp_path: Path) -> None:
    path = tmp_path / "access.log"
    _write(path, 2).close()
    reopened = _write(path, 2)
    reopened.close()
    assert verify_file(path)["entries"] == 4
    assert [json.loads(line)["seq"] for line in _lines(path)] == [1, 2, 3, 4]


def test_a_refusal_turned_into_a_success_is_named_by_line(tmp_path: Path) -> None:
    path = tmp_path / "access.log"
    _write(path, 3).close()
    lines = _lines(path)
    entry = json.loads(lines[1])
    entry["status"] = 403
    lines[1] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    _rewrite(path, lines)
    verdict = verify_file(path)
    assert (verdict["verified"], verdict["broken_at"], verdict["entries"]) == (False, 2, 1)
    assert verdict["reason"] == "edited since it was written"


def test_a_line_removed_from_the_middle_breaks_the_chain(tmp_path: Path) -> None:
    path = tmp_path / "access.log"
    _write(path, 3).close()
    lines = _lines(path)
    _rewrite(path, [lines[0], lines[2]])
    verdict = verify_file(path)
    assert (verdict["verified"], verdict["broken_at"]) == (False, 2)
    assert "sequence 3" in verdict["reason"]


def test_a_line_removed_and_renumbered_is_still_caught_by_the_chain(tmp_path: Path) -> None:
    # Renumbering fixes the sequence and recomputing the hash fixes the line
    # itself; what the tamperer cannot fix without rewriting every later
    # line is the link to the line before.
    path = tmp_path / "access.log"
    _write(path, 3).close()
    lines = _lines(path)
    moved = json.loads(lines[2])
    moved["seq"] = 2
    from ironclad.api.access_log import _digest

    moved["hash"] = _digest(moved)
    _rewrite(path, [lines[0], json.dumps(moved, sort_keys=True, separators=(",", ":"))])
    verdict = verify_file(path)
    assert (verdict["verified"], verdict["broken_at"]) == (False, 2)
    assert verdict["reason"] == "does not chain from the line before"


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        (lambda e: {**e, "body": "PHI"}, "not an access-log entry"),
        (lambda e: {k: v for k, v in e.items() if k != "user"}, "not an access-log entry"),
    ],
)
def test_a_line_with_the_wrong_keys_is_refused(tmp_path: Path, damage, reason) -> None:
    path = tmp_path / "access.log"
    _write(path, 1).close()
    entry = damage(json.loads(_lines(path)[0]))
    _rewrite(path, [json.dumps(entry)])
    verdict = verify_file(path)
    assert (verdict["verified"], verdict["broken_at"], verdict["reason"]) == (False, 1, reason)


def test_a_log_cut_off_mid_line_is_refused_at_open(tmp_path: Path) -> None:
    path = tmp_path / "access.log"
    _write(path, 2).close()
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw[: len(raw) - 20], encoding="utf-8")
    assert verify_file(path)["broken_at"] == 2
    with pytest.raises(AccessLogError, match="not a whole chain at line 2"):
        AccessLog(path)


def test_concurrent_writers_in_one_process_leave_one_chain(tmp_path: Path) -> None:
    path = tmp_path / "access.log"
    log = AccessLog(path)
    threads = [
        threading.Thread(
            target=lambda n=n: log.record(
                user=f"u{n}", user_tenant="t", method="GET", path="/api/v1/me", status=200
            )
        )
        for n in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    log.close()
    verdict = verify_file(path)
    assert (verdict["verified"], verdict["entries"]) == (True, 20)
    assert verdict["head"] == log.head


def test_a_closed_log_refuses_to_record(tmp_path: Path) -> None:
    log = AccessLog(tmp_path / "access.log")
    log.close()
    with pytest.raises(AccessLogError, match="cannot append"):
        log.record(user=None, user_tenant=None, method="GET", path="/api/v1/me", status=401)


class TestVerifyCommand:
    def test_a_whole_log_exits_0_and_prints_the_head(self, tmp_path: Path, capsys) -> None:
        path = tmp_path / "access.log"
        log = _write(path, 2)
        log.close()
        assert main(["access-log", "verify", str(path)]) == 0
        verdict = json.loads(capsys.readouterr().out)
        assert (verdict["entries"], verdict["head"]) == (2, log.head)

    def test_an_edited_log_exits_4_naming_the_line(self, tmp_path: Path, capsys) -> None:
        path = tmp_path / "access.log"
        _write(path, 2).close()
        lines = _lines(path)
        _rewrite(path, [lines[0].replace("user0@", "someone@"), lines[1]])
        assert main(["access-log", "verify", str(path)]) == 4
        assert json.loads(capsys.readouterr().out)["broken_at"] == 1

    def test_a_missing_log_exits_2(self, tmp_path: Path, capsys) -> None:
        assert main(["access-log", "verify", str(tmp_path / "none.log")]) == 2
        assert "not found" in capsys.readouterr().err
