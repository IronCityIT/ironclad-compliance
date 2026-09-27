"""The access log's chain, without a server: written, reopened, tampered with."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ironclad.api.access_log import (
    GENESIS_HASH,
    MAX_PATHS,
    ROTATION_FIELDS,
    AccessLog,
    AccessLogError,
    line_digest,
    read_files,
    refusals,
    rotate,
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
        "first": 1,
        "continues": "",
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
    from ironclad.api.access_log import line_digest

    moved["hash"] = line_digest(moved)
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


class TestAnchor:
    """The chain cannot see a cut tail or a replaced file; an anchor kept elsewhere can."""

    def _verify(self, path: Path, capsys, *extra: str) -> tuple[int, dict]:
        code = main(["access-log", "verify", str(path), *extra])
        return code, json.loads(capsys.readouterr().out)

    def _anchor(self, path: Path, capsys) -> str:
        code, verdict = self._verify(path, capsys)
        assert code == 0
        return verdict["anchor"]

    def test_verify_prints_the_anchor_as_the_last_line_and_its_digest(
        self, tmp_path: Path, capsys
    ) -> None:
        path = tmp_path / "access.log"
        log = _write(path, 3)
        log.close()
        assert self._anchor(path, capsys) == f"3:{log.head}"
        empty = tmp_path / "empty.log"
        empty.write_text("", encoding="utf-8")
        assert self._anchor(empty, capsys) == ""

    def test_a_log_that_grew_since_the_anchor_extends_it(self, tmp_path: Path, capsys) -> None:
        path = tmp_path / "access.log"
        _write(path, 3).close()
        anchor = self._anchor(path, capsys)
        _write(path, 2).close()
        code, verdict = self._verify(path, capsys, "--anchor", anchor)
        assert code == 0
        assert verdict["entries"] == 5 and verdict["extends"]["extended"] is True
        # Copied by hand, in capitals or with a space after the colon, it still reads.
        code, _ = self._verify(path, capsys, "--anchor", anchor.upper().replace(":", ": "))
        assert code == 0

    def test_a_tail_cut_off_verifies_alone_and_fails_the_anchor(
        self, tmp_path: Path, capsys
    ) -> None:
        path = tmp_path / "access.log"
        _write(path, 4).close()
        anchor = self._anchor(path, capsys)
        _rewrite(path, _lines(path)[:2])
        assert self._verify(path, capsys)[0] == 0
        code, verdict = self._verify(path, capsys, "--anchor", anchor)
        assert code == 4
        assert verdict["verified"] is True and verdict["extends"]["extended"] is False
        assert "removed from the end" in verdict["extends"]["reason"]

    def test_a_replaced_log_as_long_as_the_old_one_fails_the_anchor(
        self, tmp_path: Path, capsys
    ) -> None:
        # The server restarted on an emptied file and wrote as many lines again:
        # a fresh chain, whole and the same length, with none of the old lines.
        path = tmp_path / "access.log"
        _write(path, 3).close()
        anchor = self._anchor(path, capsys)
        path.unlink()
        log = AccessLog(path)
        for n in range(3):
            log.record(user=f"u{n}@x.example", user_tenant="sage-spine", method="GET",
                       path="/api/v1/me", status=200, at=AT)  # fmt: skip
        log.close()
        code, verdict = self._verify(path, capsys, "--anchor", anchor)
        assert code == 4 and verdict["verified"] is True
        assert "line 3 is not the line anchored" in verdict["extends"]["reason"]

    def test_a_consistently_rehashed_rewrite_fails_the_anchor(self, tmp_path: Path, capsys) -> None:
        # A success turned into a refusal and every digest after it recomputed:
        # the chain is whole again, and only the anchor still knows.
        path = tmp_path / "access.log"
        _write(path, 3).close()
        anchor = self._anchor(path, capsys)
        prev, rewritten = GENESIS_HASH, []
        for n, line in enumerate(_lines(path)):
            entry = json.loads(line)
            if n == 0:
                entry["status"] = 403
            entry["prev_hash"] = prev
            entry["hash"] = prev = line_digest(entry)
            rewritten.append(json.dumps(entry, sort_keys=True, separators=(",", ":")))
        _rewrite(path, rewritten)
        assert self._verify(path, capsys)[0] == 0
        code, verdict = self._verify(path, capsys, "--anchor", anchor)
        assert code == 4 and not verdict["extends"]["extended"]

    def test_a_broken_chain_is_not_held_to_the_anchor(self, tmp_path: Path, capsys) -> None:
        path = tmp_path / "access.log"
        _write(path, 2).close()
        anchor = self._anchor(path, capsys)
        lines = _lines(path)
        _rewrite(path, [lines[0].replace("user0@", "someone@"), lines[1]])
        code, verdict = self._verify(path, capsys, "--anchor", anchor)
        assert code == 4 and verdict["broken_at"] == 1 and "extends" not in verdict

    @pytest.mark.parametrize(
        "anchor",
        ["3", "0:" + "a" * 64, "-1:" + "a" * 64, "x:" + "a" * 64, "3:" + "a" * 63, "3:" + "g" * 64],
    )
    def test_an_anchor_that_is_not_n_colon_digest_is_bad_input(
        self, tmp_path: Path, capsys, anchor: str
    ) -> None:
        path = tmp_path / "access.log"
        _write(path, 3).close()
        assert main(["access-log", "verify", str(path), f"--anchor={anchor}"]) == 2
        captured = capsys.readouterr()
        assert captured.out == "" and "not an anchor" in captured.err


class TestRotation:
    """A rotated log runs on from its archive; a file cut or swapped still does not."""

    def _run(self, capsys, *argv: str) -> tuple[int, dict, str]:
        code = main(list(argv))
        captured = capsys.readouterr()
        return code, json.loads(captured.out) if captured.out else {}, captured.err

    def _rotate(self, capsys, log: Path, archive: Path) -> dict:
        code, out, err = self._run(
            capsys, "access-log", "rotate", str(log), "--to", str(archive), "--actor", "ops-1"
        )
        assert code == 0, err
        return out

    def test_the_archive_keeps_every_line_and_the_log_runs_on_from_it(
        self, tmp_path: Path, capsys
    ) -> None:
        log, archive = tmp_path / "access.log", tmp_path / "access.log.1"
        _write(log, 3).close()
        before = log.read_bytes()
        _, verdict, _ = self._run(capsys, "access-log", "verify", str(log))
        rotated = self._rotate(capsys, log, archive)
        assert archive.read_bytes() == before
        assert rotated["archive_anchor"] == verdict["anchor"]
        (line,) = [json.loads(text) for text in _lines(log)]
        assert (line["seq"], line["prev_hash"]) == (4, verdict["head"])
        assert (line["rotated_from"], line["rotated_by"]) == ("access.log.1", "ops-1")
        assert rotated["anchor"] == f"4:{line['hash']}"
        # The new file alone is whole, and says where it begins.
        alone = verify_file(log)
        assert alone["verified"] and alone["first"] == 4
        assert alone["continues"] == verdict["anchor"]
        # A server reopening it carries on the numbering.
        reopened = _write(log, 2)
        reopened.close()
        assert [json.loads(text)["seq"] for text in _lines(log)] == [4, 5, 6]
        code, both, _ = self._run(capsys, "access-log", "verify", str(archive), str(log))
        assert code == 0
        assert (both["entries"], both["anchor"]) == (6, f"6:{reopened.head}")
        # Read alone, the rotated file is numbered by the chain, not by its own lines.
        _, alone_cli, _ = self._run(capsys, "access-log", "verify", str(log))
        assert (alone_cli["entries"], alone_cli["anchor"]) == (3, f"6:{reopened.head}")
        # And rotated again, its archive is anchored the same way.
        again = self._rotate(capsys, log, tmp_path / "access.log.2")
        assert again["archive_anchor"] == f"6:{reopened.head}"

    def test_an_anchor_from_before_the_rotation_needs_the_archive(
        self, tmp_path: Path, capsys
    ) -> None:
        log, archive = tmp_path / "access.log", tmp_path / "access.log.1"
        _write(log, 2).close()
        _, early, _ = self._run(capsys, "access-log", "verify", str(log))
        _write(log, 1).close()
        rotated = self._rotate(capsys, log, archive)
        _write(log, 1).close()
        code, alone, _ = self._run(
            capsys, "access-log", "verify", str(log), "--anchor", early["anchor"]
        )
        assert code == 4 and alone["verified"] is True
        assert "give the archives" in alone["extends"]["reason"]
        code, both, _ = self._run(
            capsys, "access-log", "verify", str(archive), str(log), "--anchor", early["anchor"]
        )
        assert code == 0 and both["extends"]["extended"] is True
        # The archive's own last line is the one the rotation line vouches for.
        code, _, _ = self._run(
            capsys, "access-log", "verify", str(log), "--anchor", rotated["archive_anchor"]
        )
        assert code == 0

    def test_lines_cut_from_the_front_are_still_broken(self, tmp_path: Path) -> None:
        log = tmp_path / "access.log"
        _write(log, 3).close()
        _rewrite(log, _lines(log)[1:])
        verdict = verify_file(log)
        assert (verdict["verified"], verdict["broken_at"]) == (False, 1)
        assert "where 1 was expected" in verdict["reason"]

    def test_a_forged_rotation_line_does_not_hold_an_anchor_it_never_saw(
        self, tmp_path: Path, capsys
    ) -> None:
        # The log replaced by a file claiming to follow a rotation at the
        # anchored line: whole on its own, and the digest gives it away.
        log = tmp_path / "access.log"
        _write(log, 3).close()
        _, verdict, _ = self._run(capsys, "access-log", "verify", str(log))
        forged: dict = {"seq": 4, "at": "2026-09-27T00:00:00.000Z", "rotated_from": "gone.log",
                        "rotated_by": "x", "prev_hash": "b" * 64}  # fmt: skip
        forged["hash"] = line_digest(forged, ROTATION_FIELDS)
        _rewrite(log, [json.dumps(forged)])
        assert verify_file(log)["verified"] is True
        code, out, _ = self._run(
            capsys, "access-log", "verify", str(log), "--anchor", verdict["anchor"]
        )
        assert code == 4
        assert "line 3 is not the line anchored" in out["extends"]["reason"]

    def test_an_archive_left_out_or_out_of_order_breaks_the_join(
        self, tmp_path: Path, capsys
    ) -> None:
        log, first, second = (tmp_path / n for n in ("access.log", "a.1", "a.2"))
        _write(log, 2).close()
        self._rotate(capsys, log, first)
        _write(log, 2).close()
        self._rotate(capsys, log, second)
        _write(log, 1).close()
        code, whole, _ = self._run(
            capsys, "access-log", "verify", str(first), str(second), str(log)
        )
        assert code == 0 and whole["entries"] == 7
        for order in ((first, log), (second, first, log), (first, first, second, log)):
            code, out, _ = self._run(capsys, "access-log", "verify", *map(str, order))
            assert code == 4 and out["verified"] is False
            assert "does not chain" in out["reason"] or "was expected" in out["reason"]

    def test_a_server_still_writing_is_found_not_lost(self, tmp_path: Path) -> None:
        log, archive = tmp_path / "access.log", tmp_path / "access.log.1"
        running = _write(log, 2)
        try:
            rotate(log, archive, actor="ops-1")
        except AccessLogError:
            # Where an open file cannot be replaced (Windows), nothing moved.
            running.close()
            assert not archive.exists() and verify_file(log)["entries"] == 2
            return
        running.record(user="late@sage.example", user_tenant="sage-spine", method="GET",
                       path="/api/v1/me", status=200, at=AT)  # fmt: skip
        running.close()
        # The late line is in the archive, and the join names where it went wrong.
        assert json.loads(_lines(archive)[-1])["user"] == "late@sage.example"
        verdict, entries = read_files([archive, log])
        assert verdict["verified"] is False and entries == []
        assert verdict["reason"] == f"{log} line 1: sequence 3 where 4 was expected"

    def test_what_is_refused(self, tmp_path: Path, capsys) -> None:
        log, archive = tmp_path / "access.log", tmp_path / "access.log.1"
        _write(log, 2).close()
        archive.write_text("kept\n", encoding="utf-8")
        before = log.read_bytes()
        rotate_args = ("access-log", "rotate", str(log), "--actor", "ops-1", "--to")
        code, out, err = self._run(capsys, *rotate_args, str(archive))
        assert (code, out) == (2, {}) and "never overwritten" in err
        assert archive.read_text(encoding="utf-8") == "kept\n" and log.read_bytes() == before
        code, _, err = self._run(capsys, *rotate_args, str(log))
        assert code == 2 and "another file" in err
        with pytest.raises(AccessLogError, match="names who"):
            rotate(log, tmp_path / "a.2", actor=" ")
        empty = tmp_path / "empty.log"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(AccessLogError, match="no lines to rotate"):
            rotate(empty, tmp_path / "a.3", actor="ops-1")
        lines = _lines(log)
        _rewrite(log, [lines[0].replace("user0@", "someone@"), lines[1]])
        code, _, err = self._run(capsys, *rotate_args, str(tmp_path / "a.4"))
        assert code == 4 and "evidence" in err and not (tmp_path / "a.4").exists()
        code, _, err = self._run(capsys, "access-log", "rotate", str(tmp_path / "none.log"),
                                 "--actor", "ops-1", "--to", str(tmp_path / "a.5"))  # fmt: skip
        assert code == 2 and "not found" in err


class TestRefusals:
    """Who was refused one tenant's workspace, from the verified log alone."""

    SAGE = "/api/v1/tenants/sage-spine"

    @staticmethod
    def _log(path: Path, *lines: tuple[str | None, str | None, str, int, str]) -> Path:
        log = AccessLog(path)
        for user, tenant, where, status, day in lines:
            log.record(
                user=user, user_tenant=tenant, method="GET", path=where, status=status,
                at=datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
            )  # fmt: skip
        log.close()
        return path

    def test_callers_are_grouped_and_ranked(self, tmp_path: Path) -> None:
        path = self._log(
            tmp_path / "access.log",
            ("staff@sage.example", "sage-spine", self.SAGE + "/assessments", 200,
             "2026-09-20T10:00:00"),
            (None, None, self.SAGE + "/assessments", 401, "2026-09-20T11:00:00"),
            ("viewer@sage.example", "sage-spine", self.SAGE + "/oversight/partners", 403,
             "2026-09-21T09:00:00"),
            ("nurse@other.example", "other-clinic", self.SAGE + "/audit", 403,
             "2026-09-22T09:00:00"),
            ("nurse@other.example", "other-clinic", self.SAGE + "/assessments", 403,
             "2026-09-23T09:00:00"),
            (None, None, self.SAGE + "/audit", 401, "2026-09-24T09:00:00"),
        )  # fmt: skip
        _, entries = read_files([path])
        report = refusals(entries, "sage-spine", date(2026, 9, 27))
        assert {k: report[k] for k in ("requests", "refused", "high", "notices")} == {
            "requests": 6,
            "refused": 5,
            "high": 1,
            "notices": 2,
        }
        assert (report["from"], report["to"]) == (
            "2026-09-20T10:00:00.000Z",
            "2026-09-24T09:00:00.000Z",
        )
        assert [(g["caller"], g["user"], g["requests"], g["level"]) for g in report["callers"]] == [
            ("other_tenant", "nurse@other.example", 2, "high"),
            ("unauthenticated", None, 2, "notice"),
            ("member", "viewer@sage.example", 1, "notice"),
        ]
        nurse = report["callers"][0]
        assert (nurse["first"], nurse["last"], nurse["statuses"]) == (
            "2026-09-22T09:00:00.000Z",
            "2026-09-23T09:00:00.000Z",
            [403],
        )
        assert nurse["paths"] == [self.SAGE + "/assessments", self.SAGE + "/audit"]

    def test_only_this_workspace_up_to_the_date_counts(self, tmp_path: Path) -> None:
        path = self._log(
            tmp_path / "access.log",
            # Another tenant's workspace, a prefix of this one's name, and no workspace.
            (None, None, "/api/v1/tenants/other-clinic/audit", 401, "2026-09-20T10:00:00"),
            (None, None, "/api/v1/tenants/sage-spine-2/audit", 401, "2026-09-20T10:00:00"),
            (None, None, "/api/v1/me", 401, "2026-09-20T10:00:00"),
            # Encoded, and still this workspace.
            (None, None, "/api/v1/tenants/sage%2Dspine/audit", 401, "2026-09-21T10:00:00"),
            # 23:30 in New York on the 27th is the 28th in UTC: after the review.
            (None, None, self.SAGE + "/audit", 401, "2026-09-28T03:30:00"),
        )  # fmt: skip
        rotated = tmp_path / "access.log.1"
        rotate(path, rotated, actor="ops-1")
        _, entries = read_files([rotated, path])
        report = refusals(entries, "sage-spine", date(2026, 9, 27))
        assert (report["requests"], report["refused"]) == (1, 1)
        assert report["callers"][0]["paths"] == ["/api/v1/tenants/sage%2Dspine/audit"]
        assert refusals(entries, "sage-spine", date(2026, 9, 28))["refused"] == 2
        assert refusals(entries, "other-clinic", date(2026, 9, 27))["refused"] == 1

    def test_a_caller_trying_many_paths_is_one_group(self, tmp_path: Path) -> None:
        probes = [
            ("x@other.example", "other-clinic", f"{self.SAGE}/oversight/partners/p{n:02d}", 403,
             "2026-09-22T09:00:00")
            for n in range(MAX_PATHS + 5)
        ]  # fmt: skip
        _, entries = read_files([self._log(tmp_path / "access.log", *probes)])
        (group,) = refusals(entries, "sage-spine", date(2026, 9, 27))["callers"]
        assert group["requests"] == MAX_PATHS + 5
        assert len(group["paths"]) == MAX_PATHS and group["more_paths"] == 5

    def test_the_command(self, tmp_path: Path, capsys) -> None:
        path = self._log(
            tmp_path / "access.log",
            (None, None, self.SAGE + "/audit", 401, "2026-09-21T10:00:00"),
        )  # fmt: skip

        def run(*argv: str) -> tuple[int, dict, str]:
            code = main(["access-log", "refusals", *argv])
            out, err = capsys.readouterr()
            return code, (json.loads(out) if out.strip() else {}), err

        base = (str(path), "--tenant", "sage-spine", "--as-of", "2026-09-27")
        code, report, _ = run(*base)
        assert (code, report["refused"], report["high"]) == (0, 1, 0)
        assert report["anchor"] == f"1:{json.loads(_lines(path)[0])['hash']}"
        assert run(*base, "--fail-on", "high")[0] == 0
        assert run(*base, "--fail-on", "any")[0] == 4
        other = self._log(
            tmp_path / "other.log",
            ("x@other.example", "other-clinic", self.SAGE + "/audit", 403, "2026-09-21T10:00:00"),
        )  # fmt: skip
        assert run(str(other), *base[1:], "--fail-on", "high")[0] == 4
        # Refused, not reviewed: a broken chain, a bad tenant, a bad date, no file.
        lines = _lines(path)
        _rewrite(path, [lines[0].replace('"status":401', '"status":200')])
        code, report, err = run(*base)
        assert (code, report) == (4, {}) and "not a whole chain" in err
        assert run(str(other), "--tenant", "Sage Spine")[0] == 2
        assert run(str(other), "--tenant", "sage-spine", "--as-of", "2026-02-30")[0] == 2
        assert run(str(tmp_path / "none.log"), "--tenant", "sage-spine")[0] == 2
