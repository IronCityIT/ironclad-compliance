"""A partner's service token held to the register record it acts for.

`tokens issue --on-behalf-of partners/<id>` links a grant to a register record;
`oversight access` finds live access the register says should not be there:
a partner the register does not hold, has retired, or lets handle PHI without
an executed BAA. The link is part of the grant on the ledger, so re-pointing
or dropping it by hand is caught by `tokens review --ledger`.
"""

from __future__ import annotations

import http.client
import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ironclad import oversight
from ironclad.api import grant_ledger
from ironclad.api.tokens import (
    TokenFileError,
    issue_token,
    review_tokens,
    revoke_tokens,
    write_token_file,
)
from ironclad.errors import AuthorizationError, IroncladError
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
        # Ends before the assurance does, so it does not outlast it either.
        grant(document, "ops@governed.example", f"partners/{record_id}",
              expires_at=date(2026, 10, 5))  # fmt: skip
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

    def test_a_token_outlasting_the_assurance_is_a_notice(self, store: Any) -> None:
        record_id = add(store, "integrations", {**GOVERNED, "cert_expiration_date": "2026-11-30"})
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ops@governed.example", f"integrations/{record_id}")
        result = access(store, document)
        (item,) = result["items"]
        assert codes(item) == ["outlasts-assurance"]
        assert "assurance expiring 2026-11-30" in item["findings"][0]["message"]
        assert (item["level"], result["high"], result["notices"]) == ("notice", 0, 1)

    def test_a_token_ending_on_the_assurance_date_does_not_outlast_it(self, store: Any) -> None:
        record_id = add(store, "partners", {**GOVERNED, "cert_expiration_date": "2026-12-31"})
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ops@governed.example", f"partners/{record_id}")
        (item,) = access(store, document)["items"]
        assert item["findings"] == []

    def test_a_token_outlasting_both_dates_names_both(self, store: Any) -> None:
        record_id = add(
            store,
            "partners",
            {**GOVERNED, "review_due": "2026-11-30", "cert_expiration_date": "2026-10-31"},
        )
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ops@governed.example", f"partners/{record_id}")
        (item,) = access(store, document)["items"]
        assert codes(item) == ["outlasts-review", "outlasts-assurance"]

    def test_a_linked_token_with_no_expiry_is_high(self, store: Any) -> None:
        record_id = add(store, "partners", GOVERNED)
        document: dict[str, Any] = {"tokens": []}
        grant(document, "ops@governed.example", f"partners/{record_id}")
        grant(document, "staff@sage.example")
        for entry in document["tokens"]:
            del entry["expires_at"]  # tokens issue never writes one without it
        result = access(store, document)
        (item,) = result["items"]
        assert (codes(item), item["level"], item["expires_at"]) == (["no-expiry"], "high", None)
        assert result["high"] == 1
        # A staff token without one is the token review's notice, not this one's.
        assert [h["user_id"] for h in result["unlinked"]] == ["staff@sage.example"]

    def test_no_expiry_is_reported_alongside_the_register_findings(self, store: Any) -> None:
        document: dict[str, Any] = {"tokens": []}
        grant(document, "dana@drchrono.example", "partners/drchrono")
        grant(document, "ghost@nowhere.example", "integrations/not-in-register")
        for entry in document["tokens"]:
            del entry["expires_at"]
        found = {item["user_id"]: codes(item) for item in access(store, document)["items"]}
        assert "no-expiry" in found["dana@drchrono.example"]
        assert "phi-without-baa" in found["dana@drchrono.example"]
        assert sorted(found["ghost@nowhere.example"]) == ["no-expiry", "record-missing"]

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
    def cli(
        self,
        store: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> Any:
        from ironclad.cli import main  # noqa: PLC0415 -- imports fcntl, POSIX only

        # The register a linked issue is checked against, as an operator sets it.
        monkeypatch.setenv("IRONCLAD_STORE", str(tmp_path / "volume"))

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


# ------------------------------------------------- the grant ends with the record

#: Fixed, so a grant ending 2026-12-31 does not lapse under the test later.
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
DANA = "dana@drchrono.example"
STAFF = "staff@sage.example"


class TestRetiringEndsAccess:
    """`ironclad serve` honours a partner's token only while its record is live.

    `oversight access` reports a token for a retired or missing record at the
    next review; the server refuses it on the next request, as 403 with the
    holder named, so the tenant's refusals show who still presented it.
    """

    @pytest.fixture
    def secrets_(self, tmp_path: Path) -> dict[str, str]:
        document: dict[str, Any] = {"tokens": []}
        issued: dict[str, str] = {}
        for user, link in ((DANA, "partners/drchrono"), (STAFF, "")):
            token, _ = issue_token(
                document, user_id=user, tenant_id="sage-spine", roles=["contributor"],
                expires_at=date(2026, 12, 31), issued_by="bill", as_of=AS_OF, on_behalf_of=link,
            )  # fmt: skip
            issued[user] = token
        write_token_file(tmp_path / "tokens.json", document)
        return issued

    @staticmethod
    def auth(tmp_path: Path, register: Any) -> Any:
        from ironclad.api.http import TokenFileAuthenticator  # noqa: PLC0415

        return TokenFileAuthenticator(tmp_path / "tokens.json", lambda: NOW, register=register)

    @staticmethod
    def set_status(store: Any, status: str) -> None:
        oversight.save(
            store, tenant_id="sage-spine", kind="partners", record_id="drchrono",
            changes={"status": status}, principal=OWNER, at=AT,
        )  # fmt: skip

    def test_retiring_the_record_refuses_its_token_by_name(
        self, store: Any, tmp_path: Path, secrets_: dict[str, str]
    ) -> None:
        from ironclad.api.http import AccessWithdrawnError  # noqa: PLC0415

        auth = self.auth(tmp_path, store)
        assert auth.principal_for(secrets_[DANA]).user_id == DANA
        self.set_status(store, "Retired")
        with pytest.raises(AccessWithdrawnError, match="partners/drchrono is retired") as refused:
            auth.principal_for(secrets_[DANA])
        principal = refused.value.principal
        assert (principal.user_id, principal.tenant_id) == (DANA, "sage-spine")
        assert auth.principal_for(secrets_[STAFF]).user_id == STAFF  # staff hold no link

    def test_offboarding_and_a_missing_baa_are_findings_not_refusals(
        self, store: Any, tmp_path: Path, secrets_: dict[str, str]
    ) -> None:
        # The seeded DrChrono handles PHI without an executed BAA: high in the
        # review, and still the reviewers' call rather than the server's.
        self.set_status(store, "Offboarding")
        assert self.auth(tmp_path, store).principal_for(secrets_[DANA]).user_id == DANA

    def test_a_record_the_tenant_does_not_hold_refuses_the_token(
        self, store: Any, tmp_path: Path
    ) -> None:
        from ironclad.api.http import AccessWithdrawnError  # noqa: PLC0415

        elsewhere = oversight.save(
            store, tenant_id="other-clinic", kind="partners", changes={"name": "Elsewhere"},
            principal=STRANGER, at=AT,
        )["id"]  # fmt: skip
        document: dict[str, Any] = {"tokens": []}
        tokens: dict[str, str] = {}
        for link in ("partners/gone", f"partners/{elsewhere}", "integrations/drchrono"):
            tokens[link], _ = issue_token(
                document, user_id=f"{len(tokens)}@p.example", tenant_id="sage-spine",
                roles=["viewer"], expires_at=date(2026, 12, 31), issued_by="bill", as_of=AS_OF,
                on_behalf_of=link,
            )  # fmt: skip
        write_token_file(tmp_path / "tokens.json", document)
        auth = self.auth(tmp_path, store)
        for link, token in tokens.items():
            with pytest.raises(AccessWithdrawnError, match=f"does not hold {link}$"):
                auth.principal_for(token)

    def test_a_link_that_cannot_be_checked_is_not_honoured(
        self, store: Any, tmp_path: Path, secrets_: dict[str, str]
    ) -> None:
        from ironclad.api.http import AccessWithdrawnError  # noqa: PLC0415

        with pytest.raises(IroncladError, match="no register") as unchecked:
            self.auth(tmp_path, None).principal_for(secrets_[DANA])
        assert not isinstance(unchecked.value, AccessWithdrawnError)  # the operator's fault
        assert self.auth(tmp_path, None).principal_for(secrets_[STAFF]) is not None
        path = tmp_path / "tokens.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["tokens"][0]["on_behalf_of"] = "drchrono"  # edited by hand
        write_token_file(path, document)
        assert self.auth(tmp_path, store).principal_for(secrets_[DANA]) is None

    def test_over_http_the_refusal_is_a_403_the_tenant_sees(
        self, store: Any, tmp_path: Path, secrets_: dict[str, str]
    ) -> None:
        from ironclad.api import access_log  # noqa: PLC0415
        from ironclad.api.http import App, serve  # noqa: PLC0415

        log = access_log.AccessLog(tmp_path / "access.log")
        app = App(
            results=store, policy_root=tmp_path, authenticator=self.auth(tmp_path, store),
            quiet=True, access_log=log,
        )  # fmt: skip
        httpd = serve(app, port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        path = "/api/v1/tenants/sage-spine/oversight/partners"

        def get(token: str) -> tuple[int, dict[str, Any]]:
            conn = http.client.HTTPConnection("127.0.0.1", int(httpd.server_address[1]), timeout=5)
            conn.request("GET", path, headers={"Authorization": f"Bearer {token}"})
            response = conn.getresponse()
            answer = (response.status, json.loads(response.read()))
            conn.close()
            return answer

        try:
            assert get(secrets_[DANA])[0] == 200
            self.set_status(store, "Retired")
            status, body = get(secrets_[DANA])
            assert status == 403
            assert body["errors"] == ["partners/drchrono is retired in the register"]
            assert get(secrets_[STAFF])[0] == 200
        finally:
            httpd.shutdown()
            httpd.server_close()
            log.close()
        lines = log.path.read_text(encoding="utf-8").splitlines()
        seen = [(e["user"], e["status"]) for e in map(json.loads, lines)]
        assert seen == [(DANA, 200), (DANA, 403), (STAFF, 200)]
        report = access_log.refusals(
            [json.loads(line) for line in lines], "sage-spine", datetime.now(timezone.utc).date()
        )
        (caller,) = report["callers"]
        assert (caller["caller"], caller["user"], caller["statuses"]) == ("member", DANA, [403])

    def test_serve_holds_tokens_to_its_own_store(
        self, tmp_path: Path, secrets_: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ironclad.cli import main  # noqa: PLC0415

        started: list[Any] = []

        def no_serving(app: Any, **_: Any) -> None:
            started.append(app)
            raise KeyboardInterrupt  # stop before serving forever

        monkeypatch.setattr("ironclad.api.http.serve", no_serving)
        (tmp_path / "policies").mkdir()
        results = tmp_path / "results"
        args = ["serve", "--to", str(results), "--policy-root", str(tmp_path / "policies"),
                "--tokens", str(tmp_path / "tokens.json"), "--port", "0"]  # fmt: skip
        try:
            main(args)
        except KeyboardInterrupt:
            pass
        (app,) = started
        assert app.authenticator.register is app.results


class TestIssueHeldToTheRegister:
    """`tokens issue --on-behalf-of` applies the rule `serve` applies.

    A grant `serve` would refuse on its first request is refused when it is
    made, so the ledger holds no grant nobody could use. Nothing is written:
    neither the token file nor the ledger.
    """

    ISSUE = ("--tenant", "sage-spine", "--role", "contributor", "--expires", "2026-12-31",
             "--actor", "bill", "--as-of", "2026-09-27")  # fmt: skip

    @pytest.fixture
    def cli(
        self,
        store: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> Any:
        from ironclad.cli import main  # noqa: PLC0415 -- imports fcntl, POSIX only

        monkeypatch.delenv("IRONCLAD_STORE", raising=False)
        tokens = tmp_path / "tokens.json"

        def run(link: str, *extra: str) -> tuple[int, Any, str]:
            code = main(["tokens", "issue", str(tokens), "--user", DANA,
                         "--on-behalf-of", link, *self.ISSUE, *extra])  # fmt: skip
            out, err = capsys.readouterr()
            return code, (json.loads(out) if out.strip() else None), err

        return run

    @staticmethod
    def nothing_written(tmp_path: Path) -> bool:
        tokens = tmp_path / "tokens.json"
        return not tokens.exists() and not grant_ledger.default_path(tokens).exists()

    def test_a_live_record_is_granted(self, cli: Any, tmp_path: Path) -> None:
        code, out, _ = cli("partners/drchrono", "--register", str(tmp_path / "volume"))
        assert code == 0 and out["entry"]["on_behalf_of"] == "partners/drchrono"

    def test_the_register_defaults_to_the_store_variable(
        self, cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("IRONCLAD_STORE", str(tmp_path / "volume"))
        assert cli("partners/drchrono")[0] == 0

    def test_offboarding_is_still_granted(self, cli: Any, store: Any, tmp_path: Path) -> None:
        TestRetiringEndsAccess.set_status(store, "Offboarding")
        assert cli("partners/drchrono", "--register", str(tmp_path / "volume"))[0] == 0

    def test_a_retired_record_is_refused(self, cli: Any, store: Any, tmp_path: Path) -> None:
        TestRetiringEndsAccess.set_status(store, "Retired")
        code, out, err = cli("partners/drchrono", "--register", str(tmp_path / "volume"))
        assert (code, out) == (2, None)
        assert "partners/drchrono is retired in the register" in err
        assert "nothing was written" in err and self.nothing_written(tmp_path)

    def test_a_record_the_tenant_does_not_hold_is_refused(
        self, cli: Any, store: Any, tmp_path: Path
    ) -> None:
        elsewhere = oversight.save(
            store, tenant_id="other-clinic", kind="partners", changes={"name": "Elsewhere"},
            principal=STRANGER, at=AT,
        )["id"]  # fmt: skip
        for link in ("partners/gone", f"partners/{elsewhere}", "integrations/drchrono"):
            code, _, err = cli(link, "--register", str(tmp_path / "volume"))
            assert code == 2 and f"the register does not hold {link}" in err
        assert self.nothing_written(tmp_path)

    def test_no_register_is_refused_rather_than_trusted(self, cli: Any, tmp_path: Path) -> None:
        code, _, err = cli("partners/drchrono")
        assert code == 2 and "--register" in err and "IRONCLAD_STORE" in err
        assert self.nothing_written(tmp_path)

    def test_a_store_without_a_register_is_refused(
        self, cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Rows:  # a store that keeps assessments and nothing else
            pass

        monkeypatch.setattr("ironclad.cli.store_from_target", lambda target: Rows())
        code, _, err = cli("partners/drchrono", "--register", "mysql://db.example/ironclad")
        assert code == 2 and "does not hold the register" in err
        assert self.nothing_written(tmp_path)

    def test_a_register_that_cannot_answer_is_refused(
        self, cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ironclad.store import StoreError  # noqa: PLC0415

        class Down:
            def get_oversight(self, *_: Any) -> Any:
                raise StoreError("connection refused")

        monkeypatch.setattr("ironclad.cli.store_from_target", lambda target: Down())
        code, _, err = cli("partners/drchrono", "--register", "mysql://db.example/ironclad")
        assert code == 2 and "could not be read (connection refused)" in err
        assert self.nothing_written(tmp_path)

    def test_a_malformed_link_is_named_without_a_register(self, cli: Any, tmp_path: Path) -> None:
        code, _, err = cli("drchrono")
        assert code == 2 and "on_behalf_of 'drchrono'" in err and "--register" not in err
        assert self.nothing_written(tmp_path)


class TestOffboardingRevokesByRecord:
    """`tokens revoke --tenant T --on-behalf-of partners/<id>` ends a partner's access.

    Every entry in the tenant acting for the record goes, whoever holds it and
    whether or not it has expired, in one ledgered act; nothing else does. The
    register is not consulted: cutting access off never waits on it.
    """

    @pytest.fixture
    def document(self) -> dict[str, Any]:
        document: dict[str, Any] = {"tokens": []}
        grant(document, DANA, "partners/drchrono")
        lapsed = grant(document, "ops@drchrono.example", "partners/drchrono")
        lapsed["expires_at"] = "2026-09-01"  # expired, and still in the file
        grant(document, "p@primo.example", "partners/primo")
        grant(document, STAFF)
        grant(document, DANA, "partners/drchrono", tenant_id="other-clinic")
        return document

    def test_every_holder_in_the_tenant_goes_and_nothing_else(
        self, document: dict[str, Any]
    ) -> None:
        removed = revoke_tokens(
            document, tenant_id="sage-spine", on_behalf_of=" partners/drchrono "
        )
        assert [e["user_id"] for e in removed] == [DANA, "ops@drchrono.example"]
        kept = [(e["user_id"], e["tenant_id"]) for e in document["tokens"]]
        assert kept == [
            ("p@primo.example", "sage-spine"),
            (STAFF, "sage-spine"),
            (DANA, "other-clinic"),
        ]

    @pytest.mark.parametrize(
        ("selector", "message"),
        [
            ({"on_behalf_of": "partners/drchrono"}, "names the tenant too"),
            (
                {"on_behalf_of": "partners/drchrono", "tenant_id": "sage-spine", "user_id": DANA},
                "name one of",
            ),
            (
                {
                    "on_behalf_of": "partners/drchrono",
                    "tenant_id": "sage-spine",
                    "expired_as_of": AS_OF,
                },
                "name one of",
            ),
            ({"on_behalf_of": "drchrono", "tenant_id": "sage-spine"}, "on_behalf_of 'drchrono'"),
            ({"on_behalf_of": "integrations/drchrono", "tenant_id": "sage-spine"}, "no entry"),
            ({"on_behalf_of": "partners/primo", "tenant_id": "other-clinic"}, "no entry"),
        ],
    )
    def test_refusals_remove_nothing(
        self, document: dict[str, Any], selector: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(TokenFileError, match=message):
            revoke_tokens(document, **selector)
        assert len(document["tokens"]) == 5

    def test_the_command_ledgers_each_removal_and_the_review_stays_clean(
        self, store: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:  # fmt: skip
        from ironclad.cli import main  # noqa: PLC0415 -- imports fcntl, POSIX only

        monkeypatch.setenv("IRONCLAD_STORE", str(tmp_path / "volume"))
        tokens = tmp_path / "tokens.json"
        ledger = grant_ledger.default_path(tokens)
        for user, link in ((DANA, "partners/drchrono"), ("ops@drchrono.example",
                           "partners/drchrono"), (STAFF, "")):  # fmt: skip
            extra = ["--on-behalf-of", link] if link else []
            assert main(["tokens", "issue", str(tokens), "--user", user,
                         *TestIssueHeldToTheRegister.ISSUE, *extra]) == 0  # fmt: skip
        capsys.readouterr()
        # Offboarded and retired: the register would now refuse a new grant,
        # and the revocation does not ask it.
        TestRetiringEndsAccess.set_status(store, "Retired")
        monkeypatch.delenv("IRONCLAD_STORE")
        code = main(["tokens", "revoke", str(tokens), "--tenant", "sage-spine",
                     "--on-behalf-of", "partners/drchrono", "--actor", "bill",
                     "--as-of", "2026-09-27"])  # fmt: skip
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert [e["user_id"] for e in out["removed"]] == [DANA, "ops@drchrono.example"]
        assert all("sha256" not in e for e in out["removed"])
        lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        assert [(e["action"], e["on_behalf_of"]) for e in lines[3:]] == [
            ("revoke", "partners/drchrono"),
            ("revoke", "partners/drchrono"),
        ]
        assert out["ledger_anchor"].startswith("5:")
        remaining = json.loads(tokens.read_text(encoding="utf-8"))
        assert [e["user_id"] for e in remaining["tokens"]] == [STAFF]
        review = review_tokens(remaining, AS_OF)
        assert review["high"] == 0

    def test_the_command_refuses_a_record_nobody_holds_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ironclad.cli import main  # noqa: PLC0415 -- imports fcntl, POSIX only

        tokens = tmp_path / "tokens.json"
        document: dict[str, Any] = {"tokens": []}
        grant(document, STAFF)
        write_token_file(tokens, document)
        before = tokens.read_bytes()
        code = main(["tokens", "revoke", str(tokens), "--tenant", "sage-spine",
                     "--on-behalf-of", "partners/drchrono", "--actor", "bill"])  # fmt: skip
        err = capsys.readouterr().err
        assert code == 2 and "no entry matches" in err and "nothing was written" in err
        assert tokens.read_bytes() == before
        assert not grant_ledger.default_path(tokens).exists()
