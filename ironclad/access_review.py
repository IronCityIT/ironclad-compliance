"""A tenant's access review as one packet of evidence, and its check.

Each piece of the Sage Spine workspace's access review already exists on its
own: the register export an auditor files as the business-associate
inventory, the review queue, the register's history check and seal, partner
tokens held to their records (`oversight access`), and the token review with
its use from the access log and its grants from the ledger (`tokens review`).
A quarterly review (HIPAA 164.308(a)(1)(ii)(D) information-system activity
review, (a)(4) access review, 164.316(b) documentation) needs them taken
together, as of one date, in a form that cannot quietly be changed after it
is filed. Run one at a time they were six commands, six dates and no record
tying the outputs to each other.

`build_packet()` takes them all as of one date and returns the files and a
manifest naming each file's SHA-256. The manifest's `digest` covers the
tenant, the date, who built it and when, the inputs and every file's hash:
one line to write down beside the filed packet. `verify_packet()` re-hashes a
packet on disk and, given that line, says whether it is still the packet that
was filed.

A review is only worth as much as its link to the last one. Each packet holds
the register seal and each chain's anchor, and nothing inside one packet can
see a history entry rewritten, or a log cut and restarted, between two
reviews. Given the previous packet, `build_packet()` also files
`continuity.json`: the previous packet re-verified, its seal compared with
today's, and its log and ledger anchors held against today's chains. The
manifest records the previous packet's digest, so the packets form a chain of
their own.

A packet holds only its tenant. The token file and the access log hold every
tenant's entries and requests; the token review is run on the whole file (so
a digest shared with another tenant is still found) and then cut down to the
tenant's own entries, requests and grants before anything is written. The
one whole-file figure kept is each chain's anchor (`N:DIGEST`), since that is
what the operator recorded and what a later check must match.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ironclad import oversight
from ironclad.api.tokens import DORMANT_DAYS, review_tokens
from ironclad.model.tenant import Principal

PACKET_FORMAT = "ironclad-access-review/1"
MANIFEST = "manifest.json"

#: The files a packet holds besides its manifest, in the order they are listed.
FILES = (
    "register.csv",
    "review-queue.json",
    "partner-access.json",
    "register-verify.json",
    "register-seal.json",
    "token-review.json",
)
#: Filed as well when the packet is built against the previous one.
CONTINUITY = "continuity.json"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PacketError(oversight.OversightError):
    """The packet cannot be built from these inputs, or is not a packet."""


def packet_name(tenant_id: str, today: str) -> str:
    """The directory a packet is filed under: the tenant and the date."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(tenant_id or "")) or "tenant"
    return f"access-review-{safe}-{today}"


def _json_bytes(payload: object) -> bytes:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    return (text + "\n").encode("utf-8")


