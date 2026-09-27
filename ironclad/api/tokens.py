"""Service tokens: when one stops working, and a review of who holds one.

A token file entry grants a person or an integration partner access to one
tenant's workspace. Before this module an entry granted it for ever: a partner
whose contract ended kept a working token until someone remembered to edit the
file, and nothing could list who held access without reading raw JSON.
HIPAA's workforce-clearance and termination procedures (164.308(a)(3)(ii)(B)
and (C)) and its access review (164.308(a)(4)) want both answered.

`expires_at` is an ISO calendar date, `YYYY-MM-DD`. The token works through
the end of that day in UTC and is refused from the next. An entry without one
does not expire, which is how every file written before this reads; the review
reports it so it is a choice rather than an accident. An `expires_at` that is
not a calendar date authenticates nobody: a typo in an expiry must not become
access that never ends.

`review_tokens()` is the access review. It reads a token file's digests and
never needs a token, so an operator can run it anywhere the file is. Given the
server's access log as well, it says when each entry was last used and which
were refused: a token nobody has used in `DORMANT_DAYS` is access to remove,
not to keep in case (164.308(a)(4)(ii)(C), access modification), and a run of
403s is a caller reaching for what their role or tenant does not allow.

`issue_token()` and `revoke_tokens()` are the only edits an operator should
need, so the file is not written by hand. An issued entry always ends, within
`MAX_TERM_DAYS`, and names who granted it and when; a renewal is a new token
issued after the old entry is revoked, so a credential never outlives its
term. `write_token_file()` replaces the file whole, under an exclusive lock
file, so the server (which re-reads it per request) sees the old file or the
new one and never half of one, and two operators cannot each lose the other's
edit. Each edit goes on the grant ledger first (`ironclad.api.grant_ledger`),
so the grant outlives the entry, and a review given the ledger finds entries
nobody granted.

An entry issued to an integration partner can name the register record it acts
for, `on_behalf_of: "partners/<id>"` or `"integrations/<id>"`. The token file
cannot see the register, so it only checks the form; `ironclad oversight
access` holds each linked entry to its record: access for a partner the
register does not hold, has retired, or lets handle PHI without an executed BAA
is access a business-associate review would remove. The server refuses the
first two itself (`ironclad.api.http.TokenFileAuthenticator`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ironclad.ids import slugify
from ironclad.model.tenant import Role

#: A token expiring within this many days is reported as a notice, so its
#: renewal or removal is decided before it lapses, not after.
EXPIRY_WARNING_DAYS = 30

#: An active entry with no recorded request in this many days is reported as
#: dormant. The window is ours, not HIPAA's; `--dormant-days` changes it.
DORMANT_DAYS = 90

#: The longest term `issue_token` grants. Ours, not HIPAA's: a year keeps
#: every grant inside one annual access review.
MAX_TERM_DAYS = 365

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_ROLES = frozenset(member.value for member in Role)
_ON_BEHALF_OF = re.compile(r"^(partners|integrations)/[A-Za-z0-9_-]{1,128}$")


def parse_on_behalf_of(value: object) -> tuple[str, str] | None:
    """`(kind, record_id)` for a well-formed link, `None` for none, else ValueError."""
    if value is None or value == "":
        return None
    text = str(value)
    if not _ON_BEHALF_OF.match(text):
        raise ValueError(
            f"on_behalf_of {value!r} is not partners/<record-id> or integrations/<record-id>"
        )
    kind, record_id = text.split("/", 1)
    return kind, record_id


def link_withdrawn(register: Any, tenant_id: str, kind: str, record_id: str) -> str | None:
    """Why the register withholds access acting for `kind/record_id`, or `None`.

    One rule for `serve` and for `tokens issue`: the token's own tenant must
    hold the record, and it must not be `Retired`. A link to another tenant's
    record is a record this tenant does not hold. `register` is a store with
    `get_oversight`; whatever it raises is left to the caller.
    """
    link = f"{kind}/{record_id}"
    record = register.get_oversight(tenant_id, kind, record_id)
    if record is None:
        return f"the register does not hold {link}"
    if str(record.get("status", "")) == "Retired":
        return f"{link} is retired in the register"
    return None


class InvalidExpiryError(ValueError):
    """An `expires_at` that is present and is not a calendar date."""


def parse_expiry(value: object) -> date | None:
    """The last day a token works, `None` for no expiry, or `InvalidExpiryError`."""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not _ISO_DATE.match(text):
        raise InvalidExpiryError(f"expires_at {value!r} is not YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise InvalidExpiryError(f"expires_at {value!r} is not a calendar date") from exc


def is_expired(last_day: date | None, now: datetime) -> bool:
    """True once `now` (UTC) is past the end of `last_day`."""
    if last_day is None:
        return False
    return now.astimezone(timezone.utc).date() > last_day


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def review_tokens(
    document: object,
    as_of: date,
    access_log: list[dict[str, Any]] | None = None,
    dormant_days: int = DORMANT_DAYS,
    ledger: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Every entry in a token file, what it grants and what is wrong with it.

    One item per entry, in file order: the user, tenant, recognised roles,
    expiry, a `state` (`active`, `expiring`, `expired`, `refused`) and its
    findings, each `high` or `notice`. `high` means the entry grants access it
    should not, or is broken so that it grants none and someone thinks it does.
    Only the first 12 hex characters of a digest are shown, enough to find the
    entry and not the whole stored value.

    `access_log` is the entries of a verified log (`access_log.read_file`).
    With it, each entry gains `requests`, `refused` and `last_used`, matched
    on the user and tenant the log names (the log holds no digest), counting
    only lines on or before `as_of`. Notices: an active entry with no request
    in `dormant_days`, and an entry that was refused with 403.

    `ledger` is the entries of a verified grant ledger (`grant_ledger.read_file`).
    With it, an entry with no grant on record, one that differs from its grant,
    or one revoked and back in the file is high; a matching entry gains
    `granted_by` and `granted_at`; and a grant whose entry is gone with no
    revocation on record is listed under `ledger.unrecorded` as a notice.
    """
    entries = document.get("tokens") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise ValueError('not a token file: expected {"tokens": [...]}')

    digests = Counter(
        str(e.get("sha256", "")).strip().lower() for e in entries if isinstance(e, dict)
    )
    items: list[dict[str, Any]] = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            items.append(
                {
                    "entry": position,
                    "state": "refused",
                    "findings": [{"level": "high", "message": "entry is not an object"}],
                }
            )
            continue
        items.append(_review_entry(position, entry, digests, as_of))

    log_summary: dict[str, Any] | None = None
    if access_log is not None:
        if dormant_days < 1:
            raise ValueError("dormant_days must be at least 1")
        usage, log_summary = _usage(access_log, as_of)
        log_summary["dormant_days"] = dormant_days
        for item in items:
            if "tenant_id" in item:
                _apply_usage(item, usage, log_summary["from"], as_of, dormant_days)

    unrecorded: list[dict[str, Any]] | None = None
    if ledger is not None:
        from ironclad.api.grant_ledger import reconcile  # noqa: PLC0415

        held = reconcile(document, ledger)
        unrecorded = held["unrecorded"]
        for item, messages, grant in zip(items, held["findings"], held["granted"], strict=True):
            item["findings"][:0] = [{"level": "high", "message": m} for m in messages]
            if grant:
                item.update(grant)

    counts = Counter(item["state"] for item in items)
    review: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "entries": len(items),
        "active": counts["active"] + counts["expiring"],
        "high": sum(1 for i in items if any(f["level"] == "high" for f in i["findings"])),
        "notices": sum(1 for i in items if any(f["level"] == "notice" for f in i["findings"]))
        + len(unrecorded or []),
        "tenants": sorted(
            {
                str(i.get("tenant_id", ""))
                for i in items
                if i["state"] in ("active", "expiring") and i.get("tenant_id")
            }
        ),
        "items": items,
    }
    if log_summary is not None:
        review["access_log"] = log_summary
        review["dormant"] = sum(1 for i in items if i.get("dormant"))
    if ledger is not None:
        review["ledger"] = {"entries": len(ledger), "unrecorded": unrecorded}
    return review


