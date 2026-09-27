"""Who asked `ironclad serve` for what, and what they were told.

The register's history says who *changed* a record. Nothing said who *read*
one, or who was refused: a partner's token probing another tenant's register
left a 403 on stderr with no name attached. HIPAA's audit-controls standard
(45 CFR 164.312(b)) asks for a record of activity in systems holding ePHI,
reads and refusals included, so the server can now keep one.

One JSON object per line, appended, each carrying the digest of the line
before it — the same chain as `ironclad.model.audit`, so deleting, editing or
reordering a line breaks every digest after it and `verify_file` says where.
A line holds the time, the authenticated user and their tenant (or none),
the method, the path, and the status. Never the query string (a filter a
client typed), the body (a record's contents) or any header.

The chain is only as good as where the file is kept and who can write it.
It cannot see lines cut from the end, or the file replaced by a new one, so
the anchor (`N:DIGEST`, the last line's number and digest) is the value to
copy somewhere else, as with the register seal; `check_anchor` holds a later
file to it. One server per file: two processes appending to one log would
each chain from their own head.

A log is rotated with `rotate`, never by moving the file: the current file is
copied to an archive, and the new file starts with one rotation line that
carries the next sequence number and the old file's last digest. The chain
therefore runs on across files, and `read_files` verifies the archives and
the current file, oldest first, as one. Only a rotation line may begin a file
mid-chain, so a log with lines cut from the front is still broken, and a
rotated log given without the archive that holds an earlier anchor cannot
vouch for it.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64

#: The keys every line carries, in addition to `hash`. A line with any other
#: key, or without one of these, is not one this module wrote.
FIELDS = ("seq", "at", "user", "user_tenant", "method", "path", "status", "prev_hash")

#: The keys of the rotation line `rotate` writes first in the new file.
ROTATION_FIELDS = ("seq", "at", "rotated_from", "rotated_by", "prev_hash")


class AccessLogError(Exception):
    """The log cannot be read, is not a chain, or cannot be written."""


def line_digest(entry: dict[str, Any], fields: tuple[str, ...] = FIELDS) -> str:
    payload = {key: entry[key] for key in fields}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _broken(line: int, reason: str, head: str, first: int, continues: str) -> dict[str, Any]:
    return {
        "entries": line - 1,
        "verified": False,
        "broken_at": line,
        "reason": reason,
        "head": head,
        "first": first,
        "continues": continues,
    }


def is_rotation(entry: dict[str, Any]) -> bool:
    """A rotation line `rotate` wrote, rather than a request."""
    return "rotated_from" in entry


def requests(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The request lines of a verified log, rotation lines left out."""
    return [entry for entry in entries if not is_rotation(entry)]