def _manifest_digest(manifest: dict[str, Any]) -> str:
    # Over everything the manifest says but its own digest: who built it and
    # when are part of the record, so neither can be changed afterwards.
    covered = {key: value for key, value in manifest.items() if key != "digest"}
    encoded = json.dumps(covered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def tenant_token_review(
    review: dict[str, Any],
    tenant_id: str,
    as_of: date,
    access_log: list[dict[str, Any]] | None,
    ledger: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """A whole-file token review cut down to one tenant, and recounted.

    Only entries naming the tenant are kept; an entry with no readable tenant
    belongs to none and stays in the whole-file review. The access-log span
    counts only the tenant's own requests, and the ledger only its own lines.
    """
    items = [item for item in review["items"] if item.get("tenant_id") == tenant_id]
    unrecorded = [
        grant
        for grant in (review.get("ledger") or {}).get("unrecorded") or []
        if grant.get("tenant_id") == tenant_id
    ]
    scoped: dict[str, Any] = {
        "as_of": review["as_of"],
        "tenant_id": tenant_id,
        "entries": len(items),
        "active": sum(1 for i in items if i["state"] in ("active", "expiring")),
        "high": sum(1 for i in items if any(f["level"] == "high" for f in i["findings"])),
        "notices": sum(1 for i in items if any(f["level"] == "notice" for f in i["findings"]))
        + len(unrecorded),
        "items": items,
    }
    if access_log is not None:
        summary = review["access_log"]
        scoped["access_log"] = {
            "from": summary["from"],
            "to": summary["to"],
            "dormant_days": summary["dormant_days"],
            "entries": sum(
                1
                for line in access_log
                if line.get("user_tenant") == tenant_id and _utc_day(line["at"]) <= as_of
            ),
        }
        scoped["dormant"] = sum(1 for i in items if i.get("dormant"))
    if ledger is not None:
        scoped["ledger"] = {
            "entries": sum(1 for line in ledger if line.get("tenant_id") == tenant_id),
            "unrecorded": unrecorded,
        }
    return scoped


def _utc_day(moment: object) -> date:
    parsed = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).date()


def _verified(what: str, chain: tuple[dict[str, Any], list[dict[str, Any]]] | None) -> None:
    if chain is not None and not chain[0]["verified"]:
        raise PacketError(f"the {what} is not a whole chain; no review is built on it")


def build_packet(
    store: Any,
    document: object,
    *,
    tenant_id: str,
    principal: Principal,
    today: str,
    token_file_sha256: str,
    access_log: tuple[dict[str, Any], list[dict[str, Any]]] | None = None,
    ledger: tuple[dict[str, Any], list[dict[str, Any]]] | None = None,
    dormant_days: int = DORMANT_DAYS,
    at: str | None = None,
    previous: Path | None = None,
    previous_digest: str = "",
) -> dict[str, Any]:
    """Every part of the tenant's access review as of `today`, as files.

    `access_log` and `ledger` are `(verdict, entries)` from their `read_file`;
    a chain that is not whole is refused rather than reviewed. Any member of
    the tenant may build one, as each part already allows. Returns `name`, the
    directory to file it under, `files` (name to bytes, the manifest last) and
    `manifest`.

    With `previous`, the tenant's last filed packet (and `previous_digest`,
    the line recorded when it was filed), the packet also holds
    `continuity.json`; see `continuity()`. A previous packet that does not
    verify, is another tenant's or is not earlier is refused.
    """
    oversight.check_reader(principal, tenant_id)
    as_of = date.fromisoformat(oversight.check_as_of(today))
    if not _HEX64.match(token_file_sha256):
        raise PacketError("token_file_sha256 must be a 64-character hex digest")
    _verified("access log", access_log)
    _verified("grant ledger", ledger)
    log_entries = access_log[1] if access_log is not None else None
    ledger_entries = ledger[1] if ledger is not None else None

    export = oversight.export_register(store, tenant_id=tenant_id, principal=principal, today=today)
    queue = oversight.attention_queue(store, tenant_id=tenant_id, principal=principal, today=today)
    access = oversight.partner_access(
        store, document, tenant_id=tenant_id, principal=principal, today=today
    )
    sweep = oversight.verify_register(store, tenant_id=tenant_id, principal=principal)
    seal = oversight.seal_register(store, tenant_id=tenant_id, principal=principal, at=at)
    try:
        whole = review_tokens(document, as_of, log_entries, dormant_days, ledger_entries)
    except ValueError as exc:
        raise PacketError(str(exc)) from exc
    tokens = tenant_token_review(whole, tenant_id, as_of, log_entries, ledger_entries)
    linked = (
        continuity(previous, previous_digest, tenant_id, today, seal, log_entries, ledger_entries)
        if previous is not None
        else None
    )

    contents = {
        "register.csv": export["csv"].encode("utf-8"),
        "review-queue.json": _json_bytes(queue),
        "partner-access.json": _json_bytes(access),
        "register-verify.json": _json_bytes(sweep),
        "register-seal.json": _json_bytes(seal),
        "token-review.json": _json_bytes(tokens),
    }
    if linked is not None:
        contents[CONTINUITY] = _json_bytes(linked)
    summary = {
        "register": {"records": export["records"], "verified": sweep["verified"]},
        "review_queue": {"records": queue["records"], "high": queue["high"]},
        "partner_access": {
            "holders": access["holders"],
            "high": access["high"],
            "notices": access["notices"],
            "unlinked": len(access["unlinked"]),
        },
        "token_review": {
            "entries": tokens["entries"],
            "active": tokens["active"],
            "high": tokens["high"],
            "notices": tokens["notices"],
            **({"dormant": tokens["dormant"]} if "dormant" in tokens else {}),
        },
    }
    high = queue["high"] + access["high"] + tokens["high"] + (0 if sweep["verified"] else 1)
    notices = (queue["records"] - queue["high"]) + access["notices"] + tokens["notices"]
    if linked is not None:
        summary["continuity"] = {k: linked[k] for k in ("verified", "broken", "unchecked")}
        high += linked["broken"]
        notices += linked["unchecked"]
    summary["high"] = high
    summary["notices"] = notices
    manifest: dict[str, Any] = {
        "format": PACKET_FORMAT,
        "tenant_id": tenant_id,
        "as_of": today,
        "generated_at": at or oversight.stamp(),
        "generated_by": principal.user_id,
        "inputs": {
            "token_file_sha256": token_file_sha256,
            "register_seal": seal["digest"],
            "access_log": _chain_input(access_log),
            "grant_ledger": _chain_input(ledger),
            "dormant_days": dormant_days if access_log is not None else None,
            **({"previous": linked["previous"]} if linked is not None else {}),
        },
        "summary": summary,
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in contents.items()
        },
    }
    manifest["digest"] = _manifest_digest(manifest)
    contents[MANIFEST] = _json_bytes(manifest)
    return {"name": packet_name(tenant_id, today), "files": contents, "manifest": manifest}


