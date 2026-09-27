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
never needs a token, so an operator can run it anywhere the file is.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ironclad.ids import slugify
from ironclad.model.tenant import Role

#: A token expiring within this many days is reported as a notice, so its
#: renewal or removal is decided before it lapses, not after.
EXPIRY_WARNING_DAYS = 30

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_ROLES = frozenset(member.value for member in Role)


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


def review_tokens(document: object, as_of: date) -> dict[str, Any]:
    """Every entry in a token file, what it grants and what is wrong with it.

    One item per entry, in file order: the user, tenant, recognised roles,
    expiry, a `state` (`active`, `expiring`, `expired`, `refused`) and its
    findings, each `high` or `notice`. `high` means the entry grants access it
    should not, or is broken so that it grants none and someone thinks it does.
    Only the first 12 hex characters of a digest are shown, enough to find the
    entry and not the whole stored value.
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

    counts = Counter(item["state"] for item in items)
    return {
        "as_of": as_of.isoformat(),
        "entries": len(items),
        "active": counts["active"] + counts["expiring"],
        "high": sum(1 for i in items if any(f["level"] == "high" for f in i["findings"])),
        "notices": sum(1 for i in items if any(f["level"] == "notice" for f in i["findings"])),
        "tenants": sorted(
            {
                str(i.get("tenant_id", ""))
                for i in items
                if i["state"] in ("active", "expiring") and i.get("tenant_id")
            }
        ),
        "items": items,
    }


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

    return {
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