def verify_lines(
    lines: list[str],
    fields: tuple[str, ...] = FIELDS,
    kind: str = "an access-log entry",
    *,
    rotatable: bool = False,
) -> dict[str, Any]:
    """Re-check a chain. `broken_at` is the 1-based line of the first fault.

    `fields` and `kind` let another chained log (the grant ledger) share the check.
    With `rotatable` (the access log), a rotation line is accepted wherever the
    chain runs on through it, and as the first line it sets where the chain
    starts: `first` is its sequence number and `continues` the anchor
    (`N:DIGEST`) of the archive it follows. Any other first line starts at 1
    from the genesis digest, so lines cut from the front still break it.
    """
    prev = GENESIS_HASH
    first = 1
    continues = ""
    for number, line in enumerate(lines, start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return _broken(number, "not a JSON object", prev, first, continues)
        rotation = (
            rotatable and isinstance(entry, dict) and set(entry) == {*ROTATION_FIELDS, "hash"}
        )
        expected = ROTATION_FIELDS if rotation else fields
        if not isinstance(entry, dict) or set(entry) != {*expected, "hash"}:
            return _broken(number, f"not {kind}", prev, first, continues)
        seq = entry["seq"]
        if number == 1 and rotation:
            digest = entry["prev_hash"]
            if not isinstance(seq, int) or isinstance(seq, bool) or seq < 2:
                return _broken(number, f"a rotation line at sequence {seq!r}", prev, first, "")
            if not isinstance(digest, str) or len(digest) != 64:
                return _broken(number, "a rotation line with no digest to follow", prev, first, "")
            first, prev, continues = seq, digest, f"{seq - 1}:{digest}"
        if seq != first + number - 1:
            expected_seq = first + number - 1
            reason = f"sequence {seq!r} where {expected_seq} was expected"
            return _broken(number, reason, prev, first, continues)
        if entry["prev_hash"] != prev:
            return _broken(number, "does not chain from the line before", prev, first, continues)
        if entry["hash"] != line_digest(entry, expected):
            return _broken(number, "edited since it was written", prev, first, continues)
        prev = entry["hash"]
    return {
        "entries": len(lines),
        "verified": True,
        "broken_at": None,
        "reason": "",
        "head": prev,
        "first": first,
        "continues": continues,
    }


def read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise AccessLogError(f"cannot read {path}: {exc}") from exc
    # A file that does not end in a newline was cut off mid-write; the partial
    # line is kept so verification names it rather than skipping it.
    return text.splitlines()


def verify_file(path: Path | str) -> dict[str, Any]:
    """The verdict on one log file. A missing file is an empty, whole chain."""
    return verify_lines(read_lines(Path(path)), rotatable=True)


def read_file(path: Path | str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The verdict on one log file and, only if it is a whole chain, its entries.

    Read once, so the entries are the lines the verdict was reached on. A log
    that is not a whole chain yields no entries: anything built on it would
    rest on lines someone may have edited. Rotation lines are among the
    entries, since anchors are checked on them; `requests()` leaves them out.
    """
    return read_files([path])


def read_files(paths: Sequence[Path | str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Archives and the current log, oldest first, verified as one chain.

    Each file after the first must begin with the rotation line that follows
    the one before, so an archive left out of the middle, given twice or out of
    order breaks the chain where it should have joined. `files` names each file
    and its line count; a break across files is named by file and line in
    `reason`, while `broken_at` counts lines across all of them.
    """
    lines: list[str] = []
    files: list[dict[str, Any]] = []
    for path in paths:
        own = read_lines(Path(path))
        files.append({"path": str(path), "lines": len(own)})
        lines.extend(own)
    verdict = verify_lines(lines, rotatable=True)
    verdict["files"] = files
    if not verdict["verified"]:
        if len(files) > 1:
            line = verdict["broken_at"]
            for file in files:
                if line <= file["lines"]:
                    verdict["reason"] = f"{file['path']} line {line}: {verdict['reason']}"
                    break
                line -= file["lines"]
        return verdict, []
    return verdict, [json.loads(line) for line in lines]


def anchor_of(verdict: dict[str, Any]) -> str:
    """`N:DIGEST` for a whole chain whose last line is N: the value to record elsewhere.

    Empty for an empty or broken chain, which has nothing worth anchoring.
    """
    if not verdict["verified"] or not verdict["entries"]:
        return ""
    return f"{verdict.get('first', 1) + verdict['entries'] - 1}:{verdict['head']}"


def parse_anchor(text: str) -> tuple[int, str]:
    """`N:DIGEST` as `anchor_of` writes it. Raises `ValueError` otherwise."""
    seq, sep, digest = text.strip().partition(":")
    digest = digest.strip().lower()
    if (
        not sep
        or not seq.isdigit()
        or int(seq) < 1
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError(f"not an anchor: {text!r}; expected N:DIGEST as verify prints it")
    return int(seq), digest


def check_anchor(entries: list[dict[str, Any]], anchor: str) -> dict[str, Any]:
    """Does a chain still hold the line an earlier `anchor_of` recorded?

    The chain alone cannot see lines removed from the end, or the file
    replaced by a new one (a server restarted on an empty file starts a fresh,
    whole chain). An anchor taken earlier and kept elsewhere can: line N must
    still be there and still carry the digest recorded for it. Because each
    digest covers the one before, that one comparison vouches for lines 1..N.
    A chain that begins with a rotation line holds its lines by sequence
    number, and the line before its first by the digest the rotation line
    follows; an anchor earlier than that needs the archives given as well.

    Call it only on the parsed entries of a chain `verify_lines` found whole.
    Raises `ValueError` for an anchor that is not `N:DIGEST`.
    """
    seq, digest = parse_anchor(anchor)
    result = {"anchor": f"{seq}:{digest}", "extended": False, "reason": ""}
    first = entries[0]["seq"] if entries else 1
    last = first + len(entries) - 1
    if seq < first - 1:
        result["reason"] = (
            f"the anchor was taken at line {seq} and this log begins at line {first}, "
            "after a rotation: give the archives that hold it, oldest first"
        )
        return result
    if seq > last:
        result["reason"] = (
            f"the anchor was taken at line {seq} and the log now ends at line {last}: "
            "lines were removed from the end, or the file was replaced"
        )
        return result
    held = entries[0]["prev_hash"] if seq == first - 1 else entries[seq - first]["hash"]
    if held != digest:
        result["reason"] = (
            f"line {seq} is not the line anchored: the log was rewritten at or before "
            "that line, or replaced"
        )
        return result
    result["extended"] = True
    return result


def rotate(
    path: Path | str, archive: Path | str, *, actor: str, at: datetime | None = None
) -> dict[str, Any]:
    """Move a log's lines to `archive` and start `path` again from its head.

    Run only while no server holds the log. The log must be a whole chain with
    at least one line, and the archive must not exist: it is made a hard link
    to the log, which is exclusive, so an archive is never overwritten. The
    log is then replaced whole by one rotation line carrying the next sequence
    number and the old head, so the log is never missing and the chain never
    starts afresh. A server still appending holds the old file, which is now
    the archive: its lines land there, past the head the rotation line
    follows, and break the chain where the archive and the log join. They are
    found, not lost. If the log cannot be replaced, the archive link is
    removed and the log is as it was.
    """
    path, archive = Path(path), Path(archive)
    if not actor.strip():
        raise AccessLogError("a rotation names who rotated the log (--actor)")
    if archive.resolve() == path.resolve():
        raise AccessLogError("the archive must be another file than the log")
    if not path.is_file():
        raise AccessLogError(f"access log not found: {path}")
    verdict = verify_file(path)
    if not verdict["verified"]:
        raise AccessLogError(
            f"{path} is not a whole chain at line {verdict['broken_at']} "
            f"({verdict['reason']}); it is evidence, not something to rotate"
        )
    if not verdict["entries"]:
        raise AccessLogError(f"{path} has no lines to rotate")
    try:
        os.link(path, archive)
    except FileExistsError:
        raise AccessLogError(f"{archive} already exists; an archive is never overwritten") from None
    except OSError as exc:
        raise AccessLogError(f"cannot archive {path} as {archive}: {exc}") from exc
    moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    entry: dict[str, Any] = {
        "seq": verdict["first"] + verdict["entries"],
        "at": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "rotated_from": archive.name,
        "rotated_by": actor.strip(),
        "prev_hash": verdict["head"],
    }
    entry["hash"] = line_digest(entry, ROTATION_FIELDS)
    temp = path.with_name(path.name + ".rotating")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    except OSError as exc:
        # Undo: the log stays whole and in place, and the archive name is free again.
        temp.unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
        raise AccessLogError(f"cannot start {path} again: {exc}") from exc
    return {
        "archive": str(archive),
        "archive_anchor": anchor_of(verdict),
        "log": str(path),
        "anchor": f"{entry['seq']}:{entry['hash']}",
        "rotated_by": entry["rotated_by"],
    }


class AccessLog:
    """Appends one chained line per API request. Safe across handler threads.

    Opening a log re-checks the whole file first and refuses one that is not a
    whole chain: appending to a broken log would bury the break under entries
    that verify from a head nobody can trust. The operator moves the broken
    file aside (it is the evidence) and starts a new one.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        verdict = verify_file(self.path)
        if not verdict["verified"]:
            raise AccessLogError(
                f"{self.path} is not a whole chain at line {verdict['broken_at']} "
                f"({verdict['reason']}); move it aside and start a new log"
            )
        self._seq = verdict["first"] + verdict["entries"] - 1
        self._head = verdict["head"]
        self._lock = threading.Lock()
        try:
            self._file = self.path.open("a", encoding="utf-8", newline="\n")
        except OSError as exc:
            raise AccessLogError(f"cannot append to {self.path}: {exc}") from exc

    @property
    def head(self) -> str:
        return self._head

    def record(
        self,
        *,
        user: str | None,
        user_tenant: str | None,
        method: str,
        path: str,
        status: int,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        """Write one line and make it durable before returning it.

        Raises `AccessLogError` if the line cannot be written; the server then
        refuses to answer rather than answer unrecorded.
        """
        moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._lock:
            entry: dict[str, Any] = {
                "seq": self._seq + 1,
                "at": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "user": user,
                "user_tenant": user_tenant,
                "method": method,
                "path": path,
                "status": int(status),
                "prev_hash": self._head,
            }
            entry["hash"] = line_digest(entry)
            line = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            try:
                self._file.write(line + "\n")
                self._file.flush()
                os.fsync(self._file.fileno())
            except (OSError, ValueError) as exc:
                raise AccessLogError(f"cannot append to {self.path}: {exc}") from exc
            self._seq += 1
            self._head = entry["hash"]
            return entry

    def close(self) -> None:
        with self._lock:
            self._file.close()