def _at(entry: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(entry["at"]).replace("Z", "+00:00"))


def _usage(
    access_log: list[dict[str, Any]], as_of: date
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    """Requests per (user, tenant) up to the end of `as_of`, and the log's span."""
    usage: dict[tuple[str, str], dict[str, Any]] = {}
    first: str | None = None
    last: str | None = None
    counted = 0
    for entry in access_log:
        if "rotated_from" in entry:
            continue  # a rotation line (`access_log.rotate`), not a request
        moment = _at(entry)
        if moment.astimezone(timezone.utc).date() > as_of:
            continue
        counted += 1
        first = first or entry["at"]
        last = entry["at"]
        if not entry.get("user"):
            continue  # no recognised token: nobody to attribute it to
        key = (str(entry["user"]), str(entry.get("user_tenant") or ""))
        seen = usage.setdefault(
            key, {"requests": 0, "refused": 0, "last_used": None, "last_refused": None}
        )
        seen["requests"] += 1
        seen["last_used"] = entry["at"]
        if entry.get("status") == 403:
            seen["refused"] += 1
            seen["last_refused"] = {"at": entry["at"], "path": entry["path"]}
    return usage, {"entries": counted, "from": first, "to": last}


def _apply_usage(
    item: dict[str, Any],
    usage: dict[tuple[str, str], dict[str, Any]],
    log_from: str | None,
    as_of: date,
    dormant_days: int,
) -> None:
    seen = usage.get((item["user_id"], item["tenant_id"]))
    item["requests"] = seen["requests"] if seen else 0
    item["refused"] = seen["refused"] if seen else 0
    item["last_used"] = seen["last_used"] if seen else None
    item["dormant"] = False
    notices: list[str] = []
    if item["state"] in ("active", "expiring"):
        if seen is None:
            item["dormant"] = True
            since = f"since it begins at {log_from}" if log_from else "at all"
            notices.append(
                f"no request in the access log {since}; confirm the access is "
                "still needed or remove the entry"
            )
        else:
            idle = (as_of - _last_day(seen)).days
            if idle > dormant_days:
                item["dormant"] = True
                notices.append(
                    f"last request {seen['last_used']}, {idle} days before {as_of.isoformat()}; "
                    "confirm the access is still needed or remove the entry"
                )
    if seen and seen["refused"]:
        latest = seen["last_refused"]
        notices.append(
            f"refused {seen['refused']} time(s) with 403, the latest {latest['path']} "
            f"at {latest['at']}"
        )
    item["findings"].extend({"level": "notice", "message": m} for m in notices)


def _last_day(seen: dict[str, Any]) -> date:
    return _at({"at": seen["last_used"]}).astimezone(timezone.utc).date()


def _review_entry(
    position: int, entry: dict[str, Any], digests: Counter[str], as_of: date
) -> dict[str, Any]:
    high: list[str] = []
    notice: list[str] = []
    refused = False

    digest = str(entry.get("sha256", "")).strip().lower()
    if not _SHA256_HEX.match(digest):
        high.append("sha256 is not a 64-character hex digest; no token matches it")
        refused = True
    elif digests[digest] > 1:
        high.append(
            f"the same digest is listed {digests[digest]} times; the token is refused "
            "rather than guessed between them"
        )
        refused = True

    tenant = str(entry.get("tenant_id", "")).strip()
    if not tenant or slugify(tenant) != tenant:
        high.append(f"tenant_id {tenant!r} is not a tenant id; the token authenticates nobody")
        refused = True

    raw_roles = entry.get("roles") or []
    if not isinstance(raw_roles, list):
        raw_roles = []
        high.append("roles is not a list")
    roles = sorted(r for r in raw_roles if r in _ROLES)
    unknown = sorted(str(r) for r in raw_roles if r not in _ROLES)
    if unknown:
        high.append(f"unrecognised roles dropped: {', '.join(unknown)}")
    if not roles:
        high.append("no recognised role; the token can reach nothing")

    user = str(entry.get("user_id", "")).strip()
    if not user:
        high.append("no user_id; the access log could not name this caller")

    link = entry.get("on_behalf_of")
    try:
        parse_on_behalf_of(link)
    except ValueError as exc:
        high.append(f"{exc}; `oversight access` cannot hold it to a register record")

    last_day: date | None = None
    try:
        last_day = parse_expiry(entry.get("expires_at"))
    except InvalidExpiryError as exc:
        high.append(f"{exc}; the token is refused")
        refused = True

    if refused:
        state = "refused"
    elif last_day is not None and as_of > last_day:
        state = "expired"
        high.append(f"expired {last_day.isoformat()} and still in the file; remove the entry")
    elif last_day is None:
        state = "active"
        notice.append("no expires_at; this token works until the entry is removed")
    elif last_day - as_of <= timedelta(days=EXPIRY_WARNING_DAYS):
        state = "expiring"
        notice.append(f"expires {last_day.isoformat()}; renew or let it lapse")
    else:
        state = "active"

    item: dict[str, Any] = {
        "entry": position,
        "user_id": user,
        "tenant_id": tenant,
        "roles": roles,
        "expires_at": last_day.isoformat() if last_day else None,
        "digest_prefix": digest[:12],
        "state": state,
        "findings": [{"level": "high", "message": m} for m in high]
        + [{"level": "notice", "message": m} for m in notice],
    }
    # Written by `issue_token`; a hand-written entry has neither.
    for key in ("issued_by", "issued_at", "on_behalf_of"):
        if entry.get(key):
            item[key] = str(entry[key])
    return item


# ------------------------------------------------------------------ editing


class TokenFileError(ValueError):
    """An issue or revocation refused; nothing was written."""


def _entries_of(document: object) -> list[Any]:
    entries = document.get("tokens") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise TokenFileError('not a token file: expected {"tokens": [...]}')
    return entries


def _holds(entry: object, user: str, tenant: str) -> bool:
    return (
        isinstance(entry, dict)
        and str(entry.get("user_id", "")).strip() == user
        and str(entry.get("tenant_id", "")).strip() == tenant
    )


def issue_token(
    document: object,
    *,
    user_id: str,
    tenant_id: str,
    roles: list[str],
    expires_at: date,
    issued_by: str,
    as_of: date,
    on_behalf_of: str = "",
) -> tuple[str, dict[str, Any]]:
    """Add one entry to `document` in place; return the token and the entry.

    The token is returned once and is not stored: the entry holds its digest.
    Refused, leaving `document` unchanged, for a user or tenant that is not
    one, an unknown or missing role, no issuer, an expiry already past or
    beyond `MAX_TERM_DAYS`, or an entry already held by this user in this
    tenant. The access log names callers by user and tenant, not by token, so
    two entries for one pair could not be told apart in a review.

    `on_behalf_of` links the grant to a register record in the same tenant
    (`partners/<id>` or `integrations/<id>`); only its form is checked here.
    `tokens issue` also holds it to the register first (`link_withdrawn`).
    """
    entries = _entries_of(document)
    user, tenant, actor = user_id.strip(), tenant_id.strip(), issued_by.strip()
    problems: list[str] = []
    if not user:
        problems.append("no user id; the access log could not name this caller")
    if not tenant or slugify(tenant) != tenant:
        problems.append(f"tenant {tenant_id!r} is not a tenant id")
    unknown = sorted({r for r in roles if r not in _ROLES})
    if unknown:
        problems.append(f"unrecognised roles: {', '.join(unknown)}")
    if not roles:
        problems.append("no role; the token could reach nothing")
    if not actor:
        problems.append("no issuer; the grant must name who made it")
    link = on_behalf_of.strip()
    try:
        parse_on_behalf_of(link)
    except ValueError as exc:
        problems.append(str(exc))
    if expires_at < as_of:
        problems.append(f"expires {expires_at.isoformat()}, before {as_of.isoformat()}")
    elif (expires_at - as_of).days > MAX_TERM_DAYS:
        problems.append(
            f"expires {expires_at.isoformat()}, more than {MAX_TERM_DAYS} days after "
            f"{as_of.isoformat()}"
        )
    if user and any(_holds(e, user, tenant) for e in entries):
        problems.append(
            f"{user} already holds an entry for {tenant}; revoke it first "
            "(a renewal is a new token)"
        )
    if problems:
        raise TokenFileError("; ".join(problems))

    token = secrets.token_urlsafe(32)
    entry: dict[str, Any] = {
        "sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "user_id": user,
        "tenant_id": tenant,
        "roles": sorted(set(roles)),
        "expires_at": expires_at.isoformat(),
        "issued_by": actor,
        "issued_at": as_of.isoformat(),
    }
    if link:
        entry["on_behalf_of"] = link
    entries.append(entry)
    return token, entry


def revoke_tokens(
    document: object,
    *,
    user_id: str = "",
    tenant_id: str = "",
    digest_prefix: str = "",
    expired_as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Remove matching entries from `document` in place; return what was removed.

    Exactly one selector: a user in a tenant, a digest prefix as the review
    prints it (at least 12 hex characters, matching one entry), or every entry
    expired as of a date, which is what the review asks for when it reports
    one still in the file. Removing nothing is refused, so a mistyped name is
    not reported as a revocation that happened.
    """
    entries = _entries_of(document)
    user, tenant = user_id.strip(), tenant_id.strip()
    prefix = digest_prefix.strip().lower()
    by_user = bool(user or tenant)
    if sum([by_user, bool(prefix), expired_as_of is not None]) != 1:
        raise TokenFileError("name one of: a user and tenant, a digest prefix, or expired")
    if by_user and not (user and tenant):
        raise TokenFileError("a revocation by user names both the user and the tenant")
    if prefix and not re.fullmatch(r"[0-9a-f]{12,64}", prefix):
        raise TokenFileError("a digest prefix is 12 to 64 hex characters")

    def matches(entry: object) -> bool:
        if by_user:
            return _holds(entry, user, tenant)
        if not isinstance(entry, dict):
            return False
        if prefix:
            return str(entry.get("sha256", "")).strip().lower().startswith(prefix)
        try:
            last_day = parse_expiry(entry.get("expires_at"))
        except InvalidExpiryError:
            return False  # refused already; the review names it for a person to decide
        return last_day is not None and expired_as_of is not None and expired_as_of > last_day

    removed = [e for e in entries if matches(e)]
    if not removed:
        raise TokenFileError("no entry matches; nothing was revoked")
    if prefix and len(removed) > 1:
        raise TokenFileError(f"{len(removed)} entries match that prefix; give more of it")
    entries[:] = [e for e in entries if not matches(e)]
    return removed


def summary(entry: dict[str, Any]) -> dict[str, Any]:
    """An entry as it may be printed: the digest cut to the review's prefix."""
    shown = {k: v for k, v in entry.items() if k != "sha256"}
    shown["digest_prefix"] = str(entry.get("sha256", ""))[:12]
    return shown


def read_token_file(path: Path) -> dict[str, Any]:
    """A token file to edit; a missing one is empty, anything unreadable refused."""
    if not path.exists():
        return {"tokens": []}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenFileError(f"token file unreadable: {path}: {exc}") from exc
    _entries_of(document)
    return document  # type: ignore[no-any-return]


class TokenFileLock:
    """`<file>.lock`, created exclusively and held across a read-modify-write."""

    def __init__(self, path: Path) -> None:
        self.lock = path.with_name(path.name + ".lock")

    def __enter__(self) -> TokenFileLock:
        try:
            fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise TokenFileError(
                f"{self.lock} exists: another edit is in progress, or one was "
                "interrupted; remove it only once no edit is running"
            ) from exc
        os.close(fd)
        return self

    def __exit__(self, *_: object) -> None:
        self.lock.unlink(missing_ok=True)


def write_token_file(path: Path, document: dict[str, Any]) -> None:
    """Replace the file whole, so a reader sees the old file or the new one."""
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(temp, "x", encoding="utf-8") as handle:
            handle.write(json.dumps(document, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