def continuity(
    previous: Path,
    previous_digest: str,
    tenant_id: str,
    today: str,
    seal: dict[str, Any],
    log_entries: list[dict[str, Any]] | None,
    ledger_entries: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Whether nothing the previous packet recorded has changed since.

    The previous packet must verify (against `previous_digest` too, when
    given), be the same tenant's and be earlier. Its seal must be extended by
    today's: a sealed history entry rewritten or removed, or a record gone, is
    broken. Each anchor it recorded must still be in today's chain: a log or
    ledger cut back or started afresh is broken. An anchored chain not given
    today cannot be checked, and is counted as `unchecked` rather than passed.
    """
    before = verify_packet(previous, previous_digest)
    if not before["verified"]:
        raise PacketError(
            f"the previous packet {previous} does not verify: {'; '.join(before['problems'])}"
        )
    if before["tenant_id"] != tenant_id:
        raise PacketError(f"the previous packet is {before['tenant_id']}'s, not {tenant_id}'s")
    if not str(before["as_of"]) < today:
        raise PacketError(f"the previous packet is as of {before['as_of']}, not before {today}")
    try:
        manifest = json.loads((previous / MANIFEST).read_text(encoding="utf-8"))
        earlier_seal = json.loads((previous / "register-seal.json").read_text(encoding="utf-8"))
        recorded = manifest.get("inputs") or {}
        chains = {
            "access_log": _still_anchored(recorded.get("access_log"), log_entries),
            "grant_ledger": _still_anchored(recorded.get("grant_ledger"), ledger_entries),
        }
    except (OSError, ValueError, AttributeError) as exc:
        raise PacketError(f"the previous packet cannot be read ({exc})") from exc
    register = oversight.compare_seals(earlier_seal, seal)
    broken = register["broken"] + sum(1 for c in chains.values() if c and c["extended"] is False)
    unchecked = sum(1 for c in chains.values() if c and c["extended"] is None)
    return {
        "previous": {"name": previous.name, "as_of": before["as_of"], "digest": before["digest"]},
        "register": register,
        **chains,
        "broken": broken,
        "unchecked": unchecked,
        "verified": broken == 0 and unchecked == 0,
    }


def _still_anchored(
    recorded: dict[str, Any] | None, entries: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    """The previous packet's anchor held against today's chain, if it had one."""
    from ironclad.api.access_log import check_anchor  # noqa: PLC0415

    anchor = (recorded or {}).get("anchor") or ""
    if not anchor:
        return None
    if entries is None:
        return {"anchor": anchor, "extended": None, "reason": "not given for this review"}
    return check_anchor(entries, anchor)


def _chain_input(chain: tuple[dict[str, Any], list[dict[str, Any]]] | None) -> Any:
    from ironclad.api.access_log import anchor_of  # noqa: PLC0415

    if chain is None:
        return None
    given = {"entries": chain[0]["entries"], "anchor": anchor_of(chain[0])}
    if chain[0].get("continues"):
        # The chain given begins after a rotation: this is where the review's view starts.
        given["continues"] = chain[0]["continues"]
    return given


def write_packet(packet: dict[str, Any], out: Path) -> Path:
    """File the packet as a new directory under `out`; never over an old one.

    Written to a temporary sibling and renamed into place, so a packet on
    disk is whole or absent.
    """
    if not out.is_dir():
        raise PacketError(f"{out} is not a directory")
    final = out / packet["name"]
    if final.exists():
        raise PacketError(f"{final} already exists; a filed packet is not overwritten")
    staging = out / f".{packet['name']}.partial"
    if staging.exists():
        raise PacketError(f"{staging} is left from an earlier run; remove it first")
    try:
        staging.mkdir()
        for name, data in packet["files"].items():
            (staging / name).write_bytes(data)
        staging.rename(final)
    except OSError as exc:
        raise PacketError(f"cannot write {final} ({exc})") from exc
    return final


def verify_packet(
    directory: Path, digest: str = "", previous: Path | None = None
) -> dict[str, Any]:
    """Re-hash a filed packet against its manifest, and the manifest against `digest`.

    `verified` is true only when the manifest matches its own digest, every
    file it lists is there with that hash and size, nothing else is in the
    directory, and (given `digest`, the line written down when it was filed)
    the manifest's digest is that one. A manifest rebuilt to fit edited files
    passes every check but the last, which is why the line is kept elsewhere.

    With `previous`, the packet must have been built against that one: the
    previous packet verifies, and its digest is the one this manifest names.
    """
    digest = digest.strip().lower()
    if digest and not _HEX64.match(digest):
        raise PacketError("the digest must be 64 hex characters")
    try:
        manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketError(f"{directory} has no readable {MANIFEST} ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != PACKET_FORMAT:
        raise PacketError(f"not an access-review packet (expected format {PACKET_FORMAT})")
    listed = manifest.get("files")
    if not isinstance(listed, dict) or sorted(listed) not in (
        sorted(FILES),
        sorted((*FILES, CONTINUITY)),
    ):
        raise PacketError(f"the manifest does not list the packet's files: {', '.join(FILES)}")
    names = [name for name in (*FILES, CONTINUITY) if name in listed]

    problems: list[str] = []
    if manifest.get("digest") != _manifest_digest(manifest):
        problems.append("the manifest does not match its own digest")
    if digest and manifest.get("digest") != digest:
        problems.append("the manifest's digest is not the one recorded when it was filed")
    files: dict[str, str] = {}
    for name in names:
        path = directory / name
        if not path.is_file():
            files[name] = "missing"
            problems.append(f"{name} is missing")
            continue
        data = path.read_bytes()
        expected = listed[name] if isinstance(listed[name], dict) else {}
        if hashlib.sha256(data).hexdigest() != expected.get("sha256") or len(data) != expected.get(
            "bytes"
        ):
            files[name] = "changed"
            problems.append(f"{name} does not match the manifest")
        else:
            files[name] = "ok"
    extra = sorted(
        p.name for p in directory.iterdir() if p.name not in names and p.name != MANIFEST
    )
    problems.extend(f"{name} is not part of the packet" for name in extra)
    if previous is not None:
        before = verify_packet(previous)
        named = ((manifest.get("inputs") or {}).get("previous") or {}).get("digest")
        if not before["verified"]:
            problems.append(f"the previous packet does not verify: {'; '.join(before['problems'])}")
        if not named:
            problems.append("the packet was not built against a previous packet")
        elif named != before["digest"]:
            problems.append("the previous packet is not the one this packet was built against")
    return {
        "tenant_id": manifest.get("tenant_id"),
        "as_of": manifest.get("as_of"),
        "digest": manifest.get("digest"),
        "files": files,
        "unlisted": extra,
        "problems": problems,
        "verified": not problems,
    }


__all__ = [
    "CONTINUITY",
    "FILES",
    "MANIFEST",
    "PACKET_FORMAT",
    "PacketError",
    "build_packet",
    "continuity",
    "packet_name",
    "tenant_token_review",
    "verify_packet",
    "write_packet",
]
