"""The partner and integration register, off Firebase.

The register is the one tenant surface people write to: who a client shares
data with, whether a BAA is executed, when each relationship is next reviewed.
Today it lives in Firestore, and every rule about it is in `firestore.rules` —
a closed field list, closed vocabularies, bounded text, a contributor who may
propose but not rate, and an immutable `history/{revision}` entry written with
every change. Firestore is retired from the target architecture, and
`HANDOFF.md` records what the replacement owes: the same checks, and an
immutable per-record change log written in the same transaction as the record.

This module is that replacement's policy, free of any store. `next_revision`
is the rules' create and update predicates as a function: it takes what a
caller asked to change and returns the record to write, or refuses. Stamps are
the server's, never the caller's: who and when come from the principal and the
clock, the revision from the stored record. The stores (`FileResultStore`,
`MariaDBResultStore`) then write the record and its history entry as one step
and refuse a revision that is already taken, so two editors working from the
same revision cannot both land.

The vocabularies here are asserted equal to the ones parsed out of
`firestore.rules` (`tests/test_oversight.py`), so the two cannot drift while
both exist.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ironclad.errors import AuthorizationError, IroncladError
from ironclad.ids import is_safe_document_id, slugify
from ironclad.model.tenant import Principal, Role

KINDS = ("partners", "integrations")

#: Every field a stored record may carry, in the order `firestore.rules` lists them.
FIELDS = (
    "tenant_id", "name", "business_owner", "technical_owner", "status",
    "risk", "data_access", "phi_scope", "data_flow_direction",
    "agreement_status", "baa_status", "baa_execution_date", "baa_document_ref",
    "review_due", "integration_method", "port_protocol", "network_exposure",
    "assurance", "cert_expiration_date", "notes", "revision",
    "created_at", "created_by", "updated_at", "updated_by",
)  # fmt: skip

#: Set by the server on every write; a caller never supplies them.
STAMP_FIELDS = ("tenant_id", "revision", "created_at", "created_by", "updated_at", "updated_by")

#: What a person edits.
CONTENT_FIELDS = tuple(f for f in FIELDS if f not in STAMP_FIELDS)

REQUIRED = (
    "tenant_id", "name", "status", "risk", "agreement_status", "baa_status",
    "revision", "created_at", "created_by", "updated_at", "updated_by",
)  # fmt: skip

AGREEMENT = ("Pending review", "Under review", "Required - pending", "Executed", "Not required")

#: A closed vocabulary per governance field. An empty value is allowed only
#: where the rules allow it (data flow direction).
VOCABULARY: dict[str, tuple[str, ...]] = {
    "status": ("Pending information", "Onboarding", "Active", "Under review", "Offboarding", "Retired"),
    "risk": ("Unrated", "Low", "Medium", "High", "Critical"),
    "agreement_status": AGREEMENT,
    "baa_status": AGREEMENT,
    "data_access": ("PHI", "PII", "Operational only", "No production data", "Unknown"),
    "data_flow_direction": ("", "Bidirectional", "Outbound / push", "Inbound / pull", "Unidirectional"),
}  # fmt: skip

DATE_FIELDS = ("baa_execution_date", "review_due", "cert_expiration_date")

#: The longest value each text field may hold. `name` must also be non-empty.
TEXT_BOUNDS: dict[str, int] = {
    "name": 120,
    "business_owner": 120,
    "technical_owner": 120,
    "phi_scope": 300,
    "baa_document_ref": 300,
    "integration_method": 120,
    "port_protocol": 120,
    "network_exposure": 120,
    "assurance": 300,
    "notes": 2000,
}

#: The fields only an approver may set. A contributor's proposal starts at
#: `UNRATED` and a contributor's edit leaves them as stored.
GOVERNANCE_FIELDS = ("status", "risk", "agreement_status", "baa_status")
UNRATED = {
    "status": "Pending information",
    "risk": "Unrated",
    "agreement_status": "Pending review",
    "baa_status": "Pending review",
}

MAINTAIN_ROLES = frozenset({Role.OWNER, Role.COMPLIANCE_MANAGER, Role.CONTRIBUTOR})
APPROVE_ROLES = frozenset({Role.OWNER, Role.COMPLIANCE_MANAGER})

_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_RECORD_ID_MAX = 128


class OversightError(IroncladError):
    """A register write was refused. `problems` names every reason."""

    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []

    def __str__(self) -> str:
        base = super().__str__()
        return base + ("\n  - " + "\n  - ".join(self.problems) if self.problems else "")


class StaleRevisionError(OversightError):
    """Someone saved this record first; the write was based on an old revision."""


class RecordNotFoundError(OversightError):
    """An edit named a record the register does not hold."""


# ------------------------------------------------------------------- checks


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise OversightError(f"{kind!r} is not a register; use one of {', '.join(KINDS)}")
    return kind


def check_record_id(record_id: str) -> str:
    # The id becomes a path segment on a volume and a key in SQL, so it is
    # checked rather than trusted, exactly as a tenant id is.
    value = str(record_id or "")
    if (
        not value
        or len(value) > _RECORD_ID_MAX
        or value != value.strip()
        or not is_safe_document_id(value)
        or not re.fullmatch(r"[A-Za-z0-9_-]+", value)
    ):
        raise OversightError(f"{record_id!r} is not a usable register record id")
    return value


def new_record_id() -> str:
    """An id for a record created without one: opaque, path-safe, unguessable."""
    return uuid.uuid4().hex


def content_problems(content: dict[str, Any]) -> list[str]:
    """What is wrong with a record's editable fields, as the rules judge them."""
    problems = [f"{key!r} is not a register field" for key in content if key not in CONTENT_FIELDS]
    for field, values in VOCABULARY.items():
        if field in content and content[field] not in values:
            problems.append(f"{field} {content[field]!r} is not one of {list(values)}")
    for field in DATE_FIELDS:
        if field in content:
            value = content[field]
            if not isinstance(value, str) or (value and not _ISO_DATE.match(value)):
                problems.append(f"{field} {value!r} is not a YYYY-MM-DD date or empty")
    for field, bound in TEXT_BOUNDS.items():
        if field in content:
            value = content[field]
            if not isinstance(value, str):
                problems.append(f"{field} must be text")
            elif len(value) > bound:
                problems.append(f"{field} is {len(value)} characters; the limit is {bound}")
    name = content.get("name")
    if "name" in content and isinstance(name, str) and not name.strip():
        problems.append("name must not be empty")
    return problems


