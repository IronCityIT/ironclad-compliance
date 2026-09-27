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

import csv
import hashlib
import io
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
ATTENTION = json.loads(
    (ROOT / "tests" / "fixtures" / "oversight-attention.json").read_text(encoding="utf-8")
)
EXPORT = json.loads(
    (ROOT / "tests" / "fixtures" / "oversight-export.json").read_text(encoding="utf-8")
)

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


class TestTheReviewQueue:
    """`attentionFindings()` in the dashboard, as Python, held to one table."""

    @pytest.mark.parametrize("case", ATTENTION["cases"], ids=lambda c: c["name"])
    def test_the_shared_specification(self, case: dict[str, Any]) -> None:
        record = {**ATTENTION["base"], **case["patch"]}
        assert oversight.attention_findings(record, ATTENTION["today"]) == case["expected"]

    def test_the_window_is_the_dashboards(self) -> None:
        assert ATTENTION["window_days"] == oversight.ATTENTION_WINDOW_DAYS
        core = (ROOT / "dashboard" / "public" / "oversight-core.js").read_text(encoding="utf-8")
        window = re.search(r"ATTENTION_WINDOW_DAYS = (\d+);", core)
        assert window and int(window.group(1)) == oversight.ATTENTION_WINDOW_DAYS

    def test_the_review_horizon_is_the_dashboards(self) -> None:
        assert ATTENTION["review_horizon_days"] == oversight.REVIEW_HORIZON_DAYS
        core = (ROOT / "dashboard" / "public" / "oversight-core.js").read_text(encoding="utf-8")
        horizon = re.search(r"REVIEW_HORIZON_DAYS = (\d+);", core)
        assert horizon and int(horizon.group(1)) == oversight.REVIEW_HORIZON_DAYS

    def test_no_sage_seed_review_is_scheduled_beyond_the_horizon(self) -> None:
        distant = [
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if "review-too-distant"
            in [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
        ]
        assert distant == []

    def test_the_elevated_ratings_are_the_dashboards_and_in_the_vocabulary(self) -> None:
        assert set(oversight.ELEVATED_RISK) <= set(oversight.VOCABULARY["risk"])
        core = (ROOT / "dashboard" / "public" / "oversight-core.js").read_text(encoding="utf-8")
        listed = re.search(r"ELEVATED_RISK = \[([^\]]*)\];", core)
        assert listed and re.findall(r'"([^"]+)"', listed.group(1)) == list(oversight.ELEVATED_RISK)

    def test_the_settled_agreements_are_the_dashboards_and_in_the_vocabulary(self) -> None:
        assert set(oversight.AGREEMENT_SETTLED) <= set(oversight.AGREEMENT)
        core = (ROOT / "dashboard" / "public" / "oversight-core.js").read_text(encoding="utf-8")
        listed = re.search(r"AGREEMENT_SETTLED = \[([^\]]*)\];", core)
        assert listed and re.findall(r'"([^"]+)"', listed.group(1)) == list(
            oversight.AGREEMENT_SETTLED
        )

    def test_the_sage_seed_names_every_active_record_without_an_agreement(self) -> None:
        unsigned = sorted(
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if "agreement-not-executed"
            in [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
        )
        assert unsigned == ["DrChrono"]

    def test_no_sage_seed_record_is_active_and_unrated(self) -> None:
        # DrChrono is the seed's one Active record, and it is rated High.
        unrated = [
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if "active-unrated"
            in [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
        ]
        assert unrated == []
        drchrono = {**SEED["oversight"]["partners"][0], "risk": "Unrated"}
        assert drchrono["status"] == "Active"
        found = oversight.attention_findings(drchrono, "2026-09-26")
        assert ("high", "active-unrated") in [(f["level"], f["code"]) for f in found]
        assert "risk-unrated" not in [f["code"] for f in found]
        assert "active-unrated" in oversight.ACCESS_CODES

    def test_no_sage_seed_record_is_active_with_unknown_data_access(self) -> None:
        # DrChrono, the seed's one Active record, handles PHI.
        unknown = [
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if "active-access-unknown"
            in [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
        ]
        assert unknown == []
        drchrono = {**SEED["oversight"]["partners"][0], "data_access": "Unknown"}
        assert drchrono["status"] == "Active"
        found = oversight.attention_findings(drchrono, "2026-09-26")
        assert ("high", "active-access-unknown") in [(f["level"], f["code"]) for f in found]
        assert "data-access-unknown" not in [f["code"] for f in found]
        assert "phi-without-baa" not in [f["code"] for f in found]
        assert "active-access-unknown" in oversight.ACCESS_CODES

    def test_every_sage_seed_record_surfaces_its_missing_baa(self) -> None:
        for kind in oversight.KINDS:
            for entry in SEED["oversight"][kind]:
                codes = [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
                assert "phi-without-baa" in codes, entry["name"]

    def test_the_sage_seed_names_its_integrations_as_ownerless_and_scopes_all_phi(self) -> None:
        found = {
            entry["name"]: [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
        }
        ownerless = sorted(name for name, codes in found.items() if "owner-unassigned" in codes)
        assert ownerless == sorted(e["name"] for e in SEED["oversight"]["integrations"])
        assert not [name for name, codes in found.items() if "phi-scope-missing" in codes]

    def test_the_sage_seed_names_every_phi_partner_with_no_direction_of_flow(self) -> None:
        unrecorded = sorted(
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if "phi-flow-unrecorded"
            in [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
        )
        # Each integration records its direction; no partner does yet.
        assert unrecorded == sorted(e["name"] for e in SEED["oversight"]["partners"])

    def test_every_high_rated_sage_seed_record_asks_for_a_dated_assurance(self) -> None:
        undated = sorted(
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if "assurance-undated"
            in [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
        )
        elevated = sorted(
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if entry.get("risk") in oversight.ELEVATED_RISK
            and not entry.get("cert_expiration_date")
        )
        assert elevated and undated == elevated

    def test_no_sage_seed_record_dates_an_assurance_it_does_not_name(self) -> None:
        # Every seed record names its pending assurance and dates none of them.
        unnamed = [
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if "assurance-unnamed"
            in [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
        ]
        assert unnamed == []
        dated = {**SEED["oversight"]["partners"][0], "cert_expiration_date": "2027-06-30"}
        assert "assurance-unnamed" not in [
            f["code"] for f in oversight.attention_findings(dated, "2026-09-26")
        ]
        dated["assurance"] = ""
        assert "assurance-unnamed" in [
            f["code"] for f in oversight.attention_findings(dated, "2026-09-26")
        ]

    def test_no_sage_seed_record_dates_a_baa_it_does_not_mark_executed(self) -> None:
        # No seed BAA is executed, and none carries an execution date.
        contradicted = [
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if "baa-date-unexecuted"
            in [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
        ]
        assert contradicted == []
        dated = {**SEED["oversight"]["partners"][0], "baa_execution_date": "2026-01-15"}
        assert dated["baa_status"] != "Executed"
        assert "baa-date-unexecuted" in [
            f["code"] for f in oversight.attention_findings(dated, "2026-09-26")
        ]
        dated["baa_status"] = "Executed"
        assert "baa-date-unexecuted" not in [
            f["code"] for f in oversight.attention_findings(dated, "2026-09-26")
        ]

    def test_no_sage_seed_record_scopes_phi_it_says_it_does_not_handle(self) -> None:
        # Every seed record handles PHI and names its scope.
        contradicted = [
            entry["name"]
            for kind in oversight.KINDS
            for entry in SEED["oversight"][kind]
            if "phi-scope-contradicted"
            in [f["code"] for f in oversight.attention_findings(entry, "2026-09-26")]
        ]
        assert contradicted == []
        # DrChrono moved off PHI: its missing BAA drops out, and its scope says why it should not.
        drchrono = {**SEED["oversight"]["partners"][0], "data_access": "PII"}
        found = [
            (f["level"], f["code"]) for f in oversight.attention_findings(drchrono, "2026-09-26")
        ]
        assert "phi-without-baa" not in [code for _, code in found]
        assert ("notice", "phi-scope-contradicted") in found
        assert "phi-scope-contradicted" not in oversight.ACCESS_CODES

    @pytest.mark.parametrize("bad", ["", "2026-9-26", "2026-02-30", "26/09/2026", "today"])
    def test_a_date_that_is_not_a_calendar_day_is_refused(self, bad: str) -> None:
        with pytest.raises(OversightError, match="YYYY-MM-DD"):
            oversight.check_as_of(bad)
        with pytest.raises(OversightError):
            oversight.attention_findings(ATTENTION["base"], bad)


class TestTheRegisterExport:
    """`registerCsv()` in the dashboard, as Python, held to one file byte for byte."""

    def test_the_shared_specification(self) -> None:
        assert oversight.register_csv(EXPORT["register"], EXPORT["today"]) == EXPORT["csv"]
        assert (
            oversight.export_file_name(EXPORT["tenant_id"], EXPORT["today"]) == (EXPORT["filename"])
        )

    def test_it_reads_back_as_the_register_with_formulas_defused(self) -> None:
        text = oversight.register_csv(EXPORT["register"], EXPORT["today"])
        head, *rows = list(csv.reader(io.StringIO(text, newline="")))
        assert tuple(head) == oversight.EXPORT_COLUMNS
        by_id = {row[1]: dict(zip(head, row, strict=True)) for row in rows}
        acme = by_id["acme-imaging"]
        source = EXPORT["register"]["partners"][1]
        # Delimiters, quotes and line breaks survive; nothing is evaluated.
        assert acme["name"] == "Acme Imaging, Inc." and acme["notes"] == source["notes"]
        for field in ("business_owner", "technical_owner", "phi_scope", "assurance"):
            assert acme[field] == "'" + source[field], field
        # The inventory keeps a retired record, with no finding against it.
        assert (by_id["zeta-billing"]["status"], by_id["zeta-billing"]["attention"]) == (
            "Retired",
            "",
        )
        assert by_id["ehr-feed"]["attention_level"] == "high"
        assert [row[0] for row in rows] == ["Partner"] * 3 + ["Integration"] * 2

    def test_the_date_is_a_calendar_day(self) -> None:
        with pytest.raises(OversightError, match="YYYY-MM-DD"):
            oversight.register_csv(EXPORT["register"], "2026-02-30")

    @pytest.mark.parametrize(
        ("tenant", "name"),
        [("../sage spine", "sagespine"), ("", "tenant"), ("a/b\\c:d", "abcd")],
    )
    def test_the_file_name_carries_nothing_a_filesystem_would_act_on(
        self, tenant: str, name: str
    ) -> None:
        assert oversight.export_file_name(tenant, "2026-09-27") == (
            f"oversight-register-{name}-2026-09-27.csv"
        )


class TestTheSealItself:
    """A seal is only an anchor if an edit to it shows; checked without a store."""

    def seal(self) -> dict[str, Any]:
        store = FileResultStore(Path(self.tmp) / "volume")
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        return oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR, at=AT)

    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path: Path) -> None:
        self.tmp = tmp_path

    def test_an_entry_digest_ignores_key_order_and_nothing_else(self) -> None:
        record = create()
        assert oversight.entry_digest(record) == oversight.entry_digest(
            dict(reversed(record.items()))
        )
        assert oversight.entry_digest(record) != oversight.entry_digest({**record, "notes": " "})

    def test_a_seal_is_its_own_earlier_self(self) -> None:
        seal = self.seal()
        result = oversight.compare_seals(seal, seal)
        assert (result["verified"], result["new_records"]) == (True, [])
        assert {i["detail"] for i in result["items"]} == {""}

    def test_a_seal_edited_after_it_was_taken_is_refused(self) -> None:
        seal = self.seal()
        seal["records"][0]["entries"][0] = "0" * 64
        with pytest.raises(OversightError, match="its own digest"):
            oversight.check_seal(seal)

    def test_a_seal_with_a_record_dropped_is_refused(self) -> None:
        seal = self.seal()
        seal["records"].pop()
        with pytest.raises(OversightError, match="its own digest"):
            oversight.compare_seals(seal, self.seal())

    @pytest.mark.parametrize(
        ("mutate", "named"),
        [
            (lambda s: s.update(format="something-else/1"), "not a register seal"),
            (lambda s: s.update(tenant_id=""), "tenant_id is missing"),
            (lambda s: s["records"][0].update(kind="vendors"), "not a list of sealed records"),
            (lambda s: s["records"][0].update(revisions=9), "not a list of sealed records"),
        ],
    )
    def test_a_malformed_seal_is_refused_and_named(self, mutate: Any, named: str) -> None:
        seal = self.seal()
        mutate(seal)
        with pytest.raises(OversightError) as refused:
            oversight.check_seal(seal)
        assert named in str(refused.value)


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

    def test_a_refused_writer_cannot_tell_whether_a_record_exists(self, tmp_path: Path) -> None:
        # Authorization is settled before the store is asked for the record,
        # so an id that exists and one that does not are refused alike.
        store = self.store(tmp_path)
        first = self.save(store)
        for principal in (OUTSIDER, VIEWER, AUDITOR):
            refusals = []
            for record_id in (first["id"], "no-such-record"):
                with pytest.raises(AuthorizationError) as refused:
                    oversight.save(
                        store, tenant_id="sage-spine", kind="partners", principal=principal,
                        record_id=record_id, changes={"notes": "x"}, at=AT,
                    )  # fmt: skip
                refusals.append(str(refused.value))
            assert refusals[0] == refusals[1], principal.user_id
        with pytest.raises(oversight.RecordNotFoundError):
            self.save(store, record_id="no-such-record", changes={"notes": "x"})

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

    def test_the_review_queue_spans_both_kinds_high_first(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        clean = {k: v for k, v in ATTENTION["base"].items() if k != "status"}
        self.save(store, changes={**clean, "name": "Aardvark Labs"})
        self.save(store, changes={**clean, "name": "Zeta Fax", "review_due": "2026-10-01"})
        queue = oversight.attention_queue(
            store, tenant_id="sage-spine", principal=VIEWER, today="2026-09-26"
        )
        seeded = len(SEED["oversight"]["partners"]) + len(SEED["oversight"]["integrations"])
        # Aardvark Labs is clean and absent; Zeta Fax is a notice, after every high.
        assert (queue["records"], queue["high"]) == (seeded + 1, seeded)
        assert [i["name"] for i in queue["items"]][-1] == "Zeta Fax"
        assert "Aardvark Labs" not in [i["name"] for i in queue["items"]]
        highs = [i["name"] for i in queue["items"] if i["level"] == "high"]
        assert highs == sorted(highs, key=str.casefold)
        assert {i["kind"] for i in queue["items"]} == set(oversight.KINDS)
        assert all(i["id"] and i["revision"] == 1 for i in queue["items"])

    def test_the_review_queue_is_the_tenants_own(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        with pytest.raises(AuthorizationError):
            oversight.attention_queue(
                store, tenant_id="sage-spine", principal=OUTSIDER, today="2026-09-26"
            )
        outsider_view = oversight.attention_queue(
            store, tenant_id="other-clinic", principal=OUTSIDER, today="2026-09-26"
        )
        assert outsider_view["items"] == []

    def test_the_export_is_every_record_the_tenant_holds(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        retired = self.save(store, changes={"name": "Old Fax", "status": "Retired"})
        export = oversight.export_register(
            store, tenant_id="sage-spine", principal=AUDITOR, today="2026-09-26"
        )
        seeded = {k: len(SEED["oversight"][k]) for k in oversight.KINDS}
        assert export["records"] == {**seeded, "partners": seeded["partners"] + 1}
        assert export["filename"] == "oversight-register-sage-spine-2026-09-26.csv"
        assert export["sha256"] == hashlib.sha256(export["csv"].encode("utf-8")).hexdigest()
        rows = list(csv.reader(io.StringIO(export["csv"], newline="")))[1:]
        assert len(rows) == sum(export["records"].values())
        assert retired["id"] in [row[1] for row in rows]
        assert {row[2] for row in rows} == {"sage-spine"}

    def test_the_export_is_the_tenants_own(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        with pytest.raises(AuthorizationError):
            oversight.export_register(
                store, tenant_id="sage-spine", principal=OUTSIDER, today="2026-09-26"
            )
        own = oversight.export_register(
            store, tenant_id="other-clinic", principal=OUTSIDER, today="2026-09-26"
        )
        assert own["records"] == {"partners": 0, "integrations": 0}
        assert own["csv"].count("\r\n") == 1

    def test_a_contributor_may_not_load_a_rated_seed(self, tmp_path: Path) -> None:
        with pytest.raises(AuthorizationError, match="rated seed"):
            oversight.load_seed(self.store(tmp_path), SEED, principal=CONTRIBUTOR)

    def test_the_sweep_verifies_every_record_of_both_kinds(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        first = oversight.seed_record_id(SEED["oversight"]["partners"][0]["name"])
        self.save(store, record_id=first, changes={"notes": "x"}, at=LATER)
        sweep = oversight.verify_register(store, tenant_id="sage-spine", principal=AUDITOR)
        seeded = sum(len(SEED["oversight"][k]) for k in oversight.KINDS)
        assert (sweep["records"], sweep["broken"], sweep["verified"]) == (seeded, 0, True)
        assert {i["kind"] for i in sweep["items"]} == set(oversight.KINDS)
        revisions = {i["id"]: i["revisions"] for i in sweep["items"]}
        assert revisions.pop(first) == 2
        assert set(revisions.values()) == {1}

    def test_the_sweep_is_the_tenants_own(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        with pytest.raises(AuthorizationError):
            oversight.verify_register(store, tenant_id="sage-spine", principal=OUTSIDER)
        own = oversight.verify_register(store, tenant_id="other-clinic", principal=OUTSIDER)
        assert (own["records"], own["verified"], own["items"]) == (0, True, [])

    def test_a_later_seal_extends_an_earlier_one(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        earlier = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR, at=AT)
        seeded = sum(len(SEED["oversight"][k]) for k in oversight.KINDS)
        assert len(earlier["records"]) == seeded
        again = oversight.seal_register(store, tenant_id="sage-spine", principal=VIEWER, at=LATER)
        assert again["digest"] == earlier["digest"]
        first = oversight.seed_record_id(SEED["oversight"]["partners"][0]["name"])
        self.save(store, record_id=first, changes={"notes": "x"}, at=LATER)
        added = self.save(store, changes={"name": "Fax relay"}, at=LATER)
        later = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        assert later["digest"] != earlier["digest"]
        result = oversight.compare_seals(earlier, later)
        assert (result["records"], result["broken"], result["verified"]) == (seeded, 0, True)
        assert result["new_records"] == [{"kind": "partners", "id": added["id"]}]
        (moved,) = [i for i in result["items"] if i["revisions"] != i["sealed_revisions"]]
        assert (moved["id"], moved["detail"]) == (first, "1 revision(s) added since the seal")

    def test_the_seal_is_the_tenants_own(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        with pytest.raises(AuthorizationError):
            oversight.seal_register(store, tenant_id="sage-spine", principal=OUTSIDER)
        own = oversight.seal_register(store, tenant_id="other-clinic", principal=OUTSIDER)
        assert own["records"] == []
        mine = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        with pytest.raises(OversightError, match="different tenants"):
            oversight.compare_seals(mine, own)


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

    def test_the_sweep_names_the_record_whose_history_was_edited(self, tmp_path: Path) -> None:
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        record_id = oversight.seed_record_id(SEED["oversight"]["integrations"][0]["name"])
        path = tmp_path / "volume" / "sage-spine" / "oversight" / "integrations" / record_id
        entry = json.loads((path / "1.json").read_text(encoding="utf-8"))
        # Rewriting the only entry moves the record with it, so the tenant is
        # what gives it away: an entry filed here that names another.
        (path / "1.json").write_text(
            json.dumps({**entry, "tenant_id": "other-clinic"}), encoding="utf-8"
        )
        sweep = oversight.verify_register(store, tenant_id="sage-spine", principal=VIEWER)
        assert (sweep["verified"], sweep["broken"]) == (False, 1)
        (broken,) = [i for i in sweep["items"] if not i["verified"]]
        assert (broken["kind"], broken["id"]) == ("integrations", record_id)
        assert "another tenant" in broken["detail"]

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

    def _two_revisions(self, tmp_path: Path) -> tuple[Any, str, Path]:
        store = self.store(tmp_path)
        first = self.save(store, changes={"name": "PRIMO", "data_access": "PHI"})
        self.save(store, record_id=first["id"], changes={"risk": "High"}, at=LATER)
        path = tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / first["id"]
        return store, first["id"], path

    def test_an_entry_rewritten_in_place_passes_verify_and_fails_the_seal(
        self, tmp_path: Path
    ) -> None:
        store, record_id, path = self._two_revisions(tmp_path)
        self.save(store, record_id=record_id, changes={"notes": "x"}, at=LATER)
        seal = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        # Revision 2 is the approver's rating. Rewritten to say Low, it keeps
        # its revision, tenant and creation stamp, so the history checks out.
        entry = json.loads((path / "2.json").read_text(encoding="utf-8"))
        (path / "2.json").write_text(json.dumps({**entry, "risk": "Low"}), encoding="utf-8")
        assert store.verify_oversight("sage-spine", "partners", record_id)["verified"]
        now = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        (item,) = oversight.compare_seals(seal, now)["items"]
        assert (item["verified"], item["broken_at"]) == (False, 2)
        assert item["detail"] == "revision 2 changed since the seal"

    def test_a_deleted_latest_revision_passes_verify_and_fails_the_seal(
        self, tmp_path: Path
    ) -> None:
        # The known limit of `verify` on a volume: the record rolls back to a
        # whole, shorter history. Only an anchor kept elsewhere can see it.
        store, record_id, path = self._two_revisions(tmp_path)
        seal = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        (path / "2.json").unlink()
        assert store.get_oversight("sage-spine", "partners", record_id)["risk"] == "Unrated"
        assert store.verify_oversight("sage-spine", "partners", record_id)["verified"]
        now = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        result = oversight.compare_seals(seal, now)
        assert (result["verified"], result["broken"]) == (False, 1)
        assert result["items"][0]["detail"] == "revision 2 was removed since the seal"

    def test_a_record_removed_whole_fails_the_seal(self, tmp_path: Path) -> None:
        store, record_id, path = self._two_revisions(tmp_path)
        seal = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        for entry in path.iterdir():
            entry.unlink()
        path.rmdir()
        assert oversight.verify_register(store, tenant_id="sage-spine", principal=AUDITOR)[
            "verified"
        ]
        now = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        (item,) = oversight.compare_seals(seal, now)["items"]
        assert (item["id"], item["verified"], item["revisions"]) == (record_id, False, 0)
        assert "gone since the seal" in item["detail"]


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

    def test_a_record_row_deleted_from_under_its_history_is_found(self, tmp_path: Path) -> None:
        # The inventory is the record table; deleting a row would drop a
        # business associate from every list without a trace. The sweep
        # walks the history as well, so the row's absence is reported.
        store = self.store(tmp_path)
        oversight.load_seed(store, SEED, principal=OWNER, at=AT)
        record_id = oversight.seed_record_id(SEED["oversight"]["partners"][0]["name"])
        self._execute(store, f"DELETE FROM oversight_records WHERE record_id = '{record_id}'")
        assert record_id not in [r["id"] for r in store.list_oversight("sage-spine", "partners")]
        assert record_id in store.oversight_ids("sage-spine", "partners")
        sweep = oversight.verify_register(store, tenant_id="sage-spine", principal=AUDITOR)
        assert (sweep["verified"], sweep["broken"]) == (False, 1)
        (broken,) = [i for i in sweep["items"] if not i["verified"]]
        assert (broken["kind"], broken["id"]) == ("partners", record_id)
        assert "history exists for a record that does not" in broken["detail"]

    def test_a_refused_write_leaves_no_history_behind(self, tmp_path: Path) -> None:
        # All or nothing: the history row goes in first, and a record that
        # is not at the revision before rolls it back.
        store = self.store(tmp_path)
        orphan = {**create(), "revision": 2}
        with pytest.raises(StaleRevisionError):
            store.put_oversight("sage-spine", "partners", "drchrono", orphan)
        assert store.oversight_history("sage-spine", "partners", "drchrono") == []
        assert store.get_oversight("sage-spine", "partners", "drchrono") is None

    def test_a_history_row_rewritten_in_place_fails_the_seal(self, tmp_path: Path) -> None:
        # Without the production grant (SELECT/INSERT only on the history
        # table), an UPDATE to a past entry is invisible to `verify`.
        store = self.store(tmp_path)
        store.put_oversight("sage-spine", "partners", "drchrono", create())
        prior = store.get_oversight("sage-spine", "partners", "drchrono")
        store.put_oversight("sage-spine", "partners", "drchrono", edit(prior, OWNER, risk="High"))
        seal = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        self._execute(
            store,
            "UPDATE oversight_history SET record = JSON_SET(record, '$.notes', 'rewritten') "
            "WHERE record_id = 'drchrono' AND revision = 1",
        )
        assert store.verify_oversight("sage-spine", "partners", "drchrono")["verified"]
        now = oversight.seal_register(store, tenant_id="sage-spine", principal=AUDITOR)
        (item,) = oversight.compare_seals(seal, now)["items"]
        assert (item["verified"], item["broken_at"]) == (False, 1)


# ------------------------------------------------------------ command line


class TestTheCommandLine:
    """`ironclad oversight`, for what holds no browser session: the same policy.

    The actor is asserted, as with `ironclad exception`: whoever runs this
    holds the store credential. What the policy still decides is what that
    actor's roles allow.
    """

    SEED_PATH = str(ROOT / "tenants" / "sage-spine" / "seed.json")
    APPROVER = ("--actor", "owner-1", "--role", "owner")
    AUDIT = ("--actor", "auditor-1", "--role", "auditor")
    TENANT = ("--tenant", "sage-spine")

    @pytest.fixture()
    def run(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Any:
        from ironclad.cli import main  # noqa: PLC0415 -- imports fcntl, POSIX only

        volume = str(tmp_path / "volume")

        def run(*argv: str) -> tuple[int, Any, str]:
            code = main(["oversight", *argv, "--to", volume])
            out, err = capsys.readouterr()
            return code, (json.loads(out) if out.strip() else None), err

        return run

    def test_an_approver_loads_the_seed_once(self, run: Any) -> None:
        seeded = sum(len(SEED["oversight"][k]) for k in oversight.KINDS)
        code, loaded, _ = run("load-seed", "--seed", self.SEED_PATH, *self.APPROVER)
        assert (code, loaded["tenant_id"], len(loaded["created"])) == (0, "sage-spine", seeded)
        code, again, _ = run("load-seed", "--seed", self.SEED_PATH, *self.APPROVER)
        assert (code, again["created"], len(again["skipped"])) == (0, [], seeded)

    def test_a_contributor_may_not_load_the_seed(self, run: Any) -> None:
        contributor = ("--actor", "c-1", "--role", "contributor")
        code, out, err = run("load-seed", "--seed", self.SEED_PATH, *contributor)
        assert (code, out) == (2, None) and "rated seed" in err

    def test_the_queue_exits_4_only_when_asked_to_fail(self, run: Any) -> None:
        run("load-seed", "--seed", self.SEED_PATH, *self.APPROVER)
        dated = (*self.TENANT, "--as-of", "2026-09-26", *self.AUDIT)
        code, queue, _ = run("attention", *dated)
        assert (code, queue["as_of"]) == (0, "2026-09-26") and queue["high"] > 0
        assert run("attention", *dated, "--fail-on", "high")[0] == 4
        assert run("attention", *dated, "--fail-on", "any")[0] == 4

    def test_an_empty_queue_passes_the_strictest_gate(self, run: Any) -> None:
        code, queue, _ = run("attention", *self.TENANT, *self.AUDIT, "--fail-on", "any")
        assert (code, queue["records"]) == (0, 0)

    def test_export_writes_the_file_it_names_and_hashes(self, run: Any, tmp_path: Path) -> None:
        run("load-seed", "--seed", self.SEED_PATH, *self.APPROVER)
        out = tmp_path / "out"
        out.mkdir()
        dated = (*self.TENANT, "--as-of", "2026-09-26", *self.AUDIT)
        code, summary, _ = run("export", *dated, "--out", str(out))
        written = out / "oversight-register-sage-spine-2026-09-26.csv"
        assert (code, summary["path"], "csv" in summary) == (0, str(written), False)
        raw = written.read_bytes()
        assert summary["sha256"] == hashlib.sha256(raw).hexdigest()
        # CRLF rows as written, not doubled by a text-mode write on Windows.
        assert raw.count(b"\r\n") == 1 + sum(summary["records"].values())
        assert b"\r\r" not in raw

    def test_export_refuses_a_stranger_and_writes_nothing(self, run: Any, tmp_path: Path) -> None:
        run("load-seed", "--seed", self.SEED_PATH, *self.APPROVER)
        target = tmp_path / "register.csv"
        stranger = ("--actor", "x", "--role", "owner", "--tenant", "other-clinic")
        code, out, _ = run("export", *self.TENANT, "--actor", "x", "--out", str(target))
        assert (code, out, target.exists()) == (2, None, False)
        code, summary, _ = run("export", *stranger, "--out", str(target))
        assert (code, summary["records"]) == (0, {"partners": 0, "integrations": 0})

    def test_verify_exits_4_and_names_a_broken_history(self, run: Any, tmp_path: Path) -> None:
        run("load-seed", "--seed", self.SEED_PATH, *self.APPROVER)
        code, sweep, _ = run("verify", *self.TENANT, *self.AUDIT)
        assert (code, sweep["verified"], sweep["broken"]) == (0, True, 0)
        record_id = oversight.seed_record_id(SEED["oversight"]["partners"][0]["name"])
        record_dir = tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / record_id
        # A revision 2 planted beside the real one, with nothing else kept.
        (record_dir / "2.json").write_text(
            json.dumps({"revision": 2, "tenant_id": "sage-spine"}), encoding="utf-8"
        )
        code, sweep, _ = run("verify", *self.TENANT, *self.AUDIT)
        assert (code, sweep["broken"]) == (4, 1)
        assert [i["id"] for i in sweep["items"] if not i["verified"]] == [record_id]

    def test_an_actor_with_no_role_and_a_bad_date_are_bad_input(self, run: Any) -> None:
        code, out, err = run("attention", *self.TENANT, "--actor", "x")
        assert (code, out) == (2, None) and "may not read" in err
        code, out, _ = run("verify", *self.TENANT, "--actor", "x")
        assert (code, out) == (2, None)
        code, out, _ = run("attention", *self.TENANT, *self.AUDIT, "--as-of", "2026-02-30")
        assert (code, out) == (2, None)

    def test_verify_against_a_seal_exits_4_on_a_rewrite_it_alone_would_pass(
        self, run: Any, tmp_path: Path
    ) -> None:
        run("load-seed", "--seed", self.SEED_PATH, *self.APPROVER)
        code, seal, _ = run("seal", *self.TENANT, *self.AUDIT)
        assert (code, seal["sealed_by"]) == (0, "auditor-1")
        sealed = tmp_path / "seal.json"
        sealed.write_text(json.dumps(seal), encoding="utf-8")
        code, sweep, _ = run("verify", *self.TENANT, *self.AUDIT, "--seal", str(sealed))
        assert (code, sweep["verified"], sweep["seal"]["verified"]) == (0, True, True)
        record_id = oversight.seed_record_id(SEED["oversight"]["partners"][0]["name"])
        entry = tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / record_id / "1.json"
        rewritten = {**json.loads(entry.read_text(encoding="utf-8")), "baa_status": "Executed"}
        entry.write_text(json.dumps(rewritten), encoding="utf-8")
        assert run("verify", *self.TENANT, *self.AUDIT)[0] == 0
        code, sweep, _ = run("verify", *self.TENANT, *self.AUDIT, "--seal", str(sealed))
        assert (code, sweep["verified"], sweep["seal"]["broken"]) == (4, True, 1)

    def test_verify_with_an_unreadable_or_foreign_seal_is_bad_input(
        self, run: Any, tmp_path: Path
    ) -> None:
        missing = str(tmp_path / "missing.json")
        code, out, err = run("verify", *self.TENANT, *self.AUDIT, "--seal", missing)
        assert (code, out) == (2, None) and "not a readable seal" in err
        run("load-seed", "--seed", self.SEED_PATH, *self.APPROVER)
        foreign = tmp_path / "foreign.json"
        other = ("--tenant", "other-clinic", "--actor", "o-1", "--role", "auditor")
        foreign.write_text(json.dumps(run("seal", *other)[1]), encoding="utf-8")
        code, out, err = run("verify", *self.TENANT, *self.AUDIT, "--seal", str(foreign))
        assert (code, out) == (2, None) and "different tenants" in err

    def test_two_seals_compare_without_a_store(
        self, run: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ironclad.cli import main  # noqa: PLC0415

        run("load-seed", "--seed", self.SEED_PATH, *self.APPROVER)
        earlier, later, forged = (tmp_path / f"{n}.json" for n in ("earlier", "later", "forged"))
        seal = run("seal", *self.TENANT, *self.AUDIT)[1]
        earlier.write_text(json.dumps(seal), encoding="utf-8")
        later.write_text(json.dumps(seal), encoding="utf-8")
        compare = ["oversight", "compare-seals", "--earlier", str(earlier), "--later"]
        assert main([*compare, str(later)]) == 0
        assert json.loads(capsys.readouterr().out)["verified"] is True
        record_id = oversight.seed_record_id(SEED["oversight"]["partners"][0]["name"])
        record_dir = tmp_path / "volume" / "sage-spine" / "oversight" / "partners" / record_id
        for entry in record_dir.iterdir():
            entry.unlink()
        record_dir.rmdir()
        later.write_text(json.dumps(run("seal", *self.TENANT, *self.AUDIT)[1]), encoding="utf-8")
        assert main([*compare, str(later)]) == 4
        result = json.loads(capsys.readouterr().out)
        assert [i["id"] for i in result["items"] if not i["verified"]] == [record_id]
        forged.write_text(json.dumps({**seal, "records": []}), encoding="utf-8")
        assert main([*compare, str(forged)]) == 2
        assert "its own digest" in capsys.readouterr().err

    def test_no_store_is_bad_input(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ironclad.cli import main  # noqa: PLC0415

        monkeypatch.delenv("IRONCLAD_STORE", raising=False)
        argv = ["oversight", "verify", *self.TENANT, *self.AUDIT]
        assert main(argv) == 2
        assert "no store target" in capsys.readouterr().err
