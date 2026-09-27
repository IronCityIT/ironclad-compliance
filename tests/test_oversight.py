"""The partner and integration register, off Firebase.

Three things are held here. The Python policy says what `firestore.rules`
says — parsed out of the rules file, not copied, so the two cannot drift while
both exist. The policy refuses what the rules refuse, case for case with the
emulator suite. And every store keeps the change log the rules kept: one
immutable entry per revision, written with the record, a revision writable
once, no read across tenants. The MariaDB half runs against a real server when
`IRONCLAD_TEST_DSN` is set, as `tests/test_store.py` does.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from ironclad import oversight
from ironclad.errors import AuthorizationError
from ironclad.model.tenant import Principal, Role
from ironclad.oversight import OversightError, StaleRevisionError
from ironclad.store import FileResultStore, StoreError

ROOT = Path(__file__).resolve().parent.parent
RULES = (ROOT / "firestore.rules").read_text(encoding="utf-8")
SEED = json.loads((ROOT / "tenants" / "sage-spine" / "seed.json").read_text(encoding="utf-8"))

TEST_DSN = os.environ.get("IRONCLAD_TEST_DSN", "")
needs_mariadb = pytest.mark.skipif(
    not TEST_DSN, reason="set IRONCLAD_TEST_DSN to run against a real MariaDB"
)

AT = "2026-09-26T12:00:00Z"
LATER = "2026-09-27T09:30:00Z"


def person(user: str, *roles: Role, tenant: str = "sage-spine") -> Principal:
    return Principal(user_id=user, tenant_id=tenant, roles=frozenset(roles))


OWNER = person("owner-1", Role.OWNER)
MANAGER = person("manager-1", Role.COMPLIANCE_MANAGER)
CONTRIBUTOR = person("contrib-1", Role.CONTRIBUTOR)
AUDITOR = person("auditor-1", Role.AUDITOR)
VIEWER = person("viewer-1", Role.VIEWER)
OUTSIDER = person("owner-9", Role.OWNER, tenant="other-clinic")


def _rules_list(expression: str) -> list[str]:
    return re.findall(r"'([^']*)'", expression)


def _rules_function_body(name: str) -> str:
    match = re.search(rf"function {name}\(\) \{{(.*?)\n    \}}", RULES, re.S)
    assert match, f"firestore.rules has no {name}()"
    return match.group(1)


class TestTheRulesAndThePolicyAgree:
    def test_the_field_list(self) -> None:
        body = _rules_function_body("oversightFields")
        assert tuple(_rules_list(body)) == oversight.FIELDS

    def test_the_required_fields(self) -> None:
        body = _rules_function_body("validOversightShape")
        required = re.search(r"hasAll\(\[(.*?)\]\)", body, re.S)
        assert required
        assert tuple(_rules_list(required.group(1))) == oversight.REQUIRED

    def test_every_vocabulary(self) -> None:
        body = _rules_function_body("validOversightShape")
        agreement = re.search(r"let agreement = \[(.*?)\];", body, re.S)
        assert agreement
        assert tuple(_rules_list(agreement.group(1))) == oversight.AGREEMENT
        for field in ("status", "risk"):
            found = re.search(rf"d\.{field} in \[(.*?)\]", body, re.S)
            assert found, field
            assert tuple(_rules_list(found.group(1))) == oversight.VOCABULARY[field]
        for field in ("data_access", "data_flow_direction"):
            found = re.search(rf"optionalOneOf\(d, '{field}', \[(.*?)\]\)", body, re.S)
            assert found, field
            assert tuple(_rules_list(found.group(1))) == oversight.VOCABULARY[field]
        assert "d.agreement_status in agreement" in body
        assert "d.baa_status in agreement" in body

    def test_every_text_bound_and_date(self) -> None:
        body = _rules_function_body("validOversightShape")
        bounds = {k: int(v) for k, v in re.findall(r"optionalText\(d, '(\w+)', (\d+)\)", body)}
        bounds["name"] = int(re.search(r"d\.name\.size\(\) <= (\d+)", body).group(1))  # type: ignore[union-attr]
        assert bounds == oversight.TEXT_BOUNDS
        dates = tuple(re.findall(r"optionalDate\(d, '(\w+)'\)", body))
        assert dates == oversight.DATE_FIELDS

    def test_the_governance_fields_and_the_unrated_proposal(self) -> None:
        guarded = re.search(r"affectedKeys\(\)\.hasAny\(\s*\[(.*?)\]", RULES, re.S)
        assert guarded
        assert set(_rules_list(guarded.group(1))) == set(oversight.GOVERNANCE_FIELDS)
        unrated = dict(re.findall(r"request\.resource\.data\.(\w+) == '([^']+)'", RULES))
        assert {k: unrated[k] for k in oversight.UNRATED} == oversight.UNRATED


def create(principal: Principal = OWNER, **changes: Any) -> dict[str, Any]:
    return oversight.next_revision(
        prior=None,
        changes={"name": "DrChrono", **changes},
        tenant_id="sage-spine",
        principal=principal,
        at=AT,
    )


def edit(prior: dict[str, Any], principal: Principal, **changes: Any) -> dict[str, Any]:
    return oversight.next_revision(
        prior=prior, changes=changes, tenant_id="sage-spine", principal=principal, at=LATER
    )


class TestThePolicy:
    def test_a_contributor_proposes_an_unrated_record(self) -> None:
        record = create(CONTRIBUTOR, notes="EHR vendor")
        assert {k: record[k] for k in oversight.GOVERNANCE_FIELDS} == oversight.UNRATED
        assert record["revision"] == 1
        assert record["created_by"] == record["updated_by"] == "contrib-1"
        assert record["created_at"] == record["updated_at"] == AT
        assert record["tenant_id"] == "sage-spine"

    def test_a_contributor_may_not_rate_a_proposal(self) -> None:
        with pytest.raises(AuthorizationError, match="risk"):
            create(CONTRIBUTOR, risk="Low")

    def test_an_approver_rates_and_a_contributor_edits_around_the_rating(self) -> None:
        proposed = create(CONTRIBUTOR)
        rated = edit(proposed, OWNER, risk="High", baa_status="Executed")
        noted = edit(rated, CONTRIBUTOR, notes="Interface reviewed")
        assert noted["risk"] == "High" and noted["baa_status"] == "Executed"
        assert noted["notes"] == "Interface reviewed"
        assert noted["revision"] == 3
        assert noted["created_by"] == "contrib-1" and noted["created_at"] == AT
        assert noted["updated_by"] == "contrib-1" and noted["updated_at"] == LATER

    def test_a_contributor_may_not_move_a_rating(self) -> None:
        rated = edit(create(), MANAGER, risk="High")
        with pytest.raises(AuthorizationError, match="risk"):
            edit(rated, CONTRIBUTOR, risk="Low")
        # Restating the stored value is not a change, and is allowed.
        assert edit(rated, CONTRIBUTOR, risk="High", notes="x")["risk"] == "High"

    @pytest.mark.parametrize("reader", [AUDITOR, VIEWER])
    def test_a_reader_may_not_write(self, reader: Principal) -> None:
        with pytest.raises(AuthorizationError, match="may not maintain"):
            create(reader)

    def test_another_tenant_may_not_write(self) -> None:
        with pytest.raises(AuthorizationError, match="another tenant"):
            create(OUTSIDER)

    def test_a_record_of_another_tenant_is_not_edited_here(self) -> None:
        foreign = {**create(), "tenant_id": "other-clinic"}
        with pytest.raises(OversightError, match="another tenant"):
            edit(foreign, OWNER, notes="x")

    @pytest.mark.parametrize("field", ["revision", "created_by", "updated_at", "tenant_id"])
    def test_a_caller_never_supplies_a_stamp(self, field: str) -> None:
        with pytest.raises(OversightError, match="stamps are set by the server"):
            create(OWNER, **{field: "forged"})

    @pytest.mark.parametrize(
        ("changes", "named"),
        [
            ({"diagnosis": "PHI parked in a field nobody reviews"}, "'diagnosis' is not"),
            ({"risk": "Approved"}, "risk 'Approved'"),
            ({"baa_status": "Signed"}, "baa_status 'Signed'"),
            ({"data_access": "Everything"}, "data_access"),
            ({"review_due": "31/12/2026"}, "review_due"),
            ({"cert_expiration_date": 20261231}, "cert_expiration_date"),
            ({"notes": "n" * 2001}, "notes is 2001"),
            ({"name": "x" * 121}, "name is 121"),
            ({"name": "   "}, "name must not be empty"),
            ({"business_owner": 7}, "business_owner must be text"),
        ],
    )
    def test_a_malformed_change_is_refused_and_named(self, changes: dict, named: str) -> None:
        with pytest.raises(OversightError) as refused:
            create(**changes)
        assert named in str(refused.value)

    def test_the_seeded_revision_zero_edits_to_revision_one(self) -> None:
        seeded = {k: v for k, v in create().items() if k != "revision"}
        assert edit(seeded, OWNER, notes="first edit")["revision"] == 1


class TestTheSageSeed:
    def test_every_seed_record_fits_the_register(self) -> None:
        for kind in oversight.KINDS:
            for entry in SEED["oversight"][kind]:
                assert oversight.content_problems(entry) == [], entry["name"]

    def test_every_seed_record_has_a_distinct_stable_id(self) -> None:
        ids = [
            oversight.seed_record_id(e["name"])
            for kind in oversight.KINDS
            for e in SEED["oversight"][kind]
        ]
        assert len(ids) == len(set(ids))
        assert all(oversight.check_record_id(i) == i for i in ids)


# ------------------------------------------------------------------ stores


class RegisterContract:
    """What every store owes the register. Subclassed per backend."""

    def store(self, tmp_path: Path) -> Any:
        raise NotImplementedError

    def save(self, store: Any, principal: Principal = OWNER, **kw: Any) -> dict[str, Any]:
        kw.setdefault("changes", {"name": "DrChrono"})
        kw.setdefault("at", AT)
        return oversight.save(store, tenant_id=principal.tenant_id, kind="partners",
                              principal=principal, **kw)  # fmt: skip

    def test_a_record_and_its_first_entry_read_back(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        saved = self.save(store, changes={"name": "PRIMO", "data_access": "PHI"})
        stored = store.get_oversight("sage-spine", "partners", saved["id"])
        assert stored == {k: v for k, v in saved.items() if k != "id"}
        assert store.oversight_history("sage-spine", "partners", saved["id"]) == [stored]
        assert store.verify_oversight("sage-spine", "partners", saved["id"])["verified"]

    def test_an_edit_adds_an_entry_and_keeps_the_first(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        first = self.save(store, CONTRIBUTOR)
        self.save(store, OWNER, record_id=first["id"], changes={"risk": "High"}, at=LATER)
        self.save(store, CONTRIBUTOR, record_id=first["id"], changes={"notes": "x"}, at=LATER)
        entries = store.oversight_history("sage-spine", "partners", first["id"])
        assert [e["revision"] for e in entries] == [1, 2, 3]
        assert [e["updated_by"] for e in entries] == ["contrib-1", "owner-1", "contrib-1"]
        assert entries[0]["risk"] == "Unrated" and entries[2]["risk"] == "High"
        assert store.get_oversight("sage-spine", "partners", first["id"]) == entries[2]
        verdict = store.verify_oversight("sage-spine", "partners", first["id"])
        assert verdict == {"verified": True, "revisions": 3, "broken_at": None, "detail": ""}

    def test_two_editors_on_one_revision_cannot_both_land(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        first = self.save(store)
        prior = store.get_oversight("sage-spine", "partners", first["id"])
        mine = edit(prior, OWNER, notes="mine")
        theirs = edit(prior, MANAGER, notes="theirs")
        store.put_oversight("sage-spine", "partners", first["id"], mine)
        with pytest.raises(StaleRevisionError):
            store.put_oversight("sage-spine", "partners", first["id"], theirs)
        assert store.get_oversight("sage-spine", "partners", first["id"])["notes"] == "mine"
        assert len(store.oversight_history("sage-spine", "partners", first["id"])) == 2

    def test_a_form_loaded_from_an_old_revision_is_refused_as_stale(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        first = self.save(store)
        self.save(store, record_id=first["id"], changes={"notes": "moved on"}, base_revision=1)
        with pytest.raises(StaleRevisionError, match="against revision 1"):
            self.save(store, record_id=first["id"], changes={"notes": "old"}, base_revision=1)

    def test_a_revision_cannot_be_skipped(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        first = self.save(store)
        prior = store.get_oversight("sage-spine", "partners", first["id"])
        skipped = {**edit(prior, OWNER, notes="x"), "revision": 3}
        with pytest.raises(StaleRevisionError):
            store.put_oversight("sage-spine", "partners", first["id"], skipped)
        assert len(store.oversight_history("sage-spine", "partners", first["id"])) == 1

    def test_the_store_refuses_a_record_the_policy_would_not_produce(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        bad = {**create(), "risk": "Approved"}
        with pytest.raises(OversightError, match="risk 'Approved'"):
            store.put_oversight("sage-spine", "partners", "drchrono", bad)
        with pytest.raises(OversightError, match="tenant_id does not match"):
            store.put_oversight("other-clinic", "partners", "drchrono", create())
        assert store.get_oversight("sage-spine", "partners", "drchrono") is None

    @pytest.mark.parametrize("record_id", ["../other-clinic", "a/b", "", "x" * 129, "a b"])
    def test_a_record_id_cannot_escape_or_be_empty(self, tmp_path: Path, record_id: str) -> None:
        store = self.store(tmp_path)
        with pytest.raises(OversightError, match="not a usable register record id"):
            store.put_oversight("sage-spine", "partners", record_id, create())

    def test_an_unknown_register_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(OversightError, match="not a register"):
            self.store(tmp_path).list_oversight("sage-spine", "vendors")

    def test_no_read_crosses_a_tenant(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        store.put_oversight("sage-spine", "partners", "drchrono", create())
        foreign = oversight.next_revision(
            prior=None, changes={"name": "Theirs"}, tenant_id="other-clinic",
            principal=OUTSIDER, at=AT,
        )  # fmt: skip
        store.put_oversight("other-clinic", "partners", "drchrono", foreign)
        assert store.get_oversight("sage-spine", "partners", "drchrono")["name"] == "DrChrono"
        assert store.get_oversight("other-clinic", "partners", "drchrono")["name"] == "Theirs"
        assert [r["name"] for r in store.list_oversight("sage-spine", "partners")] == ["DrChrono"]
        assert store.list_oversight("sage-spine", "integrations") == []
        with pytest.raises(AuthorizationError):
            oversight.records(store, tenant_id="sage-spine", kind="partners", principal=OUTSIDER)
        with pytest.raises(AuthorizationError):
            oversight.history(store, tenant_id="sage-spine", kind="partners",
                              record_id="drchrono", principal=OUTSIDER)  # fmt: skip

    def test_every_member_reads_the_register_and_its_history(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        store.put_oversight("sage-spine", "partners", "drchrono", create())
        for reader in (AUDITOR, VIEWER, CONTRIBUTOR):
            listed = oversight.records(store, tenant_id="sage-spine", kind="partners",
                                       principal=reader)  # fmt: skip
            assert [r["id"] for r in listed] == ["drchrono"]
            entries = oversight.history(store, tenant_id="sage-spine", kind="partners",
                                        record_id="drchrono", principal=reader)  # fmt: skip
            assert len(entries) == 1

    def test_the_register_lists_by_name(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        for name in ("primo", "Fujifilm", "DrChrono"):
            self.save(store, changes={"name": name})
        names = [r["name"] for r in store.list_oversight("sage-spine", "partners")]
        assert names == ["DrChrono", "Fujifilm", "primo"]

    def test_the_sage_seed_loads_once_and_is_attributed(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        loaded = oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        expected = sum(len(SEED["oversight"][k]) for k in oversight.KINDS)
        assert len(loaded["created"]) == expected and loaded["skipped"] == []
        again = oversight.load_seed(store, SEED, principal=OWNER, at=LATER)
        assert again["created"] == [] and len(again["skipped"]) == expected
        for kind in oversight.KINDS:
            for entry in SEED["oversight"][kind]:
                record_id = oversight.seed_record_id(entry["name"])
                entries = store.oversight_history("sage-spine", kind, record_id)
                assert len(entries) == 1
                assert entries[0]["created_by"] == "owner-1"
                assert {k: entries[0][k] for k in entry} == entry

    def test_a_contributor_may_not_load_a_rated_seed(self, tmp_path: Path) -> None:
        with pytest.raises(AuthorizationError, match="rated seed"):
            oversight.load_seed(self.store(tmp_path), SEED, principal=CONTRIBUTOR)


class TestTheVolume(RegisterContract):
    def store(self, tmp_path: Path) -> Any:
        return FileResultStore(tmp_path / "volume")

    def test_the_layout_is_tenant_prefixed_one_file_per_revision(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        store.put_oversight("sage-spine", "partners", "drchrono", create())
        base = tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / "drchrono"
        assert sorted(p.name for p in base.iterdir()) == ["1.json"]

    def test_an_edited_entry_is_caught_and_named(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        first = self.save(store)
        self.save(store, record_id=first["id"], changes={"notes": "x"}, at=LATER)
        path = (
            tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / first["id"] / "1.json"
        )
        entry = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({**entry, "created_by": "someone-else"}), encoding="utf-8")
        verdict = store.verify_oversight("sage-spine", "partners", first["id"])
        assert verdict["verified"] is False and verdict["broken_at"] == 2
        assert "creation stamp" in verdict["detail"]

    def test_a_removed_entry_is_caught(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        first = self.save(store)
        self.save(store, record_id=first["id"], changes={"notes": "x"}, at=LATER)
        (
            tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / first["id"] / "1.json"
        ).unlink()
        verdict = store.verify_oversight("sage-spine", "partners", first["id"])
        assert verdict["verified"] is False and "revision 1" in verdict["detail"]

    def test_an_unreadable_entry_is_named_not_skipped(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        store.put_oversight("sage-spine", "partners", "drchrono", create())
        path = tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / "drchrono" / "1.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(StoreError, match="not a readable register entry"):
            store.get_oversight("sage-spine", "partners", "drchrono")

    def test_a_writer_that_checked_before_the_other_landed_is_still_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The revision check reads the directory, then writes: a second
        # writer can pass the check just before the first one lands. The
        # exclusive create is what refuses it then, rather than overwriting.
        store = self.store(tmp_path)
        store.put_oversight("sage-spine", "partners", "drchrono", create())
        prior = store.get_oversight("sage-spine", "partners", "drchrono")
        store.put_oversight("sage-spine", "partners", "drchrono", edit(prior, OWNER, notes="mine"))
        monkeypatch.setattr(FileResultStore, "_oversight_revisions", staticmethod(lambda _d: [1]))
        with pytest.raises(StaleRevisionError, match="saved by someone else first"):
            store.put_oversight(
                "sage-spine", "partners", "drchrono", edit(prior, MANAGER, notes="theirs")
            )
        monkeypatch.undo()
        assert store.get_oversight("sage-spine", "partners", "drchrono")["notes"] == "mine"

    def test_no_temporary_file_is_left_behind(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        store.put_oversight("sage-spine", "partners", "drchrono", create())
        with pytest.raises(StaleRevisionError):
            store.put_oversight("sage-spine", "partners", "drchrono", create())
        base = tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / "drchrono"
        assert sorted(p.name for p in base.iterdir()) == ["1.json"]


@needs_mariadb
class TestMariaDB(RegisterContract):
    def store(self, tmp_path: Path) -> Any:
        from ironclad.store.mariadb import MariaDBResultStore  # noqa: PLC0415

        store = MariaDBResultStore(TEST_DSN)
        store.init_schema()
        connection = store._connect()  # noqa: SLF001 — the test owns this database
        try:
            with connection.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE oversight_history")
                cursor.execute("TRUNCATE TABLE oversight_records")
            connection.commit()
        finally:
            connection.close()
        return store

    def _execute(self, store: Any, sql: str) -> None:
        connection = store._connect()  # noqa: SLF001
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql)
            connection.commit()
        finally:
            connection.close()

    def test_an_edited_record_row_is_caught(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        store.put_oversight("sage-spine", "partners", "drchrono", create())
        self._execute(
            store,
            "UPDATE oversight_records SET record = JSON_SET(record, '$.risk', 'Low') "
            "WHERE record_id = 'drchrono'",
        )
        verdict = store.verify_oversight("sage-spine", "partners", "drchrono")
        assert verdict["verified"] is False and "latest history entry" in verdict["detail"]

    def test_a_refused_write_leaves_no_history_behind(self, tmp_path: Path) -> None:
        # All or nothing: the history row goes in first, and a record that
        # is not at the revision before rolls it back.
        store = self.store(tmp_path)
        orphan = {**create(), "revision": 2}
        with pytest.raises(StaleRevisionError):
            store.put_oversight("sage-spine", "partners", "drchrono", orphan)
        assert store.oversight_history("sage-spine", "partners", "drchrono") == []
        assert store.get_oversight("sage-spine", "partners", "drchrono") is None