def shape_problems(record: dict[str, Any]) -> list[str]:
    """What is wrong with a complete stored record. Empty means it may be stored."""
    problems = [f"{key!r} is not a register field" for key in record if key not in FIELDS]
    problems += [f"{key} is required" for key in REQUIRED if key not in record]
    content = {k: v for k, v in record.items() if k in CONTENT_FIELDS}
    problems += [p for p in content_problems(content) if p not in problems]
    revision = record.get("revision")
    if "revision" in record and (
        not isinstance(revision, int) or isinstance(revision, bool) or revision < 1
    ):
        problems.append(f"revision {revision!r} must be a whole number from 1")
    for field in ("tenant_id", "created_at", "created_by", "updated_at", "updated_by"):
        if field in record and (not isinstance(record[field], str) or not record[field]):
            problems.append(f"{field} must be non-empty text")
    return problems


# ------------------------------------------------------------------- policy


def stamp(moment: datetime | None = None) -> str:
    """A write time as ISO-8601 UTC, to the second."""
    when = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return when.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def check_reader(principal: Principal, tenant_id: str) -> None:
    """Any member of the tenant reads the register and its history; no one else."""
    if principal.tenant_id != tenant_id or not principal.roles:
        raise AuthorizationError(f"{principal.user_id} may not read this register")


