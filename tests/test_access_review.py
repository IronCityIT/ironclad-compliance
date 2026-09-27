"""The tenant's access review filed as one hashed packet, and checked later.

`oversight review-packet` takes the register export, the review queue, partner
access, the register's history check and seal, and the token review with its
use and grants, all as of one date, and files them with a manifest of hashes.
A packet holds only its tenant, although the token file, access log and
ledger it is built from hold every tenant's. `oversight verify-packet` says
whether a filed packet is still the one that was filed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ironclad import access_review, oversight
from ironclad.access_review import PacketError, build_packet, verify_packet, write_packet
from ironclad.api import access_log, grant_ledger
from ironclad.api.access_log import AccessLog
from ironclad.api.tokens import issue_token
from ironclad.errors import AuthorizationError
from ironclad.model.tenant import Principal, Role
from ironclad.store import FileResultStore

ROOT = Path(__file__).resolve().parent.parent
SEED = json.loads((ROOT / "tenants" / "sage-spine" / "seed.json").read_text(encoding="utf-8"))
TODAY = "2026-09-27"
AS_OF = date(2026, 9, 27)
AT = "2026-09-26T12:00:00Z"
SHA = "a" * 64

OWNER = Principal(user_id="owner-1", tenant_id="sage-spine", roles=frozenset({Role.OWNER}))
AUDITOR = Principal(user_id="aud-1", tenant_id="sage-spine", roles=frozenset({Role.AUDITOR}))
STRANGER = Principal(user_id="x", tenant_id="other-clinic", roles=frozenset({Role.OWNER}))


@pytest.fixture
def store(tmp_path: Path) -> FileResultStore:
    volume = FileResultStore(tmp_path / "volume")
    oversight.load_seed(volume, SEED, principal=OWNER, at=AT)
    return volume


def grant(document: dict[str, Any], user: str, tenant: str = "sage-spine", link: str = "") -> None:
    issue_token(
        document, user_id=user, tenant_id=tenant, roles=["contributor"], issued_by="bill",
        as_of=AS_OF, expires_at=date(2026, 12, 31), on_behalf_of=link,
    )  # fmt: skip


def two_tenants() -> dict[str, Any]:
    document: dict[str, Any] = {"tokens": []}
    grant(document, "dana@drchrono.example", link="partners/drchrono")
    grant(document, "staff@sage.example")
    grant(document, "nurse@other.example", tenant="other-clinic")
    return document


def ledger_of(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The issue lines `tokens issue` would have written for each entry."""
    return [
        {"action": "issue", "sha256": e["sha256"], "tenant_id": e["tenant_id"],
         "user_id": e["user_id"], "actor": "bill", "at": AT, "as_of": TODAY,
         "roles": e["roles"], "expires_at": e["expires_at"],
         "on_behalf_of": e.get("on_behalf_of", "")}
        for e in document["tokens"]
    ]  # fmt: skip


def write_log(path: Path, *lines: tuple[str | None, str | None, int, str]) -> Path:
    log = AccessLog(path)
    for user, tenant, status, at in lines:
        log.record(
            user=user, user_tenant=tenant, method="GET", path=f"/api/v1/tenants/{tenant}/x",
            status=status, at=datetime.fromisoformat(at).replace(tzinfo=timezone.utc),
        )  # fmt: skip
    log.close()
    return path


def build(store: Any, document: object, **kw: Any) -> dict[str, Any]:
    kw.setdefault("principal", AUDITOR)
    kw.setdefault("today", TODAY)
    kw.setdefault("token_file_sha256", SHA)
    kw.setdefault("at", "2026-09-27T09:00:00Z")
    return build_packet(store, document, tenant_id="sage-spine", **kw)


def load(packet: dict[str, Any], name: str) -> Any:
    return json.loads(packet["files"][name])


