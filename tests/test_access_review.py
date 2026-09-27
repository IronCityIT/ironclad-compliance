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
        broken = ({"verified": False, "broken_at": 2, "reason": "x", "entries": 1}, [])
        with pytest.raises(PacketError, match="access log is not a whole chain"):
            build(store, two_tenants(), access_log=broken)
        with pytest.raises(PacketError, match="grant ledger is not a whole chain"):
            build(store, two_tenants(), ledger=broken)


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


class TestTheCommands:
    AUDIT = ("--tenant", "sage-spine", "--actor", "aud-1", "--role", "auditor",
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
            "--tenant", "sage-spine", "--on-behalf-of", "partners/drchrono", *self.ISSUE)  # fmt: skip
        cli("tokens", "issue", str(tokens), "--user", "nurse@other.example",
            "--tenant", "other-clinic", *self.ISSUE)  # fmt: skip
        return tokens

    def packet(self, cli: Any, tmp_path: Path, tokens: Path, *extra: str) -> tuple[int, Any, str]:
        out = tmp_path / "filed"
        out.mkdir(exist_ok=True)
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

        code, verdict, _ = cli("oversight", "verify-packet", str(path), "--digest", filed["digest"])
        assert (code, verdict["verified"]) == (0, True)
        (path / "register.csv").write_bytes(b"record_type\r\n")
        code, verdict, _ = cli("oversight", "verify-packet", str(path), "--digest", filed["digest"])
        assert (code, verdict["files"]["register.csv"]) == (4, "changed")

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
