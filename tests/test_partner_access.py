"""A partner's service token held to the register record it acts for.

`tokens issue --on-behalf-of partners/<id>` links a grant to a register record;
`oversight access` finds live access the register says should not be there:
a partner the register does not hold, has retired, or lets handle PHI without
an executed BAA. The link is part of the grant on the ledger, so re-pointing
or dropping it by hand is caught by `tokens review --ledger`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ironclad import oversight
from ironclad.api import grant_ledger
from ironclad.api.tokens import TokenFileError, issue_token, review_tokens
from ironclad.errors import AuthorizationError
from ironclad.model.tenant import Principal, Role
from ironclad.oversight import OversightError
from ironclad.store import FileResultStore

ROOT = Path(__file__).resolve().parent.parent
SEED = json.loads((ROOT / "tenants" / "sage-spine" / "seed.json").read_text(encoding="utf-8"))
TODAY = "2026-09-27"
AS_OF = date(2026, 9, 27)
AT = "2026-09-26T12:00:00Z"

OWNER = Principal(user_id="owner-1", tenant_id="sage-spine", roles=frozenset({Role.OWNER}))
AUDITOR = Principal(user_id="aud-1", tenant_id="sage-spine", roles=frozenset({Role.AUDITOR}))
STRANGER = Principal(user_id="x", tenant_id="other-clinic", roles=frozenset({Role.OWNER}))

#: A relationship with nothing wrong with it: an executed, evidenced BAA and a
#: review a year out.
GOVERNED = {
    "name": "Governed Imaging",
    "status": "Active",
    "risk": "Medium",
    "data_access": "PHI",
    "agreement_status": "Executed",
    "baa_status": "Executed",
    "baa_execution_date": "2026-01-15",
    "baa_document_ref": "contracts/baa-governed-imaging.pdf",
    "review_due": "2027-06-30",
}


def grant(document: dict[str, Any], user: str, link: str = "", **kw: Any) -> dict[str, Any]:
    kw.setdefault("expires_at", date(2026, 12, 31))
    kw.setdefault("tenant_id", "sage-spine")
    _, entry = issue_token(
        document, user_id=user, roles=["contributor"], issued_by="bill",
        as_of=AS_OF, on_behalf_of=link, **kw,
    )  # fmt: skip
    return entry


def add(store: Any, kind: str, changes: dict[str, Any]) -> str:
    saved = oversight.save(
        store, tenant_id="sage-spine", kind=kind, changes=changes, principal=OWNER, at=AT
    )
    return str(saved["id"])


@pytest.fixture
def store(tmp_path: Path) -> FileResultStore:
    volume = FileResultStore(tmp_path / "volume")
    oversight.load_seed(volume, SEED, principal=OWNER, at=AT)
    return volume


def access(store: Any, document: dict[str, Any], **kw: Any) -> dict[str, Any]:
    kw.setdefault("principal", AUDITOR)
    kw.setdefault("today", TODAY)
    return oversight.partner_access(store, document, tenant_id="sage-spine", **kw)


def codes(item: dict[str, Any]) -> list[str]:
    return [f["code"] for f in item["findings"]]


class TestTheLink:
    def test_issue_records_the_link_and_the_review_shows_it(self) -> None:
        document: dict[str, Any] = {"tokens": []}
        entry = grant(document, "dana@drchrono.example", "partners/drchrono")
        assert entry["on_behalf_of"] == "partners/drchrono"
        (item,) = review_tokens(document, AS_OF)["items"]
        assert item["on_behalf_of"] == "partners/drchrono" and item["findings"] == []

    def test_no_link_writes_no_key(self) -> None:
        document: dict[str, Any] = {"tokens": []}
        assert "on_behalf_of" not in grant(document, "staff@sage.example")

    @pytest.mark.parametrize(
        "link",
        ["drchrono", "vendors/drchrono", "partners/", "partners/../x", "partners/a b",
         "partners/drchrono/1", "Partners/drchrono"],
    )  # fmt: skip
    def test_issue_refuses_a_link_that_names_no_record(self, link: str) -> None:
        document: dict[str, Any] = {"tokens": []}
        with pytest.raises(TokenFileError, match="on_behalf_of"):
            grant(document, "dana@drchrono.example", link)
        assert document == {"tokens": []}

    def test_a_hand_written_bad_link_is_high_in_the_review(self) -> None:
        document: dict[str, Any] = {"tokens": []}
        grant(document, "dana@drchrono.example", "partners/drchrono")
        document["tokens"][0]["on_behalf_of"] = "drchrono"
        (item,) = review_tokens(document, AS_OF)["items"]
        assert any("on_behalf_of" in f["message"] for f in item["findings"] if f["level"] == "high")


class TestPartnerAccess:
    def test_a_seeded_partner_without_a_baa_holding_a_token_is_high(self, store: Any) -> None:
        document: dict[str, Any] = {"tokens": []}
        grant(document, "dana@drchrono.example", "partners/drchrono")
        result = access(store, document)
        (item,) = result["items"]
        assert (result["holders"], result["high"]) == (1, 1)
        assert (item["name"], item["level"]) == ("DrChrono", "high")
        assert codes(item)[0] == "phi-without-baa"
        assert "digest_prefix" in item and "sha256" not in item

    def test_a_governed_partner_is_clean(self, store: Any) -> None:
        record_id = add(store, "partners", GOVERNED)
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ops@governed.example", f"partners/{record_id}")
        (item,) = access(store, document)["items"]
        assert (item["level"], item["findings"]) == ("ok", [])

    def test_a_record_the_register_does_not_hold_is_high(self, store: Any) -> None:
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ghost@nowhere.example", "integrations/not-in-register")
        (item,) = access(store, document)["items"]
        assert (codes(item), item["name"]) == (["record-missing"], None)

    def test_a_retired_relationship_is_high_whatever_else_it_says(self, store: Any) -> None:
        record_id = add(store, "partners", {**GOVERNED, "status": "Retired"})
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ops@governed.example", f"partners/{record_id}")
        (item,) = access(store, document)["items"]
        assert codes(item) == ["record-retired"]

    def test_a_lapsed_review_or_assurance_is_high(self, store: Any) -> None:
        overdue = add(store, "partners", {**GOVERNED, "name": "A", "review_due": "2026-09-26"})
        lapsed = add(
            store, "integrations", {**GOVERNED, "name": "B", "cert_expiration_date": "2026-09-01"}
        )
        document: dict[str, Any] = {"tokens": []}
        grant(document, "a@a.example", f"partners/{overdue}")
        grant(document, "b@b.example", f"integrations/{lapsed}")
        found = {item["user_id"]: codes(item) for item in access(store, document)["items"]}
        assert found == {"a@a.example": ["review-overdue"], "b@b.example": ["assurance-expired"]}

    def test_queue_notices_that_are_not_about_access_are_left_out(self, store: Any) -> None:
        record_id = add(
            store, "partners", {**GOVERNED, "risk": "Unrated", "cert_expiration_date": "2026-10-10"}
        )
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ops@governed.example", f"partners/{record_id}")
        (item,) = access(store, document)["items"]
        assert item["findings"] == []

    def test_offboarding_and_a_token_outlasting_the_review_are_notices(self, store: Any) -> None:
        record_id = add(
            store, "partners", {**GOVERNED, "status": "Offboarding", "review_due": "2026-11-30"}
        )
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ops@governed.example", f"partners/{record_id}")
        result = access(store, document)
        (item,) = result["items"]
        assert sorted(codes(item)) == ["outlasts-review", "record-offboarding"]
        assert (item["level"], result["high"], result["notices"]) == ("notice", 0, 1)

    def test_a_token_ending_on_the_review_date_does_not_outlast_it(self, store: Any) -> None:
        record_id = add(store, "partners", {**GOVERNED, "review_due": "2026-12-31"})
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ops@governed.example", f"partners/{record_id}")
        (item,) = access(store, document)["items"]
        assert item["findings"] == []

    def test_only_live_entries_of_this_tenant_are_held_to_the_register(self, store: Any) -> None:
        document: dict[str, Any] = {"tokens": []}
        grant(document, "lapsed@drchrono.example", "partners/drchrono",
              expires_at=date(2026, 9, 30))  # fmt: skip
        grant(document, "elsewhere@drchrono.example", "partners/drchrono",
              tenant_id="other-clinic")  # fmt: skip
        grant(document, "staff@sage.example")
        grant(document, "broken@drchrono.example", "partners/drchrono")
        document["tokens"][-1]["expires_at"] = "2026-13-01"
        # Live through its last day, gone the day after.
        assert access(store, document, today="2026-09-30")["holders"] == 1
        result = access(store, document, today="2026-10-01")
        assert result["holders"] == 0
        assert [h["user_id"] for h in result["unlinked"]] == ["staff@sage.example"]

    def test_high_holders_come_first(self, store: Any) -> None:
        record_id = add(store, "partners", GOVERNED)
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ok@governed.example", f"partners/{record_id}")
        grant(document, "dana@drchrono.example", "partners/drchrono")
        levels = [item["level"] for item in access(store, document)["items"]]
        assert levels == ["high", "ok"]

    def test_readers_only_and_the_tenants_own(self, store: Any) -> None:
        with pytest.raises(AuthorizationError):
            access(store, {"tokens": []}, principal=STRANGER)
        with pytest.raises(OversightError, match="not a token file"):
            access(store, {"entries": []})
        with pytest.raises(OversightError):
            access(store, {"tokens": []}, today="2026-02-30")


class TestTheLinkOnTheLedger:
    @pytest.fixture
    def cli(self, capsys: pytest.CaptureFixture[str]) -> Any:
        from ironclad.cli import main  # noqa: PLC0415 -- imports fcntl, POSIX only

        def run(*argv: str) -> tuple[int, Any, str]:
            code = main(list(argv))
            out, err = capsys.readouterr()
            return code, (json.loads(out) if out.strip() else None), err

        return run

    ISSUE = ("--tenant", "sage-spine", "--role", "contributor", "--expires", "2026-12-31",
             "--actor", "bill", "--as-of", "2026-09-27")  # fmt: skip

    def review(self, cli: Any, tokens: Path) -> dict[str, Any]:
        _, out, _ = cli(
            "tokens", "review", str(tokens), "--ledger", str(grant_ledger.default_path(tokens)),
            "--as-of", "2026-09-27",
        )  # fmt: skip
        return out  # type: ignore[no-any-return]

    def test_the_ledger_carries_the_link(self, tmp_path: Path, cli: Any) -> None:
        tokens = tmp_path / "tokens.json"
        cli("tokens", "issue", str(tokens), "--user", "d@x.example",
            "--on-behalf-of", "partners/drchrono", *self.ISSUE)  # fmt: skip
        cli("tokens", "issue", str(tokens), "--user", "s@x.example", *self.ISSUE)
        lines = grant_ledger.default_path(tokens).read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["on_behalf_of"] for line in lines] == ["partners/drchrono", ""]
        review = self.review(cli, tokens)
        assert review["high"] == 0
        assert [i.get("on_behalf_of") for i in review["items"]] == ["partners/drchrono", None]

    @pytest.mark.parametrize("edit", ["partners/primo", None])
    def test_a_link_edited_by_hand_is_high(
        self, tmp_path: Path, cli: Any, edit: str | None
    ) -> None:
        tokens = tmp_path / "tokens.json"
        cli("tokens", "issue", str(tokens), "--user", "d@x.example",
            "--on-behalf-of", "partners/drchrono", *self.ISSUE)  # fmt: skip
        document = json.loads(tokens.read_text(encoding="utf-8"))
        if edit is None:
            del document["tokens"][0]["on_behalf_of"]  # hidden from `oversight access`
        else:
            document["tokens"][0]["on_behalf_of"] = edit
        tokens.write_text(json.dumps(document), encoding="utf-8")
        (item,) = self.review(cli, tokens)["items"]
        assert any("on_behalf_of" in f["message"] for f in item["findings"] if f["level"] == "high")

    def test_issue_refuses_a_bad_link_and_writes_nothing(self, tmp_path: Path, cli: Any) -> None:
        tokens = tmp_path / "tokens.json"
        code, out, err = cli("tokens", "issue", str(tokens), "--user", "d@x.example",
                             "--on-behalf-of", "drchrono", *self.ISSUE)  # fmt: skip
        assert (code, out) == (2, None) and "on_behalf_of" in err
        assert not tokens.exists() and not grant_ledger.default_path(tokens).exists()


class TestTheCommand:
    AUDIT = ("--tenant", "sage-spine", "--actor", "aud-1", "--role", "auditor",
             "--as-of", TODAY)  # fmt: skip

    @pytest.fixture
    def run(self, store: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Any:
        from ironclad.cli import main  # noqa: PLC0415 -- imports fcntl, POSIX only

        volume = str(tmp_path / "volume")

        def run(*argv: str) -> tuple[int, Any, str]:
            code = main(["oversight", "access", *argv, "--to", volume])
            out, err = capsys.readouterr()
            return code, (json.loads(out) if out.strip() else None), err

        return run

    def tokens(self, tmp_path: Path, *grants: tuple[str, str]) -> str:
        document: dict[str, Any] = {"tokens": []}
        for user, link in grants:
            grant(document, user, link)
        path = tmp_path / "tokens.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return str(path)

    def test_a_partner_without_a_baa_trips_the_gate(self, run: Any, tmp_path: Path) -> None:
        path = self.tokens(tmp_path, ("dana@drchrono.example", "partners/drchrono"))
        code, result, _ = run(*self.AUDIT, "--tokens", path)
        assert (code, result["high"]) == (0, 1)
        assert run(*self.AUDIT, "--tokens", path, "--fail-on", "high")[0] == 4

    def test_staff_only_passes_the_strictest_gate(self, run: Any, tmp_path: Path) -> None:
        path = self.tokens(tmp_path, ("staff@sage.example", ""))
        code, result, _ = run(*self.AUDIT, "--tokens", path, "--fail-on", "any")
        assert (code, result["holders"], len(result["unlinked"])) == (0, 0, 1)

    def test_no_role_or_an_unreadable_file_is_bad_input(self, run: Any, tmp_path: Path) -> None:
        path = self.tokens(tmp_path, ("dana@drchrono.example", "partners/drchrono"))
        code, out, _ = run(*self.AUDIT[:2], "--actor", "x", "--tokens", path)
        assert (code, out) == (2, None)  # no role: nobody
        missing = str(tmp_path / "absent.json")
        code, out, err = run(*self.AUDIT, "--tokens", missing)
        assert (code, out) == (2, None) and "token file unreadable" in err