class TestTheParts:
    def test_every_part_is_filed_and_hashed(self, store: Any) -> None:
        packet = build(store, two_tenants())
        assert packet["name"] == "access-review-sage-spine-2026-09-27"
        assert sorted(packet["files"]) == sorted([*access_review.FILES, "manifest.json"])
        manifest = packet["manifest"]
        for name in access_review.FILES:
            data = packet["files"][name]
            assert manifest["files"][name] == {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        assert load(packet, "manifest.json") == manifest

    def test_the_register_file_is_the_export_and_the_seal_is_named(self, store: Any) -> None:
        packet = build(store, two_tenants())
        export = oversight.export_register(
            store, tenant_id="sage-spine", principal=AUDITOR, today=TODAY
        )
        assert packet["files"]["register.csv"] == export["csv"].encode("utf-8")
        assert packet["manifest"]["files"]["register.csv"]["sha256"] == export["sha256"]
        seal = load(packet, "register-seal.json")
        assert packet["manifest"]["inputs"]["register_seal"] == seal["digest"]
        assert oversight.check_seal(seal) == seal

    def test_the_summary_carries_every_high_finding(self, store: Any) -> None:
        packet = build(store, two_tenants())
        summary = packet["manifest"]["summary"]
        queue = load(packet, "review-queue.json")
        # The seed's six records all lack a BAA, and the partner token acts for one.
        assert (
            summary["review_queue"]
            == {"records": 6, "high": 6}
            == {k: queue[k] for k in ("records", "high")}
        )
        assert summary["partner_access"] == {"holders": 1, "high": 1, "notices": 0, "unlinked": 1}
        assert summary["register"] == {
            "records": {"partners": 3, "integrations": 3},
            "verified": True,
        }
        assert summary["high"] == 6 + 1 + summary["token_review"]["high"]

    def test_the_digest_covers_who_and_when(self, store: Any) -> None:
        document = two_tenants()
        one = build(store, document, at="2026-09-27T09:00:00Z")["manifest"]
        two = build(store, document, at="2026-09-27T17:30:00Z")["manifest"]
        # Only the seal carries a time of its own; every other file is the same.
        changed = [name for name in one["files"] if one["files"][name] != two["files"][name]]
        assert changed == ["register-seal.json"]
        assert one["digest"] != two["digest"]
        assert build(store, document, at="2026-09-27T09:00:00Z")["manifest"] == one

    def test_readers_of_the_tenant_only(self, store: Any) -> None:
        with pytest.raises(AuthorizationError):
            build(store, two_tenants(), principal=STRANGER)
        with pytest.raises(PacketError, match="64-character"):
            build(store, two_tenants(), token_file_sha256="abc")
        with pytest.raises(oversight.OversightError):
            build(store, two_tenants(), today="2026-02-30")


class TestOneTenant:
    def test_no_other_tenant_reaches_any_file(self, store: Any, tmp_path: Path) -> None:
        document = two_tenants()
        log = write_log(
            tmp_path / "access.log",
            ("staff@sage.example", "sage-spine", 200, "2026-09-20T10:00:00"),
            ("nurse@other.example", "other-clinic", 200, "2026-09-21T10:00:00"),
            ("nurse@other.example", "other-clinic", 403, "2026-09-22T10:00:00"),
        )
        packet = build(
            store,
            document,
            access_log=access_log.read_file(log),
            ledger=({"verified": True, "entries": 3, "head": ""}, ledger_of(document)),
        )
        for name, data in packet["files"].items():
            text = data.decode("utf-8")
            assert "other-clinic" not in text and "nurse@other.example" not in text, name
        tokens = load(packet, "token-review.json")
        assert tokens["tenant_id"] == "sage-spine"
        assert [i["user_id"] for i in tokens["items"]] == [
            "dana@drchrono.example",
            "staff@sage.example",
        ]
        assert tokens["access_log"]["entries"] == 1
        assert tokens["ledger"]["entries"] == 2

    def test_refusals_from_outside_are_filed_without_naming_anyone(
        self, store: Any, tmp_path: Path
    ) -> None:
        log = AccessLog(tmp_path / "access.log")
        for user, tenant, where, status in (
            ("staff@sage.example", "sage-spine", "sage-spine/audit", 200),
            ("nurse@other.example", "other-clinic", "sage-spine/audit", 403),
            ("nurse@other.example", "other-clinic", "sage-spine/assessments", 403),
            ("admin@other.example", "other-clinic", "sage-spine/audit", 403),
            (None, None, "sage-spine/assessments", 401),
            # Refused on the other tenant's own workspace: not Sage's to see.
            (None, None, "other-clinic/audit", 401),
        ):
            log.record(
                user=user, user_tenant=tenant, method="GET", path=f"/api/v1/tenants/{where}",
                status=status, at=datetime(2026, 9, 22, 9, tzinfo=timezone.utc),
            )  # fmt: skip
        log.close()
        packet = build(store, two_tenants(), access_log=access_log.read_file(log.path))
        for name, data in packet["files"].items():
            text = data.decode("utf-8")
            assert "other-clinic" not in text and "@other.example" not in text, name
        outside = load(packet, "token-review.json")["refused_from_outside"]
        assert outside["other_tenant"] == {
            "callers": 2,
            "requests": 3,
            "first": "2026-09-22T09:00:00.000Z",
            "last": "2026-09-22T09:00:00.000Z",
            "statuses": [403],
            "paths": ["/api/v1/tenants/sage-spine/assessments", "/api/v1/tenants/sage-spine/audit"],
            "more_paths": 0,
            "level": "high",
        }
        assert (outside["unauthenticated"]["requests"], outside["unauthenticated"]["level"]) == (
            1,
            "notice",
        )
        summary = packet["manifest"]["summary"]
        assert summary["refused_from_outside"] == {"other_tenant": 3, "unauthenticated": 1}
        quiet = build(store, two_tenants())["manifest"]["summary"]
        assert "refused_from_outside" not in quiet
        # One high for the other tenant's callers, one notice for the unnamed one.
        assert summary["high"] == quiet["high"] + 1
        assert (
            summary["notices"]
            == quiet["notices"]
            + 1
            + summary["token_review"]["notices"]
            - (quiet["token_review"]["notices"])
        )

    def test_a_quiet_workspace_files_no_refusals(self, store: Any, tmp_path: Path) -> None:
        log = write_log(
            tmp_path / "access.log",
            ("staff@sage.example", "sage-spine", 200, "2026-09-20T10:00:00"),
        )
        tokens = load(build(store, two_tenants(), access_log=access_log.read_file(log)),
                      "token-review.json")  # fmt: skip
        assert tokens["refused_from_outside"] == {"other_tenant": None, "unauthenticated": None}

    def test_a_digest_shared_with_another_tenant_is_still_found(self, store: Any) -> None:
        document = two_tenants()
        document["tokens"][2]["sha256"] = document["tokens"][1]["sha256"]
        tokens = load(build(store, document), "token-review.json")
        staff = next(i for i in tokens["items"] if i["user_id"] == "staff@sage.example")
        assert any("listed 2 times" in f["message"] for f in staff["findings"])
        assert tokens["high"] >= 1

    def test_only_the_tenants_unrecorded_grants_are_listed(self, store: Any) -> None:
        document = two_tenants()
        ledger = ledger_of(document)
        document["tokens"] = [document["tokens"][0]]  # both others removed by hand
        tokens = load(
            build(store, document, ledger=({"verified": True, "entries": 3, "head": ""}, ledger)),
            "token-review.json",
        )
        assert [g["user_id"] for g in tokens["ledger"]["unrecorded"]] == ["staff@sage.example"]
        assert tokens["notices"] == 1

    def test_a_broken_chain_is_refused(self, store: Any) -> None:
        broken: tuple[dict[str, Any], list[dict[str, Any]]] = (
            {"verified": False, "broken_at": 2, "reason": "x", "entries": 1},
            [],
        )
        with pytest.raises(PacketError, match="access log is not a whole chain"):
            build(store, two_tenants(), access_log=broken)
        with pytest.raises(PacketError, match="grant ledger is not a whole chain"):
            build(store, two_tenants(), ledger=broken)


class TestAccessChanges:
    """What was granted and revoked in the tenant during the period, from the ledger."""

    WHOLE = {"verified": True, "entries": 0, "head": ""}

    @staticmethod
    def line(action: str, user: str, at: str, **kw: Any) -> dict[str, Any]:
        return {"action": action, "user_id": user, "tenant_id": kw.get("tenant", "sage-spine"),
                "actor": kw.get("actor", "bill"), "at": at, "as_of": at[:10],
                "roles": ["viewer"], "expires_at": "2026-12-31",
                "on_behalf_of": kw.get("link", ""), "sha256": "b" * 64}  # fmt: skip

    def changes(self, store: Any, ledger: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        packet = build(store, {"tokens": []}, ledger=(self.WHOLE, ledger), **kw)
        return load(packet, "token-review.json")["ledger"]["changes"]  # type: ignore[no-any-return]

    def test_a_partner_granted_and_offboarded_inside_the_period_is_listed(self, store: Any) -> None:
        # Nothing is left in the token file: only the ledger says it happened.
        ledger = [
            self.line("issue", "ops@drchrono.example", "2026-07-02T09:00:00Z",
                      link="partners/drchrono"),
            self.line("revoke", "ops@drchrono.example", "2026-09-01T09:00:00Z",
                      link="partners/drchrono"),
        ]  # fmt: skip
        packet = build(store, {"tokens": []}, ledger=(self.WHOLE, ledger))
        changes = load(packet, "token-review.json")["ledger"]["changes"]
        assert [(c["action"], c["on_behalf_of"]) for c in changes["items"]] == [
            ("issue", "partners/drchrono"),
            ("revoke", "partners/drchrono"),
        ]
        assert changes["items"][0]["digest_prefix"] == "b" * 12
        assert "sha256" not in changes["items"][0]
        assert packet["manifest"]["summary"]["access_changes"] == {
            "since": None, "through": TODAY, "granted": 1, "revoked": 1, "self_granted": 0,
        }  # fmt: skip

    def test_only_the_tenant_and_only_up_to_the_review_date(self, store: Any) -> None:
        ledger = [
            self.line(
                "issue", "nurse@other.example", "2026-09-02T09:00:00Z", tenant="other-clinic"
            ),
            self.line("issue", "staff@sage.example", "2026-09-27T23:59:00Z"),
            self.line("issue", "late@sage.example", "2026-09-28T00:00:01Z"),
        ]
        items = self.changes(store, ledger)["items"]
        assert [c["user_id"] for c in items] == ["staff@sage.example"]

    def test_filed_against_the_last_review_only_the_quarter_since(
        self, store: Any, tmp_path: Path
    ) -> None:
        ledger = [
            self.line("issue", "spring@sage.example", "2026-06-30T20:00:00Z"),
            self.line("issue", "summer@sage.example", "2026-07-01T00:00:00Z"),
        ]
        spring = build(store, {"tokens": []}, today="2026-06-30", at="2026-06-30T21:00:00Z",
                       ledger=(self.WHOLE, ledger[:1]))  # fmt: skip
        earlier = write_packet(spring, tmp_path)
        before = load(spring, "token-review.json")["ledger"]["changes"]
        assert [c["user_id"] for c in before["items"]] == ["spring@sage.example"]
        changes = self.changes(
            store, ledger, previous=earlier, previous_digest=spring["manifest"]["digest"]
        )
        assert (changes["since"], changes["through"]) == ("2026-06-30", TODAY)
        assert [c["user_id"] for c in changes["items"]] == ["summer@sage.example"]

    def test_a_grant_to_oneself_is_a_notice(self, store: Any) -> None:
        ledger = [
            self.line("issue", "Bill", "2026-09-02T09:00:00Z", actor="bill"),
            self.line("revoke", "bill", "2026-09-03T09:00:00Z", actor="bill"),
            self.line("issue", "dana@sage.example", "2026-09-04T09:00:00Z"),
        ]
        quiet = load(build(store, {"tokens": []}, ledger=(self.WHOLE, ledger[2:])), "manifest.json")
        packet = build(store, {"tokens": []}, ledger=(self.WHOLE, ledger))
        tokens = load(packet, "token-review.json")
        assert [c["self_granted"] for c in tokens["ledger"]["changes"]["items"]] == [
            True, False, False,
        ]  # fmt: skip
        # Dana's grant, with no entry and no revocation, is unrecorded in both.
        assert tokens["notices"] == quiet["summary"]["token_review"]["notices"] + 1 == 2
        summary = packet["manifest"]["summary"]
        assert summary["access_changes"]["self_granted"] == 1
        assert summary["notices"] == quiet["summary"]["notices"] + 1

    def test_a_line_whose_time_cannot_be_read_is_listed_not_dropped(self, store: Any) -> None:
        ledger = [self.line("issue", "odd@sage.example", "not a time")]
        assert [c["user_id"] for c in self.changes(store, ledger)["items"]] == ["odd@sage.example"]

    def test_without_a_ledger_there_is_no_change_list(self, store: Any) -> None:
        packet = build(store, two_tenants())
        assert "ledger" not in load(packet, "token-review.json")
        assert "access_changes" not in packet["manifest"]["summary"]


class TestFilingAndChecking:
    def test_a_filed_packet_verifies_against_its_digest(self, store: Any, tmp_path: Path) -> None:
        packet = build(store, two_tenants())
        path = write_packet(packet, tmp_path)
        assert path.name == packet["name"] and not list(tmp_path.glob(".*partial"))
        verdict = verify_packet(path, packet["manifest"]["digest"].upper())
        assert verdict["verified"] and verdict["problems"] == []
        assert set(verdict["files"].values()) == {"ok"}

    def test_a_filed_packet_is_never_overwritten(self, store: Any, tmp_path: Path) -> None:
        write_packet(build(store, two_tenants()), tmp_path)
        with pytest.raises(PacketError, match="a filed packet is not overwritten"):
            write_packet(build(store, two_tenants()), tmp_path)
        with pytest.raises(PacketError, match="not a directory"):
            write_packet(build(store, two_tenants()), tmp_path / "absent")

    def test_an_edited_extra_or_missing_file_is_found(self, store: Any, tmp_path: Path) -> None:
        path = write_packet(build(store, two_tenants()), tmp_path)
        (path / "partner-access.json").write_text("{}\n", encoding="utf-8")
        (path / "register-seal.json").unlink()
        (path / "notes.txt").write_text("added later", encoding="utf-8")
        verdict = verify_packet(path)
        assert not verdict["verified"]
        assert verdict["files"]["partner-access.json"] == "changed"
        assert verdict["files"]["register-seal.json"] == "missing"
        assert verdict["unlisted"] == ["notes.txt"]

    def test_a_file_added_on_its_own_is_found(self, store: Any, tmp_path: Path) -> None:
        packet = build(store, two_tenants())
        path = write_packet(packet, tmp_path)
        (path / "extra.csv").write_text("x", encoding="utf-8")
        verdict = verify_packet(path, packet["manifest"]["digest"])
        assert (verdict["verified"], verdict["problems"]) == (
            False,
            ["extra.csv is not part of the packet"],
        )

    def test_a_manifest_rebuilt_to_fit_is_caught_only_by_the_recorded_digest(
        self, store: Any, tmp_path: Path
    ) -> None:
        packet = build(store, two_tenants())
        recorded = packet["manifest"]["digest"]
        path = write_packet(packet, tmp_path)
        forged = b'{"high": 0}\n'
        (path / "partner-access.json").write_bytes(forged)
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        manifest["files"]["partner-access.json"] = {
            "sha256": hashlib.sha256(forged).hexdigest(),
            "bytes": len(forged),
        }
        manifest["digest"] = access_review._manifest_digest(manifest)
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert verify_packet(path)["verified"]
        verdict = verify_packet(path, recorded)
        assert not verdict["verified"]
        assert verdict["problems"] == [
            "the manifest's digest is not the one recorded when it was filed"
        ]

    def test_a_manifest_edited_without_its_digest_is_found(
        self, store: Any, tmp_path: Path
    ) -> None:
        path = write_packet(build(store, two_tenants()), tmp_path)
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        manifest["generated_by"] = "someone-else"
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert "the manifest does not match its own digest" in verify_packet(path)["problems"]

    def test_what_is_not_a_packet(self, tmp_path: Path) -> None:
        with pytest.raises(PacketError, match="no readable manifest.json"):
            verify_packet(tmp_path)
        (tmp_path / "manifest.json").write_text('{"format": "other"}', encoding="utf-8")
        with pytest.raises(PacketError, match="not an access-review packet"):
            verify_packet(tmp_path)
        with pytest.raises(PacketError, match="64 hex"):
            verify_packet(tmp_path, "abc")


class TestContinuity:
    """Each review held to the last: nothing it recorded may have changed since."""

    SPRING = "2026-06-30"

    def first(
        self, store: Any, tmp_path: Path, log: Path | None = None
    ) -> tuple[Path, dict[str, Any]]:
        packet = build(
            store,
            two_tenants(),
            today=self.SPRING,
            at="2026-06-30T09:00:00Z",
            access_log=access_log.read_file(log) if log else None,
        )
        return write_packet(packet, tmp_path), packet["manifest"]

    def spring_log(self, tmp_path: Path) -> Path:
        return write_log(
            tmp_path / "access.log",
            ("staff@sage.example", "sage-spine", 200, "2026-06-01T10:00:00"),
            ("nurse@other.example", "other-clinic", 200, "2026-06-02T10:00:00"),
        )

    def test_a_clean_quarter_links_to_the_last(self, store: Any, tmp_path: Path) -> None:
        log = self.spring_log(tmp_path)
        earlier, spring = self.first(store, tmp_path, log)
        write_log(log, ("staff@sage.example", "sage-spine", 200, "2026-09-01T10:00:00"))
        oversight.save(
            store, tenant_id="sage-spine", kind="partners", changes={"notes": "Reviewed."},
            principal=OWNER, record_id="drchrono", base_revision=1, at="2026-08-01T00:00:00Z",
        )  # fmt: skip
        packet = build(
            store,
            two_tenants(),
            access_log=access_log.read_file(log),
            previous=earlier,
            previous_digest=spring["digest"],
        )
        linked = load(packet, access_review.CONTINUITY)
        assert linked["previous"] == {
            "name": earlier.name,
            "as_of": self.SPRING,
            "digest": spring["digest"],
        }
        assert (linked["verified"], linked["broken"], linked["unchecked"]) == (True, 0, 0)
        assert linked["register"]["verified"] and linked["access_log"]["extended"]
        assert linked["grant_ledger"] is None  # the spring packet anchored no ledger
        manifest = packet["manifest"]
        assert manifest["inputs"]["previous"] == linked["previous"]
        assert manifest["summary"]["continuity"] == {"verified": True, "broken": 0, "unchecked": 0}
        later = write_packet(packet, tmp_path)
        verdict = verify_packet(later, manifest["digest"], previous=earlier)
        assert verdict["verified"], verdict["problems"]
        assert verdict["files"][access_review.CONTINUITY] == "ok"

    def test_history_rewritten_since_is_high_although_the_sweep_passes(
        self, store: Any, tmp_path: Path
    ) -> None:
        earlier, _ = self.first(store, tmp_path)
        entry = (
            tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / "drchrono" / "1.json"
        )
        data = json.loads(entry.read_text(encoding="utf-8"))
        entry.write_text(json.dumps({**data, "notes": "Rewritten."}), encoding="utf-8")
        packet = build(store, two_tenants(), previous=earlier)
        assert load(packet, "register-verify.json")["verified"]
        linked = load(packet, access_review.CONTINUITY)
        assert (linked["verified"], linked["broken"]) == (False, 1)
        (item,) = [i for i in linked["register"]["items"] if not i["verified"]]
        assert (item["id"], item["broken_at"]) == ("drchrono", 1)
        without = build(store, two_tenants())["manifest"]["summary"]["high"]
        assert packet["manifest"]["summary"]["high"] == without + 1

    def test_a_log_started_afresh_is_high(self, store: Any, tmp_path: Path) -> None:
        log = self.spring_log(tmp_path)
        earlier, _ = self.first(store, tmp_path, log)
        log.unlink()
        write_log(
            log,
            ("staff@sage.example", "sage-spine", 200, "2026-09-01T10:00:00"),
            ("staff@sage.example", "sage-spine", 200, "2026-09-02T10:00:00"),
            ("staff@sage.example", "sage-spine", 200, "2026-09-03T10:00:00"),
        )
        linked = load(
            build(store, two_tenants(), access_log=access_log.read_file(log), previous=earlier),
            access_review.CONTINUITY,
        )
        assert (linked["broken"], linked["access_log"]["extended"]) == (1, False)
        assert "rewritten at or before" in linked["access_log"]["reason"]

    def test_a_log_rotated_since_links_to_the_last_given_its_archive(
        self, store: Any, tmp_path: Path
    ) -> None:
        log = self.spring_log(tmp_path)
        earlier, _ = self.first(store, tmp_path, log)
        write_log(log, ("staff@sage.example", "sage-spine", 200, "2026-07-01T10:00:00"))
        archive = tmp_path / "access.log.2026-07"
        access_log.rotate(log, archive, actor="ops-1")
        write_log(log, ("staff@sage.example", "sage-spine", 403, "2026-09-01T10:00:00"))
        packet = build(
            store, two_tenants(), access_log=access_log.read_files([archive, log]), previous=earlier
        )
        linked = load(packet, access_review.CONTINUITY)
        assert (linked["verified"], linked["broken"]) == (True, 0)
        assert linked["access_log"]["extended"] is True
        # Every request across both files is counted, and the rotation line is not one.
        review = load(packet, "token-review.json")
        assert review["access_log"]["entries"] == 3
        (staff,) = [i for i in review["items"] if i["user_id"] == "staff@sage.example"]
        assert (staff["requests"], staff["refused"]) == (3, 1)
        assert "continues" not in packet["manifest"]["inputs"]["access_log"]
        # The current file alone cannot vouch for the spring anchor: high, with the remedy.
        alone = build(store, two_tenants(), access_log=access_log.read_file(log), previous=earlier)
        linked = load(alone, access_review.CONTINUITY)
        assert (linked["broken"], linked["access_log"]["extended"]) == (1, False)
        assert "give the archives" in linked["access_log"]["reason"]
        assert alone["manifest"]["inputs"]["access_log"]["continues"].startswith("3:")

    def test_an_anchored_log_left_out_is_unchecked_not_passed(
        self, store: Any, tmp_path: Path
    ) -> None:
        earlier, _ = self.first(store, tmp_path, self.spring_log(tmp_path))
        packet = build(store, two_tenants(), previous=earlier)
        linked = load(packet, access_review.CONTINUITY)
        assert (linked["verified"], linked["broken"], linked["unchecked"]) == (False, 0, 1)
        assert linked["access_log"]["extended"] is None
        without = build(store, two_tenants())["manifest"]["summary"]["notices"]
        assert packet["manifest"]["summary"]["notices"] == without + 1

    def test_a_previous_packet_that_cannot_vouch_is_refused(
        self, store: Any, tmp_path: Path
    ) -> None:
        earlier, spring = self.first(store, tmp_path)
        with pytest.raises(PacketError, match="not the one recorded"):
            build(store, two_tenants(), previous=earlier, previous_digest="b" * 64)
        with pytest.raises(PacketError, match="not before 2026-06-30"):
            build(store, two_tenants(), today=self.SPRING, previous=earlier)
        other = FileResultStore(tmp_path / "other")
        stranger = write_packet(
            build_packet(
                other, {"tokens": []}, tenant_id="other-clinic", principal=STRANGER,
                today=self.SPRING, token_file_sha256=SHA,
            ),
            tmp_path,
        )  # fmt: skip
        with pytest.raises(PacketError, match="other-clinic's, not sage-spine's"):
            build(store, two_tenants(), previous=stranger)
        (earlier / "review-queue.json").write_text("{}\n", encoding="utf-8")
        with pytest.raises(PacketError, match="does not verify: review-queue.json"):
            build(store, two_tenants(), previous=earlier)

    def test_verify_holds_a_packet_to_the_one_it_names(self, store: Any, tmp_path: Path) -> None:
        earlier, _ = self.first(store, tmp_path)
        unlinked = write_packet(build(store, two_tenants(), today="2026-07-31"), tmp_path)
        later = write_packet(build(store, two_tenants(), previous=earlier), tmp_path)
        assert verify_packet(later)["verified"]
        assert verify_packet(later, previous=unlinked)["problems"] == [
            "the previous packet is not the one this packet was built against"
        ]
        assert verify_packet(unlinked, previous=earlier)["problems"] == [
            "the packet was not built against a previous packet"
        ]
        (earlier / "register.csv").write_bytes(b"x")
        (problem,) = verify_packet(later, previous=earlier)["problems"]
        assert problem.startswith("the previous packet does not verify: register.csv")


class TestTheFindingsIndex:
    """Each counted finding is listed in the manifest with the file to read it in."""

    @staticmethod
    def index(packet: dict[str, Any], level: str) -> list[tuple[str, str]]:
        return [(f["part"], f["subject"]) for f in packet["manifest"]["summary"]["findings"][level]]

    def test_every_count_comes_with_what_it_counts(self, store: Any, tmp_path: Path) -> None:
        log = write_log(
            tmp_path / "access.log",
            ("dana@drchrono.example", "sage-spine", 200, "2026-09-20T10:00:00"),
        )
        packet = build(store, two_tenants(), access_log=access_log.read_file(log))
        summary = packet["manifest"]["summary"]
        high, notices = self.index(packet, "high"), self.index(packet, "notices")
        assert (len(high), len(notices)) == (summary["high"], summary["notices"]) == (7, 1)
        # The six seeded records lack a BAA, and Dana's token acts for one of them.
        assert [part for part, _ in high] == ["review-queue.json"] * 6 + ["partner-access.json"]
        assert "partners/drchrono (DrChrono)" in [subject for _, subject in high]
        dana = load(packet, "partner-access.json")["items"][0]["digest_prefix"]
        assert high[-1][1] == f"dana@drchrono.example for partners/drchrono ({dana})"
        (queued,) = [
            f
            for f in summary["findings"]["high"]
            if f["subject"].startswith("integrations/drchrono-to-primo")
        ]
        assert queued["messages"] == [
            "Handles PHI without an executed BAA (BAA: Pending review).",
            "No review date set.",
            "No business owner recorded.",
        ]
        # Staff made no request since the log began: dormant, a notice.
        (staff,) = summary["findings"]["notices"]
        assert staff["part"] == "token-review.json"
        assert staff["subject"].startswith("staff@sage.example (")
        assert "confirm the access is still needed" in staff["messages"][0]
        # The manifest is covered by its digest, so the index is part of the record.
        assert load(packet, "manifest.json")["summary"]["findings"] == summary["findings"]

    def test_a_token_with_a_high_finding_and_a_notice_is_in_both(self, store: Any) -> None:
        document = two_tenants()
        document["tokens"][1]["expires_at"] = "2026-10-01"  # expiring, a notice
        document["tokens"][1]["on_behalf_of"] = "nowhere"  # malformed, high
        packet = build(store, document)
        staff = [
            (level, f["messages"])
            for level in ("high", "notices")
            for f in packet["manifest"]["summary"]["findings"][level]
            if f["part"] == "token-review.json" and f["subject"].startswith("staff@sage.example")
        ]
        assert [level for level, _ in staff] == ["high", "notices"]
        assert [m for m in staff[0][1] if "cannot hold it to a register record" in m]
        assert staff[1][1] == ["expires 2026-10-01; renew or let it lapse"]

    def test_grants_nobody_else_approved_or_left_unrecorded_are_listed(self, store: Any) -> None:
        document = two_tenants()
        ledger = ledger_of(document)
        document["tokens"] = [document["tokens"][0]]  # staff's entry removed by hand
        ledger.append({**TestAccessChanges.line("issue", "Bill", "2026-09-02T09:00:00Z"),
                       "sha256": "c" * 64})  # fmt: skip
        packet = build(store, document, ledger=({"verified": True, "entries": 4, "head": ""},
                                                ledger))  # fmt: skip
        notices = packet["manifest"]["summary"]["findings"]["notices"]
        assert [(f["part"], f["subject"]) for f in notices] == [
            ("token-review.json", f"staff@sage.example ({ledger[1]['sha256'][:12]})"),
            ("token-review.json", f"Bill ({'c' * 12})"),
            ("token-review.json", f"Bill ({'c' * 12})"),
        ]
        assert "no revocation on record" in notices[0]["messages"][0]
        assert "no revocation on record" in notices[1]["messages"][0]
        assert notices[2]["messages"] == [
            "granted at 2026-09-02T09:00:00Z by its own holder; nobody else approved it"
        ]
        assert packet["manifest"]["summary"]["notices"] == 3

    def test_refusals_from_outside_are_listed_without_naming_anyone(
        self, store: Any, tmp_path: Path
    ) -> None:
        log = AccessLog(tmp_path / "access.log")
        for user, tenant, status in (
            ("nurse@other.example", "other-clinic", 403),
            ("nurse@other.example", "other-clinic", 403),
            (None, None, 401),
        ):
            log.record(
                user=user, user_tenant=tenant, method="GET",
                path="/api/v1/tenants/sage-spine/audit", status=status,
                at=datetime(2026, 9, 22, 9, tzinfo=timezone.utc),
            )  # fmt: skip
        log.close()
        packet = build(store, {"tokens": []}, access_log=access_log.read_file(log.path))
        found = packet["manifest"]["summary"]["findings"]
        outside = [
            (level, f["subject"], f["messages"])
            for level in ("high", "notices")
            for f in found[level]
            if f["subject"].startswith("requests refused")
        ]
        assert outside == [
            ("high", "requests refused to other tenants' tokens",
             ["2 request(s) from 1 caller(s), 2026-09-22T09:00:00.000Z to "
              "2026-09-22T09:00:00.000Z"]),
            ("notices", "requests refused to no token",
             ["1 request(s) from 1 caller(s), 2026-09-22T09:00:00.000Z to "
              "2026-09-22T09:00:00.000Z"]),
        ]  # fmt: skip
        text = json.dumps(found)
        assert "other-clinic" not in text and "@other.example" not in text

    def test_what_changed_since_the_last_packet_is_listed(self, store: Any, tmp_path: Path) -> None:
        spring = TestContinuity()
        earlier, _ = spring.first(store, tmp_path, spring.spring_log(tmp_path))
        entry = (
            tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / "drchrono" / "1.json"
        )
        data = json.loads(entry.read_text(encoding="utf-8"))
        entry.write_text(json.dumps({**data, "notes": "Rewritten."}), encoding="utf-8")
        # The log the spring packet anchored is not given: unchecked, a notice.
        packet = build(store, two_tenants(), previous=earlier)
        found = packet["manifest"]["summary"]["findings"]
        assert [(f["subject"], f["messages"]) for f in found["high"]
                if f["part"] == access_review.CONTINUITY] == [
            ("partners/drchrono", ["since the previous packet: revision 1 changed since the seal"])
        ]  # fmt: skip
        assert [(f["subject"], f["messages"]) for f in found["notices"]
                if f["part"] == access_review.CONTINUITY] == [
            ("access log", ["not given for this review"])
        ]  # fmt: skip

    def test_a_register_history_that_does_not_verify_is_listed(self, store: Any) -> None:
        sweep = {"verified": False, "items": [
            {"kind": "partners", "id": "drchrono", "verified": False,
             "detail": "revision 1 does not hash to its entry"},
            {"kind": "partners", "id": "primo", "verified": True, "detail": ""},
        ]}  # fmt: skip
        empty: dict[str, Any] = {"items": []}
        found = access_review.findings(empty, empty, sweep, {"items": []}, None)
        assert found == {
            "high": [{"part": "register-verify.json", "subject": "register history",
                      "messages": ["partners/drchrono: revision 1 does not hash to its entry"]}],
            "notices": [],
        }  # fmt: skip


class TestTheCommands:
    AUDIT =("--tenant", "sage-spine", "--actor", "aud-1", "--role", "auditor",
             "--as-of", TODAY)  # fmt: skip
    ISSUE = ("--role", "contributor", "--expires", "2026-12-31", "--actor", "bill",
             "--as-of", TODAY)  # fmt: skip

    @pytest.fixture
    def cli(self, store: Any, capsys: pytest.CaptureFixture[str]) -> Any:
        from ironclad.cli import main  # noqa: PLC0415 -- imports fcntl, POSIX only

        def run(*argv: str) -> tuple[int, Any, str]:
            code = main(list(argv))
            out, err = capsys.readouterr()
            return code, (json.loads(out) if out.strip() else None), err

        return run

    def issued(self, cli: Any, tmp_path: Path) -> Path:
        tokens = tmp_path / "tokens.json"
        cli("tokens", "issue", str(tokens), "--user", "dana@drchrono.example",
            "--tenant", "sage-spine", "--on-behalf-of", "partners/drchrono",
            "--register", str(tmp_path / "volume"), *self.ISSUE)  # fmt: skip
        cli("tokens", "issue", str(tokens), "--user", "nurse@other.example",
            "--tenant", "other-clinic", *self.ISSUE)  # fmt: skip
        return tokens

    def packet(self, cli: Any, tmp_path: Path, tokens: Path, *extra: str) -> tuple[int, Any, str]:
        out = tmp_path / "filed"
        out.mkdir(parents=True, exist_ok=True)
        return cli(  # type: ignore[no-any-return]
            "oversight", "review-packet", *self.AUDIT, "--to", str(tmp_path / "volume"),
            "--tokens", str(tokens), "--out", str(out), *extra,
        )  # fmt: skip

    def test_file_then_verify_with_the_recorded_digest(self, cli: Any, tmp_path: Path) -> None:
        tokens = self.issued(cli, tmp_path)
        log = write_log(
            tmp_path / "access.log",
            ("dana@drchrono.example", "sage-spine", 200, "2026-09-25T08:00:00"),
        )
        code, filed, err = self.packet(
            cli, tmp_path, tokens, "--access-log", str(log),
            "--ledger", str(grant_ledger.default_path(tokens)),
        )  # fmt: skip
        assert code == 0, err
        path = Path(filed["path"])
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["digest"] == filed["digest"]
        assert (
            manifest["inputs"]["token_file_sha256"]
            == hashlib.sha256(tokens.read_bytes()).hexdigest()
        )
        assert manifest["inputs"]["access_log"]["anchor"].startswith("1:")
        assert manifest["inputs"]["grant_ledger"]["entries"] == 2
        review = json.loads((path / "token-review.json").read_text(encoding="utf-8"))
        (item,) = review["items"]
        assert (item["requests"], item["granted_by"]) == (1, "bill")
        # The CSV's CRLF rows are filed as they are.
        assert b"\r\n" in (path / "register.csv").read_bytes()
        # What the counts refer to is printed at filing, as the manifest holds it.
        assert filed["summary"]["findings"] == manifest["summary"]["findings"]
        assert len(filed["summary"]["findings"]["high"]) == filed["summary"]["high"] > 0

        code, verdict, _ = cli("oversight", "verify-packet", str(path), "--digest", filed["digest"])
        assert (code, verdict["verified"]) == (0, True)
        (path / "register.csv").write_bytes(b"record_type\r\n")
        code, verdict, _ = cli("oversight", "verify-packet", str(path), "--digest", filed["digest"])
        assert (code, verdict["files"]["register.csv"]) == (4, "changed")

    def test_a_rotated_log_is_filed_from_its_archive_and_the_current_file(
        self, cli: Any, tmp_path: Path
    ) -> None:
        tokens = self.issued(cli, tmp_path)
        log = write_log(
            tmp_path / "access.log",
            ("dana@drchrono.example", "sage-spine", 200, "2026-08-25T08:00:00"),
        )
        archive = tmp_path / "access.log.1"
        code, rotated, err = cli(
            "access-log", "rotate", str(log), "--to", str(archive), "--actor", "ops-1"
        )
        assert code == 0, err
        write_log(log, ("dana@drchrono.example", "sage-spine", 200, "2026-09-25T08:00:00"))
        logs = ("--access-log", str(archive), "--access-log", str(log))
        code, filed, err = self.packet(cli, tmp_path, tokens, *logs)
        assert code == 0, err
        manifest = json.loads((Path(filed["path"]) / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["inputs"]["access_log"]["entries"] == 3
        assert manifest["inputs"]["access_log"]["anchor"].startswith("3:")
        review = json.loads((Path(filed["path"]) / "token-review.json").read_text(encoding="utf-8"))
        assert review["items"][0]["requests"] == 2
        assert rotated["archive_anchor"].startswith("1:")
        # The archive given after the current file: nothing filed.
        backwards = ("--access-log", str(log), "--access-log", str(archive))
        code, out, err = self.packet(cli, tmp_path / "again", tokens, *backwards)
        assert (code, out) == (4, None) and "no packet is built on it" in err

    def test_the_next_quarter_is_filed_against_the_last(self, cli: Any, tmp_path: Path) -> None:
        tokens = self.issued(cli, tmp_path)
        ledger = grant_ledger.default_path(tokens)
        spring = [a if a != TODAY else "2026-06-30" for a in self.AUDIT]
        code, first, err = cli(
            "oversight", "review-packet", *spring, "--to", str(tmp_path / "volume"),
            "--tokens", str(tokens), "--ledger", str(ledger), "--out", str(tmp_path),
        )  # fmt: skip
        assert code == 0, err
        cli("tokens", "issue", str(tokens), "--user", "staff@sage.example",
            "--tenant", "sage-spine", *self.ISSUE)  # fmt: skip
        linked = ("--previous", first["path"], "--previous-digest", first["digest"])
        code, filed, err = self.packet(cli, tmp_path, tokens, "--ledger", str(ledger), *linked)
        assert code == 0, err
        assert filed["summary"]["continuity"] == {"verified": True, "broken": 0, "unchecked": 0}
        assert filed["summary"]["access_changes"]["since"] == "2026-06-30"
        code, verdict, _ = cli(
            "oversight", "verify-packet", filed["path"], "--previous", first["path"]
        )
        assert (code, verdict["verified"]) == (0, True)

        # The ledger removed and started afresh: whole on its own, and not the
        # ledger the spring review anchored.
        ledger.unlink()
        cli("tokens", "issue", str(tokens), "--user", "temp@sage.example",
            "--tenant", "sage-spine", *self.ISSUE)  # fmt: skip
        assert grant_ledger.verify_file(ledger)["verified"]
        code, filed, err = self.packet(
            cli, tmp_path / "filed", tokens, "--ledger", str(ledger), *linked,
            "--fail-on", "high",
        )  # fmt: skip
        assert code == 4, err
        continuity = json.loads(
            (Path(filed["path"]) / access_review.CONTINUITY).read_text(encoding="utf-8")
        )
        assert continuity["grant_ledger"]["extended"] is False

        code, out, err = self.packet(
            cli, tmp_path / "again", tokens, "--previous", first["path"],
            "--previous-digest", "c" * 64,
        )  # fmt: skip
        assert (code, out) == (2, None) and "not the one recorded" in err

    def test_the_gate_trips_after_filing(self, cli: Any, tmp_path: Path) -> None:
        tokens = self.issued(cli, tmp_path)
        code, filed, _ = self.packet(cli, tmp_path, tokens, "--fail-on", "high")
        assert code == 4 and filed["summary"]["high"] > 0
        assert (Path(filed["path"]) / "manifest.json").is_file()

    def test_a_second_packet_for_the_day_is_refused(self, cli: Any, tmp_path: Path) -> None:
        tokens = self.issued(cli, tmp_path)
        assert self.packet(cli, tmp_path, tokens)[0] == 0
        code, out, err = self.packet(cli, tmp_path, tokens)
        assert (code, out) == (2, None) and "a filed packet is not overwritten" in err

    def test_a_broken_ledger_files_nothing(self, cli: Any, tmp_path: Path) -> None:
        tokens = self.issued(cli, tmp_path)
        ledger = grant_ledger.default_path(tokens)
        lines = ledger.read_text(encoding="utf-8").splitlines()
        ledger.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
        code, out, err = self.packet(cli, tmp_path, tokens, "--ledger", str(ledger))
        assert (code, out) == (4, None) and "not a whole chain" in err
        assert list((tmp_path / "filed").iterdir()) == []

    def test_bad_input_files_nothing(self, cli: Any, tmp_path: Path) -> None:
        tokens = self.issued(cli, tmp_path)
        absent = str(tmp_path / "absent.log")
        code, out, err = self.packet(cli, tmp_path, tokens, "--access-log", absent)
        assert (code, out) == (2, None) and "access log not found" in err
        code, out, err = self.packet(cli, tmp_path, tmp_path / "absent.json")
        assert (code, out) == (2, None) and "token file unreadable" in err
        log = write_log(tmp_path / "access.log")
        code, out, _ = self.packet(
            cli, tmp_path, tokens, "--access-log", str(log), "--dormant-days", "0"
        )
        assert (code, out) == (2, None)
        assert list((tmp_path / "filed").iterdir()) == []