def next_revision(
    *,
    prior: dict[str, Any] | None,
    changes: dict[str, Any],
    tenant_id: str,
    principal: Principal,
    at: str,
) -> dict[str, Any]:
    """The record to store when `principal` asks for `changes`, or a refusal.

    `prior` is the record as stored now (None to create). Fields `changes`
    does not name carry over from `prior`. The refusals are the rules':
    another tenant, a role that cannot maintain the register, a field that is
    not in the register, a stamp supplied by the caller, a contributor setting
    a governance field, and a record that would not satisfy the schema.
    """
    # Tenant first, and the same refusal whether or not the caller holds the
    # role, so a probe learns nothing about another tenant.
    if principal.tenant_id != tenant_id:
        raise AuthorizationError(f"{principal.user_id} may not act on another tenant")
    if not principal.roles & MAINTAIN_ROLES:
        raise AuthorizationError(f"{principal.user_id} may not maintain the register")
    if prior is not None and prior.get("tenant_id") != tenant_id:
        raise OversightError("the stored record belongs to another tenant")

    supplied_stamps = sorted(k for k in changes if k in STAMP_FIELDS)
    if supplied_stamps:
        raise OversightError(
            "stamps are set by the server, never supplied",
            [f"{k} was supplied" for k in supplied_stamps],
        )
    problems = content_problems(changes)
    if problems:
        raise OversightError("the change does not fit the register", problems)

    approver = bool(principal.roles & APPROVE_ROLES)
    if prior is None:
        record: dict[str, Any] = dict(UNRATED)
        if not approver:
            # A contributor proposes; only an approver rates.
            rated = sorted(
                f for f in GOVERNANCE_FIELDS if f in changes and changes[f] != UNRATED[f]
            )
            if rated:
                raise AuthorizationError(
                    f"{principal.user_id} may propose a record but not set {', '.join(rated)}"
                )
    else:
        record = {k: v for k, v in prior.items() if k in CONTENT_FIELDS}
        if not approver:
            moved = sorted(
                f for f in GOVERNANCE_FIELDS if f in changes and changes[f] != prior.get(f)
            )
            if moved:
                raise AuthorizationError(
                    f"{principal.user_id} may not change {', '.join(moved)}; an approver rates"
                )
    record.update(changes)

    record["tenant_id"] = tenant_id
    # Records seeded before history existed carry no revision; their first
    # edit is revision 1, as in the rules.
    record["revision"] = 1 if prior is None else int(prior.get("revision") or 0) + 1
    record["created_at"] = at if prior is None else prior.get("created_at")
    record["created_by"] = principal.user_id if prior is None else prior.get("created_by")
    record["updated_at"] = at
    record["updated_by"] = principal.user_id

    problems = shape_problems(record)
    if problems:
        raise OversightError("the record does not fit the register", problems)
    return record


def check_stored(tenant_id: str, record: dict[str, Any]) -> None:
    """The store's last line: never write a record the policy would not produce."""
    problems = shape_problems(record)
    if record.get("tenant_id") != tenant_id:
        problems.append("tenant_id does not match the tenant being written")
    if problems:
        raise OversightError("the record does not fit the register", problems)


def verify_history(
    current: dict[str, Any] | None, history: list[dict[str, Any]], tenant_id: str
) -> dict[str, Any]:
    """Whether a record's stored history is whole and matches the record.

    Revisions must run 1..n without a gap, each entry must be in this tenant
    and keep the record's creation stamp, and the current record must be the
    last entry exactly. An edit to either the record or an entry breaks one of
    those, and the verdict says which.
    """

    def verdict(ok: bool, detail: str = "", at: int | None = None) -> dict[str, Any]:
        return {"verified": ok, "revisions": len(history), "broken_at": at, "detail": detail}

    if current is None and not history:
        return verdict(True)
    for position, entry in enumerate(history, start=1):
        if entry.get("revision") != position:
            return verdict(False, f"revision {position} is missing or out of order", position)
        if entry.get("tenant_id") != tenant_id:
            return verdict(False, "an entry names another tenant", position)
        first = history[0]
        if (entry.get("created_at"), entry.get("created_by")) != (
            first.get("created_at"),
            first.get("created_by"),
        ):
            return verdict(False, "the creation stamp changed between revisions", position)
    if current is None:
        return verdict(False, "history exists for a record that does not", len(history))
    if not history or current != history[-1]:
        return verdict(False, "the record does not match its latest history entry", len(history))
    return verdict(True)


# --------------------------------------------------------------------- use


def records(store: Any, *, tenant_id: str, kind: str, principal: Principal) -> list[dict[str, Any]]:
    check_reader(principal, tenant_id)
    return list(store.list_oversight(tenant_id, check_kind(kind)))


def history(
    store: Any, *, tenant_id: str, kind: str, record_id: str, principal: Principal
) -> list[dict[str, Any]]:
    check_reader(principal, tenant_id)
    return list(store.oversight_history(tenant_id, check_kind(kind), check_record_id(record_id)))


