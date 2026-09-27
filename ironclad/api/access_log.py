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
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64

#: The keys every line carries, in addition to `hash`. A line with any other
#: key, or without one of these, is not one this module wrote.
FIELDS = ("seq", "at", "user", "user_tenant", "method", "path", "status", "prev_hash")


class AccessLogError(Exception):
    """The log cannot be read, is not a chain, or cannot be written."""


def line_digest(entry: dict[str, Any], fields: tuple[str, ...] = FIELDS) -> str:
    payload = {key: entry[key] for key in fields}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _broken(line: int, reason: str, head: str) -> dict[str, Any]:
    return {
        "entries": line - 1,
        "verified": False,
        "broken_at": line,
        "reason": reason,
        "head": head,
    }


def verify_lines(
    lines: list[str], fields: tuple[str, ...] = FIELDS, kind: str = "an access-log entry"
) -> dict[str, Any]:
    """Re-check a chain. `broken_at` is the 1-based line of the first fault.

    `fields` and `kind` let another chained log (the grant ledger) share the check.
    """
    prev = GENESIS_HASH
    for number, line in enumerate(lines, start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return _broken(number, "not a JSON object", prev)
        if not isinstance(entry, dict) or set(entry) != {*fields, "hash"}:
            return _broken(number, f"not {kind}", prev)
        if entry["seq"] != number:
            return _broken(number, f"sequence {entry['seq']!r} where {number} was expected", prev)
        if entry["prev_hash"] != prev:
            return _broken(number, "does not chain from the line before", prev)
        if entry["hash"] != line_digest(entry, fields):
            return _broken(number, "edited since it was written", prev)
        prev = entry["hash"]
    return {"entries": len(lines), "verified": True, "broken_at": None, "reason": "", "head": prev}


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
    return verify_lines(read_lines(Path(path)))


def read_file(path: Path | str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The verdict on one log file and, only if it is a whole chain, its entries.

    Read once, so the entries are the lines the verdict was reached on. A log
    that is not a whole chain yields no entries: anything built on it would
    rest on lines someone may have edited.
    """
    lines = read_lines(Path(path))
    verdict = verify_lines(lines)
    if not verdict["verified"]:
        return verdict, []
    return verdict, [json.loads(line) for line in lines]


def anchor_of(verdict: dict[str, Any]) -> str:
    """`N:DIGEST` for a whole chain of N lines: the value to record elsewhere.

    Empty for an empty or broken chain, which has nothing worth anchoring.
    """
    if not verdict["verified"] or not verdict["entries"]:
        return ""
    return f"{verdict['entries']}:{verdict['head']}"


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


def check_anchor(lines: list[str], anchor: str) -> dict[str, Any]:
    """Does a chain still hold the line an earlier `anchor_of` recorded?

    The chain alone cannot see lines removed from the end, or the file
    replaced by a new one (a server restarted on an empty file starts a fresh,
    whole chain). An anchor taken earlier and kept elsewhere can: line N must
    still be there and still carry the digest recorded for it. Because each
    digest covers the one before, that one comparison vouches for lines 1..N.

    Call it only on lines `verify_lines` found whole. Raises `ValueError` for
    an anchor that is not `N:DIGEST`.
    """
    seq, digest = parse_anchor(anchor)
    result = {"anchor": f"{seq}:{digest}", "extended": False, "reason": ""}
    if len(lines) < seq:
        result["reason"] = (
            f"the anchor was taken at line {seq} and the file now has {len(lines)}: "
            "lines were removed from the end, or the file was replaced"
        )
        return result
    if json.loads(lines[seq - 1])["hash"] != digest:
        result["reason"] = (
            f"line {seq} is not the line anchored: the file was rewritten at or before "
            "that line, or replaced"
        )
        return result
    result["extended"] = True
    return result


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
        self._seq = verdict["entries"]
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