def save(
    store: Any,
    *,
    tenant_id: str,
    kind: str,
    changes: dict[str, Any],
    principal: Principal,
    record_id: str | None = None,
    base_revision: int | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Create or edit one record through `store`, with its history entry.

    `base_revision` is the revision the caller's form was loaded from. When it
    is given and the record has moved on, the save is refused as stale rather
    than applied on top of a change the caller never saw.
    """
    # Who may write is settled before the store is asked anything, so a
    # caller from another tenant, or one who only reads, cannot tell from the
    # refusal whether a record id exists. `next_revision` checks both again.
    if principal.tenant_id != tenant_id:
        raise AuthorizationError(f"{principal.user_id} may not act on another tenant")
    if not principal.roles & MAINTAIN_ROLES:
        raise AuthorizationError(f"{principal.user_id} may not maintain the register")
    check_kind(kind)
    creating = record_id is None
    record_id = check_record_id(new_record_id() if creating else str(record_id))
    prior = None if creating else store.get_oversight(tenant_id, kind, record_id)
    if not creating and prior is None:
        raise RecordNotFoundError(f"{kind}/{record_id} does not exist")
    if base_revision is not None and prior is not None:
        if int(prior.get("revision") or 0) != base_revision:
            raise StaleRevisionError(
                f"{kind}/{record_id} is at revision {prior.get('revision')}; "
                f"the change was made against revision {base_revision}"
            )
    record = next_revision(
        prior=prior,
        changes=changes,
        tenant_id=tenant_id,
        principal=principal,
        at=at or stamp(),
    )
    store.put_oversight(tenant_id, kind, record_id, record)
    return {"id": record_id, **record}


# ------------------------------------------------------------ review queue
#
# `attentionFindings()` in `dashboard/public/oversight-core.js`, as Python, so
# the review queue exists on the target stores and not only in a browser
# reading Firestore. Both are held to one table of cases
# (`tests/fixtures/oversight-attention.json`), finding for finding and message
# for message, by `tests/test_oversight.py` and `dashboard/test/oversight.test.js`.

#: How far ahead a review or assurance expiry is called out before it lapses.
ATTENTION_WINDOW_DAYS = 30


def today_utc() -> str:
    """Today's date in UTC as YYYY-MM-DD, the form register dates are stored in."""
    return datetime.now(timezone.utc).date().isoformat()


def check_as_of(value: str) -> str:
    """A queue date: a real calendar day as YYYY-MM-DD, or a refusal."""
    try:
        if not _ISO_DATE.match(value or ""):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise OversightError(f"{value!r} is not a YYYY-MM-DD date") from None
    return value


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def attention_findings(record: dict[str, Any], today: str) -> list[dict[str, str]]:
    """What a reviewer should look at on one record, most serious first.

    PHI moving without an executed BAA, a BAA claimed without its evidence, a
    lapsed review or assurance, and gaps that leave the record unassessable.
    Derived only from stored fields, so it says nothing a reviewer cannot check
    on the record. Retired records need no attention. ISO dates compare
    correctly as strings.
    """
    if record.get("status") == "Retired":
        return []
    soon = (
        date.fromisoformat(check_as_of(today)) + timedelta(days=ATTENTION_WINDOW_DAYS)
    ).isoformat()
    findings: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        findings.append({"level": level, "code": code, "message": message})

    baa = _text(record.get("baa_status")) or "not recorded"
    if record.get("data_access") == "PHI" and record.get("baa_status") != "Executed":
        add("high", "phi-without-baa", f"Handles PHI without an executed BAA (BAA: {baa}).")
    if record.get("baa_status") == "Executed":
        missing = [
            label
            for field, label in (
                ("baa_execution_date", "execution date"),
                ("baa_document_ref", "document reference"),
            )
            if not _text(record.get(field))
        ]
        if missing:
            add(
                "high",
                "baa-evidence-missing",
                f"BAA marked executed with no {' or '.join(missing)} recorded.",
            )
    review = _text(record.get("review_due"))
    if not _ISO_DATE.match(review):
        add("notice", "review-unscheduled", "No review date set.")
    elif review < today:
        add("high", "review-overdue", f"Review overdue since {review}.")
    elif review <= soon:
        add("notice", "review-due-soon", f"Review due {review}.")
    expiry = _text(record.get("cert_expiration_date"))
    if _ISO_DATE.match(expiry):
        if expiry < today:
            add("high", "assurance-expired", f"Certificate / assurance expired {expiry}.")
        elif expiry <= soon:
            add("notice", "assurance-expiring", f"Certificate / assurance expires {expiry}.")
    if not record.get("risk") or record.get("risk") == "Unrated":
        add("notice", "risk-unrated", "Risk not yet rated.")
    if not record.get("data_access") or record.get("data_access") == "Unknown":
        add("notice", "data-access-unknown", "Data access not established.")
    # Stable, so findings of one level keep the order they were found in.
    return sorted(findings, key=lambda f: f["level"] != "high")


def attention_queue(
    store: Any, *, tenant_id: str, principal: Principal, today: str
) -> dict[str, Any]:
    """The tenant's review queue as of `today`: every record with a finding.

    Records with a high-level finding come first, then by name. Any member of
    the tenant may read it; it holds nothing they cannot already read.
    """
    check_reader(principal, tenant_id)
    check_as_of(today)
    items: list[dict[str, Any]] = []
    for kind in KINDS:
        for record in store.list_oversight(tenant_id, kind):
            findings = attention_findings(record, today)
            if findings:
                level = findings[0]["level"]
                items.append(
                    {
                        "kind": kind,
                        "id": record.get("id"),
                        "name": record.get("name"),
                        "revision": record.get("revision"),
                        "level": level,
                        "findings": findings,
                    }
                )
    items.sort(key=lambda item: (item["level"] != "high", str(item["name"]).casefold()))
    return {
        "as_of": today,
        "window_days": ATTENTION_WINDOW_DAYS,
        "records": len(items),
        "high": sum(1 for item in items if item["level"] == "high"),
        "items": items,
    }


def verify_register(store: Any, *, tenant_id: str, principal: Principal) -> dict[str, Any]:
    """Every record's history in the tenant's register, re-checked.

    Walks every id that has a record *or* any history, so a record removed
    while its history stayed behind is reported rather than never looked at.
    Any member of the tenant may run it; the verdicts hold nothing they cannot
    already read. `verified` is true only when every record is.
    """
    check_reader(principal, tenant_id)
    items: list[dict[str, Any]] = []
    for kind in KINDS:
        for record_id in store.oversight_ids(tenant_id, kind):
            verdict = store.verify_oversight(tenant_id, kind, record_id)
            items.append({"kind": kind, "id": record_id, **verdict})
    broken = sum(1 for item in items if not item["verified"])
    return {
        "tenant_id": tenant_id,
        "records": len(items),
        "broken": broken,
        "verified": broken == 0,
        "items": items,
    }


def seed_record_id(name: str) -> str:
    """A stable id for a seeded record, so loading a seed twice finds it."""
    slug = slugify(name)[:_RECORD_ID_MAX]
    if not slug:
        raise OversightError(f"{name!r} cannot be made into a record id")
    return slug


def load_seed(
    store: Any, seed: dict[str, Any], *, principal: Principal, at: str | None = None
) -> dict[str, list[str]]:
    """Create each seeded record that is not already in the register.

    A seed carries ratings, so loading it is an approver's act, and it is
    attributed to that approver in every revision-1 entry. A record already
    present is left alone — loading twice changes nothing — and reported as
    skipped rather than silently overwritten.
    """
    tenant_id = str(seed.get("tenant_id") or "")
    if not principal.roles & APPROVE_ROLES:
        raise AuthorizationError(f"{principal.user_id} may not load a rated seed")
    when = at or stamp()
    created: list[str] = []
    skipped: list[str] = []
    for kind in KINDS:
        for entry in (seed.get("oversight") or {}).get(kind) or []:
            record_id = check_record_id(seed_record_id(str(entry.get("name") or "")))
            if store.get_oversight(tenant_id, kind, record_id) is not None:
                skipped.append(f"{kind}/{record_id}")
                continue
            record = next_revision(
                prior=None, changes=dict(entry), tenant_id=tenant_id, principal=principal, at=when
            )
            store.put_oversight(tenant_id, kind, record_id, record)
            created.append(f"{kind}/{record_id}")
    return {"created": created, "skipped": skipped}
