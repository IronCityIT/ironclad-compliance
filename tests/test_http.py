"""The HTTP surface: a real server on a real socket, refusal by refusal.

Every test speaks HTTP to a `ThreadingHTTPServer` bound to a loopback port the
OS chose, because the things worth proving about a transport — status codes,
headers, the body limit, path handling — are exactly the things a direct call
to `App.handle` would not exercise.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import secrets
import threading
from pathlib import Path
from typing import Any

import pytest

from ironclad.api.http import (
    MAX_BODY_BYTES,
    App,
    TokenFileAuthenticator,
    hash_token,
    serve,
)
from ironclad.engine import run_assessment
from ironclad.store.files import FileResultStore
from tests.conftest import NOW

TOKENS = {
    "acme-manager": ("acme", "alice@acme.example", ["compliance_manager"]),
    "acme-second-manager": ("acme", "bob@acme.example", ["compliance_manager"]),
    "acme-viewer": ("acme", "vic@acme.example", ["viewer"]),
    "acme-contributor": ("acme", "carol@acme.example", ["contributor"]),
    "beta-manager": ("beta", "mallory@beta.example", ["compliance_manager"]),
    "no-tenant": ("", "nobody", ["owner"]),
    "unslugged-tenant": ("Acme Corp", "nobody", ["owner"]),
}


@pytest.fixture
def secrets_for() -> dict[str, str]:
    """A fresh random token per named credential, never the name itself."""
    return {name: secrets.token_urlsafe(24) for name in TOKENS}


@pytest.fixture
def token_file(tmp_path: Path, secrets_for: dict[str, str]) -> Path:
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "sha256": hash_token(secrets_for[name]),
                        "user_id": user,
                        "tenant_id": tenant,
                        "roles": roles,
                    }
                    for name, (tenant, user, roles) in TOKENS.items()
                ]
            }
        )
    )
    return path


@pytest.fixture
def results(tmp_path: Path, tiny_framework, evidence) -> FileResultStore:
    store = FileResultStore(tmp_path / "results")
    for tenant, assessment_id in (("acme", "acme-run-1"), ("beta", "beta-run-1")):
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="deep",
            as_of=NOW,
            assessment_id="acme-run-1",
        )
        document = json.loads(json.dumps(result.to_dict()))
        document["tenant_id"] = tenant
        document["assessment_id"] = assessment_id
        store.put_assessment(document)
    return store


@pytest.fixture
def static_root(tmp_path: Path) -> Path:
    root = tmp_path / "public"
    root.mkdir()
    (root / "index.html").write_text("<!doctype html><title>dash</title>")
    (root / "app.js").write_text("export const x = 1;")
    (tmp_path / "outside.txt").write_text("not served")
    return root


class Client:
    """The smallest HTTP client that returns what a test wants to assert on."""

    def __init__(self, port: int, token: str = "") -> None:
        self.port = port
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], http.client.HTTPMessage]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        sent: dict[str, str] = {}
        if self.token:
            sent["Authorization"] = f"Bearer {self.token}"
        payload = raw if raw is not None else (json.dumps(body).encode() if body else None)
        if payload is not None:
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        conn.request(method, path, body=payload, headers=sent)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        try:
            parsed = json.loads(data) if data else {}
        except json.JSONDecodeError:
            parsed = {"_raw": data}
        return response.status, parsed, response.headers

    def get(self, path: str, **kw: Any) -> tuple[int, dict[str, Any], http.client.HTTPMessage]:
        return self.request("GET", path, **kw)

    def post(
        self, path: str, body: Any = None, **kw: Any
    ) -> tuple[int, dict[str, Any], http.client.HTTPMessage]:
        return self.request("POST", path, body=body, **kw)


@pytest.fixture
def server(tmp_path: Path, results: FileResultStore, token_file: Path, static_root: Path):
    """A served app, torn down after the test."""
    policy_root = tmp_path / "policies"
    policy_root.mkdir()
    app = App(
        results=results,
        policy_root=policy_root,
        authenticator=TokenFileAuthenticator(token_file),
        static_root=static_root,
        quiet=True,
    )
    httpd = serve(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, app, policy_root
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def port(server) -> int:
    return int(server[0].server_address[1])


@pytest.fixture
def as_(port: int, secrets_for: dict[str, str]):
    def client(name: str = "") -> Client:
        return Client(port, secrets_for[name] if name else "")

    return client


# ------------------------------------------------------------ authentication


class TestAuthentication:
    def test_no_authenticator_means_nothing_is_served(self, tmp_path: Path, results) -> None:
        # The fail-closed rule. Not 401 — there is nothing a caller could
        # present — and not a working read for anyone.
        app = App(results=results, policy_root=tmp_path, authenticator=None, quiet=True)
        httpd = serve(app, port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            status, body, _ = Client(int(httpd.server_address[1]), "anything").get(
                "/api/v1/tenants/acme/assessments"
            )
        finally:
            httpd.shutdown()
            httpd.server_close()
        assert status == 503
        assert "no authenticator" in body["errors"][0]

    def test_no_token_is_401(self, as_) -> None:
        status, body, _ = as_().get("/api/v1/tenants/acme/assessments")
        assert status == 401
        assert "bearer token" in body["errors"][0]

    def test_a_wrong_scheme_is_401(self, as_, secrets_for) -> None:
        status, _, _ = as_().get(
            "/api/v1/me", headers={"Authorization": f"Basic {secrets_for['acme-manager']}"}
        )
        assert status == 401

    def test_an_unknown_token_is_401(self, port: int) -> None:
        status, body, _ = Client(port, "not-a-real-token").get("/api/v1/me")
        assert status == 401
        assert "not recognised" in body["errors"][0]

    def test_a_token_that_matches_only_in_prefix_is_401(self, port, secrets_for) -> None:
        status, _, _ = Client(port, secrets_for["acme-manager"][:-1]).get("/api/v1/me")
        assert status == 401

    def test_a_token_bound_to_no_tenant_authenticates_nobody(self, as_) -> None:
        assert as_("no-tenant").get("/api/v1/me")[0] == 401

    def test_a_token_bound_to_an_unslugged_tenant_authenticates_nobody(self, as_) -> None:
        # "Acme Corp" is not a tenant id; "acme-corp" is. A token file that
        # says otherwise is a misconfiguration, and it grants nothing.
        assert as_("unslugged-tenant").get("/api/v1/me")[0] == 401

    def test_me_reports_the_principal_and_permissions(self, as_) -> None:
        status, body, _ = as_("acme-viewer").get("/api/v1/me")
        assert status == 200
        assert body["data"]["principal"]["tenant_id"] == "acme"
        assert body["data"]["principal"]["roles"] == ["viewer"]
        assert "assessment:read" in body["data"]["permissions"]
        assert "exception:approve" not in body["data"]["permissions"]

    def test_the_token_file_is_the_record(self, as_, token_file: Path) -> None:
        # Revoke by editing the file: the next request is refused, no restart.
        assert as_("acme-manager").get("/api/v1/me")[0] == 200
        token_file.write_text(json.dumps({"tokens": []}))
        assert as_("acme-manager").get("/api/v1/me")[0] == 401

    def test_a_malformed_token_file_serves_nobody(self, as_, token_file: Path) -> None:
        token_file.write_text('{"tokens": "yes"}')
        status, body, _ = as_("acme-manager").get("/api/v1/me")
        assert status == 503
        assert "authenticator cannot answer" in body["errors"][0]

    def test_a_missing_token_file_serves_nobody(self, as_, token_file: Path) -> None:
        token_file.unlink()
        assert as_("acme-manager").get("/api/v1/me")[0] == 503

    def test_the_file_stores_digests_not_tokens(self, token_file: Path, secrets_for) -> None:
        text = token_file.read_text()
        for token in secrets_for.values():
            assert token not in text
        assert hashlib.sha256(secrets_for["acme-manager"].encode()).hexdigest() in text


# --------------------------------------------------------------- tenancy


class TestTenantIsolation:
    def test_a_stranger_cannot_read_another_tenants_assessments(self, as_) -> None:
        status, body, _ = as_("beta-manager").get("/api/v1/tenants/acme/assessments")
        assert status == 403
        assert "another tenant" in body["errors"][0]

    def test_a_stranger_cannot_read_a_named_assessment(self, as_) -> None:
        # The id is real. The refusal must not say so.
        status, body, _ = as_("beta-manager").get("/api/v1/tenants/acme/assessments/acme-run-1")
        assert status == 403
        assert "acme-run-1" not in body["errors"][0]

    def test_a_stranger_cannot_raise_an_acceptance_in_another_tenant(self, as_, server) -> None:
        _, _, policy_root = server
        status, _, _ = as_("beta-manager").post(
            "/api/v1/tenants/acme/exceptions",
            {"control_id": "CC1.1", "justification": "because", "requested_by": "mallory"},
        )
        assert status == 403
        assert not (policy_root / "acme").exists(), "a refused write created the tenant's file"

    def test_the_body_cannot_redirect_a_write_to_another_tenant(self, as_, server) -> None:
        # The path is what is authorized. A body naming a different tenant is
        # dropped, not honoured — so acme's manager writes into acme's file.
        _, _, policy_root = server
        status, body, _ = as_("acme-manager").post(
            "/api/v1/tenants/acme/exceptions",
            {
                "tenant_id": "beta",
                "client_id": "beta",
                "control_id": "CC1.1",
                "justification": "scheduled",
                "requested_by": "alice",
            },
        )
        assert status == 200
        assert body["data"]["exception"]["tenant_id"] == "acme"
        assert (policy_root / "acme" / "policy.json").exists()
        assert not (policy_root / "beta").exists()

    @pytest.mark.parametrize(
        "tenant",
        ["Acme", "acme%2F..%2Fbeta", "acme..", "a--b", "ACME-CORP"],
    )
    def test_a_path_segment_that_is_not_its_own_slug_is_refused(self, as_, tenant: str) -> None:
        # None of these is a tenant id. Each would normalise into one, and a
        # request that reaches the policy volume under a normalised name is a
        # request that reached a different tenant's directory.
        status, body, _ = as_("acme-manager").get(f"/api/v1/tenants/{tenant}/assessments")
        assert status in (400, 403, 404), (tenant, body)
        assert body["ok"] is False


# ------------------------------------------------------------- reads


class TestReads:
    def test_list_assessments(self, as_) -> None:
        status, body, headers = as_("acme-viewer").get("/api/v1/tenants/acme/assessments")
        assert status == 200
        ids = [a["assessment_id"] for a in body["data"]["assessments"]]
        assert ids == ["acme-run-1"]
        assert headers["Content-Type"].startswith("application/json")
        assert headers["Cache-Control"] == "no-store"

    def test_get_assessment(self, as_) -> None:
        status, body, _ = as_("acme-viewer").get("/api/v1/tenants/acme/assessments/acme-run-1")
        assert status == 200
        assert body["data"]["assessment"]["assessment_id"] == "acme-run-1"

    def test_an_unknown_assessment_is_404(self, as_) -> None:
        status, body, _ = as_("acme-viewer").get("/api/v1/tenants/acme/assessments/nope")
        assert status == 404
        assert "no assessment" in body["errors"][0]

    def test_remediation_comes_from_the_latest_assessment(self, as_) -> None:
        status, body, _ = as_("acme-viewer").get("/api/v1/tenants/acme/remediation")
        assert status == 200
        assert body["data"]["items"], "the sample evidence leaves gaps, so there is a queue"
        assert all("control_id" in item for item in body["data"]["items"])

    def test_a_viewer_cannot_read_the_exception_register(self, as_) -> None:
        status, body, _ = as_("acme-viewer").get("/api/v1/tenants/acme/exceptions")
        assert status == 403
        assert "lacks 'exception:read'" in body["errors"][0]

    def test_a_viewer_cannot_read_the_audit_trail(self, as_) -> None:
        assert as_("acme-viewer").get("/api/v1/tenants/acme/audit")[0] == 403

    def test_the_catalog_is_the_registrys(self, as_) -> None:
        from ironclad import registry

        status, body, _ = as_("acme-viewer").get("/api/v1/catalog")
        assert status == 200
        expected = registry.catalog(registry.discover())
        assert [m["name"] for m in body["data"]["modules"]] == [m["name"] for m in expected]
        assert body["data"]["groups"]
        assert {f["alias"] for f in body["data"]["frameworks"]} >= {"soc2", "hipaa"}

    @pytest.mark.parametrize("limit", ["0", "-1", "ten"])
    def test_a_bad_limit_is_400(self, as_, limit: str) -> None:
        status, _, _ = as_("acme-viewer").get(f"/api/v1/tenants/acme/assessments?limit={limit}")
        assert status == 400

    def test_an_unknown_status_filter_is_400(self, as_) -> None:
        status, body, _ = as_("acme-manager").get("/api/v1/tenants/acme/exceptions?status=sideways")
        assert status == 400
        assert "unknown exception status" in body["errors"][0]


# ----------------------------------------------------- acceptance workflow


class TestAcceptanceWorkflow:
    def _raise(self, as_, who: str = "acme-contributor") -> str:
        status, body, _ = as_(who).post(
            "/api/v1/tenants/acme/exceptions",
            {
                "control_id": "CC1.1",
                "justification": "Remediation is scheduled for the next release train.",
                "requested_by": "carol",
                "compensating_controls": ["Daily privileged activity review"],
                "expires_in_days": 30,
            },
        )
        assert status == 200, body
        return str(body["data"]["exception"]["exception_id"])

    def test_request_approve_revoke_lands_in_the_policy_file(self, as_, server) -> None:
        _, _, policy_root = server
        exception_id = self._raise(as_)

        policy = json.loads((policy_root / "acme" / "policy.json").read_text())
        assert policy["tenant_id"] == "acme"
        assert policy["exceptions"][0]["status"] == "pending_approval"
        assert policy["exceptions"][0]["requested_by"] == "carol@acme.example"

        status, body, _ = as_("acme-manager").post(
            f"/api/v1/tenants/acme/exceptions/{exception_id}/approve"
        )
        assert status == 200, body
        assert body["data"]["exception"]["status"] == "approved"
        policy = json.loads((policy_root / "acme" / "policy.json").read_text())
        assert policy["exceptions"][0]["status"] == "approved"
        assert policy["exceptions"][0]["approved_by"] == "alice@acme.example"

        status, body, _ = as_("acme-manager").post(
            f"/api/v1/tenants/acme/exceptions/{exception_id}/revoke",
            {"reason": "the compensating control was removed"},
        )
        assert status == 200, body
        assert body["data"]["exception"]["status"] == "revoked"

        status, body, _ = as_("acme-manager").get("/api/v1/tenants/acme/audit")
        assert status == 200
        actions = [e["action"] for e in body["data"]["events"]]
        assert actions == ["exception.requested", "exception.approved", "exception.revoked"]
        # Chained: each event carries the previous one's hash.
        events = body["data"]["events"]
        assert events[1]["prev_hash"] == events[0]["hash"]
        assert events[2]["prev_hash"] == events[1]["hash"]

    def test_a_viewer_cannot_raise_one(self, as_) -> None:
        status, _, _ = as_("acme-viewer").post(
            "/api/v1/tenants/acme/exceptions",
            {"control_id": "CC1.1", "justification": "please", "requested_by": "vic"},
        )
        assert status == 403

    def test_a_contributor_cannot_approve(self, as_) -> None:
        exception_id = self._raise(as_)
        status, body, _ = as_("acme-contributor").post(
            f"/api/v1/tenants/acme/exceptions/{exception_id}/approve"
        )
        assert status == 403
        assert "lacks 'exception:approve'" in body["errors"][0]

    def test_the_requester_cannot_approve_their_own(self, as_) -> None:
        # Separation of duties holds over HTTP because it lives in the model.
        exception_id = self._raise(as_, who="acme-manager")
        status, body, _ = as_("acme-manager").post(
            f"/api/v1/tenants/acme/exceptions/{exception_id}/approve"
        )
        assert status == 400
        assert "second person" in body["errors"][0]
        status, body, _ = as_("acme-second-manager").post(
            f"/api/v1/tenants/acme/exceptions/{exception_id}/approve"
        )
        assert status == 200

    def test_the_body_cannot_name_a_different_requester(self, as_) -> None:
        # Found by the first run of the test above: the service takes
        # `requested_by` from the request for the CLI's sake, so a manager who
        # wrote a colleague's name into the body could approve their own
        # acceptance. Over HTTP the requester is whoever holds the token.
        status, body, _ = as_("acme-manager").post(
            "/api/v1/tenants/acme/exceptions",
            {"control_id": "CC1.1", "justification": "scheduled", "requested_by": "carol"},
        )
        assert status == 200
        assert body["data"]["exception"]["requested_by"] == "alice@acme.example"
        exception_id = body["data"]["exception"]["exception_id"]
        status, body, _ = as_("acme-manager").post(
            f"/api/v1/tenants/acme/exceptions/{exception_id}/approve"
        )
        assert status == 400
        assert "second person" in body["errors"][0]

    def test_approving_an_unknown_acceptance_is_404(self, as_) -> None:
        status, _, _ = as_("acme-manager").post("/api/v1/tenants/acme/exceptions/nope/approve")
        assert status == 404

    def test_an_acceptance_without_a_reason_is_400(self, as_) -> None:
        status, body, _ = as_("acme-contributor").post(
            "/api/v1/tenants/acme/exceptions", {"control_id": "CC1.1", "requested_by": "carol"}
        )
        assert status == 400
        assert any("just a gap" in e for e in body["errors"])

    def test_a_revocation_without_a_reason_is_400(self, as_) -> None:
        exception_id = self._raise(as_)
        status, body, _ = as_("acme-manager").post(
            f"/api/v1/tenants/acme/exceptions/{exception_id}/revoke", {}
        )
        assert status == 400
        assert "needs a reason" in body["errors"][0]

    def test_a_non_numeric_expiry_is_400_not_500(self, as_) -> None:
        status, body, _ = as_("acme-contributor").post(
            "/api/v1/tenants/acme/exceptions",
            {
                "control_id": "CC1.1",
                "justification": "scheduled",
                "requested_by": "carol",
                "expires_in_days": "soon",
            },
        )
        assert status == 400
        assert "malformed request" in body["errors"][0]

    def test_a_revoked_acceptance_can_be_raised_again(self, as_, server) -> None:
        # Request, approve, revoke, request again used to be a 500: the policy
        # file's one-per-control rule counted history, so no control could
        # ever carry a second acceptance — including the renewal the engine's
        # own "lapsed" finding tells the client to raise.
        _, _, policy_root = server
        first = self._raise(as_)
        as_("acme-manager").post(f"/api/v1/tenants/acme/exceptions/{first}/approve")
        status, _, _ = as_("acme-manager").post(
            f"/api/v1/tenants/acme/exceptions/{first}/revoke", {"reason": "withdrawn"}
        )
        assert status == 200

        second = self._raise(as_)
        assert second != first
        policy = json.loads((policy_root / "acme" / "policy.json").read_text())
        assert [e["status"] for e in policy["exceptions"]] == ["revoked", "pending_approval"]

    def test_twenty_people_at_once_all_land_and_the_chain_holds(self, as_, server) -> None:
        # Twenty concurrent requests for twenty controls: fourteen were
        # answered 200 and eight were on file, because each request read the
        # policy, appended its entry and wrote the whole file back over the
        # others'; six more read a half-written file and got a 500. An
        # acknowledged acceptance that is not on file is the worst thing this
        # store can do. The store now holds a lock across each write path and
        # replaces the file atomically.
        import threading

        _, _, policy_root = server
        controls = [f"CC{i}.{j}" for i in range(1, 10) for j in range(1, 4)][:20]
        outcomes: dict[str, int | str] = {}

        def raise_one(control_id: str) -> None:
            # A client-side exception (a timeout on a slow disk) would otherwise
            # die with the thread, leave no outcome, and surface later as a
            # puzzling mismatch in the policy file. Recorded, so it fails here
            # and says what happened. It failed once, unreproduced, on
            # 2026-09-23 (PRODUCTIZE_NOTES §16.41).
            try:
                status, body, _ = as_("acme-contributor").post(
                    "/api/v1/tenants/acme/exceptions",
                    {"control_id": control_id, "justification": "at once", "expires_in_days": 30},
                )
                outcomes[control_id] = status if status == 200 else f"{status} {body}"
            except Exception as exc:  # noqa: BLE001 — reported by the assertion below
                outcomes[control_id] = f"{type(exc).__name__}: {exc}"

        threads = [threading.Thread(target=raise_one, args=(c,)) for c in controls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(outcomes) == len(controls) and set(outcomes.values()) == {200}, outcomes
        policy = json.loads((policy_root / "acme" / "policy.json").read_text())
        assert sorted(e["control_id"] for e in policy["exceptions"]) == sorted(controls)
        status, body, _ = as_("acme-manager").get("/api/v1/tenants/acme/audit?limit=100")
        events = body["data"]["events"]
        assert len(events) == 20
        assert all(events[i]["prev_hash"] == events[i - 1]["hash"] for i in range(1, 20))
        # nothing half-written left behind
        assert not [p for p in (policy_root / "acme").iterdir() if p.suffix == ".tmp"]

    def test_a_lapsed_approval_on_file_does_not_block_its_renewal(self, as_, server) -> None:
        # The engine sweeps lapsed approvals before an assessment; nothing
        # swept the policy store. An acceptance past its expiry sat there as
        # "approved" and, under the open-acceptance rule, would have blocked
        # the renewal it was supposed to invite.
        _, _, policy_root = server
        (policy_root / "acme").mkdir()
        (policy_root / "acme" / "policy.json").write_text(
            json.dumps(
                {
                    "policy_version": "1.0",
                    "tenant_id": "acme",
                    "scope_exclusions": [],
                    "owners": {},
                    "exceptions": [
                        {
                            "exception_id": "ex-old",
                            "control_id": "CC1.1",
                            "justification": "last quarter's argument",
                            "requested_by": "carol@acme.example",
                            "approved_by": "alice@acme.example",
                            "requested_at": "2026-01-10T00:00:00+00:00",
                            "approved_at": "2026-01-15T00:00:00+00:00",
                            "expires_at": "2026-04-15T00:00:00+00:00",
                            "status": "approved",
                        }
                    ],
                }
            )
        )

        renewed = self._raise(as_)

        policy = json.loads((policy_root / "acme" / "policy.json").read_text())
        by_id = {e["exception_id"]: e["status"] for e in policy["exceptions"]}
        assert by_id == {"ex-old": "expired", renewed: "pending_approval"}
        status, body, _ = as_("acme-manager").get("/api/v1/tenants/acme/audit")
        assert status == 200
        actions = [e["action"] for e in body["data"]["events"]]
        assert actions == ["exception.expired", "exception.requested"]

    def test_a_second_open_acceptance_is_refused_by_name_not_by_500(self, as_) -> None:
        first = self._raise(as_)
        status, body, _ = as_("acme-contributor").post(
            "/api/v1/tenants/acme/exceptions",
            {"control_id": "CC1.1", "justification": "again", "expires_in_days": 30},
        )
        assert status == 400, body
        assert first in body["errors"][0]
        assert "pending_approval" in body["errors"][0]

    @pytest.mark.parametrize(
        "days",
        [99999999999, 30.5, True, 366, -1, 0],
        ids=["overflow", "fractional", "bool", "over-max", "negative", "zero"],
    )
    def test_an_unusable_expiry_is_400_not_500(self, as_, days) -> None:
        status, body, _ = as_("acme-contributor").post(
            "/api/v1/tenants/acme/exceptions",
            {"control_id": "CC1.1", "justification": "scheduled", "expires_in_days": days},
        )
        assert status == 400, (days, body)
        assert "internal" not in body["errors"][0]

    @pytest.mark.parametrize("days", ["30", 30.0, 365], ids=["digits", "whole-float", "max"])
    def test_a_whole_number_of_days_is_accepted_however_spelled(self, as_, days) -> None:
        status, body, _ = as_("acme-contributor").post(
            "/api/v1/tenants/acme/exceptions",
            {"control_id": "CC1.1", "justification": "scheduled", "expires_in_days": days},
        )
        assert status == 200, (days, body)

    def test_a_control_id_that_is_not_an_identifier_is_400(self, as_, server) -> None:
        _, _, policy_root = server
        status, body, _ = as_("acme-contributor").post(
            "/api/v1/tenants/acme/exceptions",
            {"control_id": "../x", "justification": "scheduled", "expires_in_days": 30},
        )
        assert status == 400, body
        assert "is not a control identifier" in body["errors"][0]
        assert not (policy_root / "acme").exists()

    def test_a_control_id_that_is_not_a_string_is_400(self, as_, server) -> None:
        # str() on the body recorded an acceptance on the control "{'a': 1}".
        _, _, policy_root = server
        status, body, _ = as_("acme-contributor").post(
            "/api/v1/tenants/acme/exceptions",
            {"control_id": {"a": 1}, "justification": "scheduled", "expires_in_days": 30},
        )
        assert status == 400, body
        assert "control_id must be a string" in body["errors"][0]
        assert not (policy_root / "acme").exists()


# ---------------------------------------------------------------- transport


class TestTransport:
    def test_health_needs_no_token(self, as_) -> None:
        status, body, _ = as_().get("/api/v1/health")
        assert status == 200
        assert body["ok"] is True and body["writable"] is True
        assert body["store"] == "file"
        assert "root" not in body, "the health endpoint must not disclose the volume path"

    def test_head_on_health(self, port: int) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("HEAD", "/api/v1/health")
        response = conn.getresponse()
        assert response.status == 200
        assert response.read() == b""

    def test_an_unknown_route_is_404(self, as_) -> None:
        assert as_("acme-manager").get("/api/v1/tenants/acme/nothing")[0] == 404

    def test_an_unknown_route_still_needs_a_token(self, as_) -> None:
        # Authentication before routing, so route existence is not probeable.
        assert as_().get("/api/v1/tenants/acme/nothing")[0] == 401

    def test_the_wrong_method_is_405(self, as_) -> None:
        assert as_("acme-manager").post("/api/v1/tenants/acme/assessments", {})[0] == 405

    def test_an_oversize_body_is_413_and_ends_the_connection(self, port, secrets_for) -> None:
        # The body is refused without being read. The first version of this
        # server then kept the connection open and parsed the unread bytes as
        # the next request line, which surfaced as a broken pipe in the
        # server's thread. The answer now closes the connection, and the same
        # connection cannot be used for a second request.
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/api/v1/tenants/acme/exceptions",
            body=b"x" * (MAX_BODY_BYTES + 1),
            headers={"Authorization": f"Bearer {secrets_for['acme-manager']}"},
        )
        response = conn.getresponse()
        assert response.status == 413
        assert response.headers["Connection"] == "close"
        response.read()
        # http.client reconnects on its own after a close, so "the same
        # socket cannot be reused" is not observable from here; what is, is
        # that the server did not choke on the leftover and still answers.
        assert Client(port).get("/api/v1/health")[0] == 200

    def test_a_connection_that_stops_mid_request_is_closed(self, server, port, secrets_for) -> None:
        # Forty half-sent POSTs held forty threads and forty sockets for as long
        # as the clients stayed connected; nothing on the server side ever gave
        # up on them. Measured with /proc/<pid>/status before the read timeout
        # existed. Here the timeout is shortened so the test does not wait 30 s.
        # Without the timeout each recv below blocks until the client's own
        # 5 s limit and the assertion raises instead of reading EOF.
        import socket
        import threading
        import time

        httpd = server[0]
        handler = httpd.RequestHandlerClass
        original = handler.timeout
        handler.timeout = 1.0
        try:
            before = threading.active_count()
            half_sent = []
            for _ in range(5):
                sock = socket.create_connection(("127.0.0.1", port))
                sock.sendall(
                    b"POST /api/v1/tenants/acme/exceptions HTTP/1.1\r\nHost: x\r\n"
                    + f"Authorization: Bearer {secrets_for['acme-manager']}\r\n".encode()
                    + b"Content-Length: 500\r\n\r\n{"
                )
                half_sent.append(sock)
            silent = [socket.create_connection(("127.0.0.1", port)) for _ in range(5)]

            for sock in half_sent + silent:
                sock.settimeout(5)
                assert sock.recv(64) == b"", "the server did not close a stalled connection"
                sock.close()
            deadline = time.monotonic() + 5
            while threading.active_count() > before and time.monotonic() < deadline:
                time.sleep(0.05)
            assert threading.active_count() == before, "a handler thread outlived its connection"
            # and it is still a server
            assert Client(port).get("/api/v1/health")[0] == 200
        finally:
            handler.timeout = original

    @staticmethod
    def _exchange(port: int, raw: bytes) -> bytes:
        """Send raw bytes on one connection and read until the server closes it."""
        import socket

        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        sock.sendall(raw)
        received = b""
        try:
            while chunk := sock.recv(65536):
                received += chunk
        except TimeoutError:
            pass
        finally:
            sock.close()
        return received

    # The body of each request below is itself a complete, authenticated
    # request. A server that does not read the body leaves those bytes on the
    # connection and runs them as the next request: two answers to one
    # request, the second to a request no proxy in front of it ever saw.
    # Measured on 2026-09-23: a chunked POST answered 400 and then 200 for
    # the /me smuggled inside it.

    @pytest.mark.parametrize(
        "framing",
        [
            b"Transfer-Encoding: chunked\r\n",
            b"Transfer-Encoding: chunked\r\nContent-Length: 0\r\n",
            b"Transfer-Encoding: gzip, chunked\r\n",
        ],
        ids=["chunked", "chunked-and-length", "coded"],
    )
    def test_a_transfer_coded_body_is_refused_and_never_run(
        self, port: int, secrets_for, framing: bytes
    ) -> None:
        auth = f"Authorization: Bearer {secrets_for['acme-manager']}\r\n".encode()
        smuggled = b"GET /api/v1/me HTTP/1.1\r\nHost: x\r\n" + auth + b"\r\n"
        received = self._exchange(
            port,
            b"POST /api/v1/tenants/acme/exceptions HTTP/1.1\r\nHost: x\r\n"
            + auth
            + framing
            + b"\r\n"
            + smuggled,
        )
        assert received.count(b"HTTP/1.1 ") == 1, received
        assert received.startswith(b"HTTP/1.1 501 ")
        assert b"Connection: close" in received
        assert b"Content-Length" in received  # the refusal says what to send instead

    # Content-Length is 1*DIGIT (RFC 9110 §8.6), and a length the server reads
    # one way and a proxy another is the same smuggling as a chunked body.
    # Measured on 2026-09-23: `0_7` and `+7` were read as 7 by int(), and of
    # two differing lengths the first silently won; each ran the /me below.
    @pytest.mark.parametrize(
        "length",
        [
            b"Content-Length: 0_7\r\n",
            b"Content-Length: +7\r\n",
            "Content-Length: ７\r\n".encode(),
            b"Content-Length: 7\r\nContent-Length: 0\r\n",
            b"Content-Length: 0\r\nContent-Length: 7\r\n",
            b"Content-Length: 7, 7\r\n",
        ],
        ids=["underscore", "plus", "fullwidth", "dup-first", "dup-last", "list"],
    )
    def test_a_length_that_is_not_plain_digits_is_refused_and_ends_the_connection(
        self, port: int, secrets_for, length: bytes
    ) -> None:
        auth = f"Authorization: Bearer {secrets_for['acme-manager']}\r\n".encode()
        smuggled = b"GET /api/v1/me HTTP/1.1\r\nHost: x\r\n" + auth + b"\r\n"
        received = self._exchange(
            port,
            b"POST /api/v1/tenants/acme/exceptions HTTP/1.1\r\nHost: x\r\n"
            + auth
            + length
            + b"\r\n"
            + b'{"a":1}'
            + smuggled,
        )
        assert received.count(b"HTTP/1.1 ") == 1, received
        assert received.startswith(b"HTTP/1.1 400 ")
        assert b"Connection: close" in received

    def test_a_padded_length_is_still_a_length(self, as_) -> None:
        # Whitespace around a field value is not part of it (RFC 9110 §5.5).
        status, body, _ = as_("acme-manager").post(
            "/api/v1/tenants/acme/exceptions",
            raw=b"{}",
            headers={"Content-Length": " 2 "},
        )
        assert status == 400
        assert "control_id is required" in body["errors"][0]

    @pytest.mark.parametrize("zero_first", [False, True], ids=["length", "zero-then-length"])
    def test_a_head_with_a_body_does_not_run_the_body(
        self, port: int, secrets_for, zero_first: bool
    ) -> None:
        auth = f"Authorization: Bearer {secrets_for['acme-manager']}\r\n".encode()
        smuggled = b"GET /api/v1/me HTTP/1.1\r\nHost: x\r\n" + auth + b"\r\n"
        received = self._exchange(
            port,
            b"HEAD /api/v1/health HTTP/1.1\r\nHost: x\r\n"
            + (b"Content-Length: 0\r\n" if zero_first else b"")
            + f"Content-Length: {len(smuggled)}\r\n\r\n".encode()
            + smuggled,
        )
        assert received.count(b"HTTP/1.1 ") == 1, received
        assert received.startswith(b"HTTP/1.1 200 ")

    def test_a_burst_of_connections_is_not_made_to_wait_for_a_retry(self, server, port) -> None:
        # socketserver's listen backlog is 5. Twenty connects at once overflowed
        # it; the kernel dropped the SYNs and each client waited for its own
        # retransmit, 1 s and then 3 s later. Measured on 2026-09-23: 12 of 20
        # requests took over a second, and at 100 at once some ran past a 10 s
        # timeout. It is also what made the twenty-at-once test fail
        # intermittently (PRODUCTIZE_NOTES §16.44). A request that took a
        # second here waited for a retransmit: loopback answers in milliseconds.
        import time

        assert server[0].request_queue_size >= 128
        latencies: list[float] = []
        go = threading.Event()

        def one() -> None:
            go.wait()
            started = time.perf_counter()
            assert Client(port).get("/api/v1/health")[0] == 200
            latencies.append(time.perf_counter() - started)

        threads = [threading.Thread(target=one) for _ in range(40)]
        for thread in threads:
            thread.start()
        go.set()
        for thread in threads:
            thread.join()
        assert len(latencies) == 40
        # A backlog of 5 makes about 25 of 40 wait. A little room for a busy CI box.
        assert sum(1 for s in latencies if s >= 1.0) <= 2, sorted(latencies)[-5:]

    def test_a_non_json_body_is_400(self, as_) -> None:
        status, body, _ = as_("acme-manager").post(
            "/api/v1/tenants/acme/exceptions", raw=b"control_id=CC1.1"
        )
        assert status == 400
        assert "not valid JSON" in body["errors"][0]

    def test_a_json_array_body_is_400(self, as_) -> None:
        status, _, _ = as_("acme-manager").post("/api/v1/tenants/acme/exceptions", raw=b"[1]")
        assert status == 400

    def test_the_server_header_names_no_python_version(self, as_) -> None:
        _, _, headers = as_().get("/api/v1/health")
        assert "Python" not in headers["Server"]
        assert headers["X-Content-Type-Options"] == "nosniff"

    def test_the_query_string_is_not_logged(self, server, capsys) -> None:
        # quiet=True in the fixture; a request must produce no log line at all.
        httpd, app, _ = server
        Client(int(httpd.server_address[1])).get("/api/v1/health?token=should-not-appear")
        assert "should-not-appear" not in capsys.readouterr().err


# ------------------------------------------------------------------ static


class TestStatic:
    def test_the_dashboard_is_served_from_the_root(self, as_) -> None:
        status, body, headers = as_().get("/")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert b"dash" in body["_raw"]

    def test_a_named_file_is_served_with_its_type(self, as_) -> None:
        status, _, headers = as_().get("/app.js")
        assert status == 200
        assert "javascript" in headers["Content-Type"]

    def test_a_missing_file_is_404(self, as_) -> None:
        assert as_().get("/nope.js")[0] == 404

    @pytest.mark.parametrize(
        "path", ["/../outside.txt", "/%2e%2e/outside.txt", "/./../outside.txt"]
    )
    def test_traversal_out_of_the_root_is_refused(self, as_, path: str) -> None:
        status, body, _ = as_().get(path)
        assert status == 404
        assert b"not served" not in body.get("_raw", b"")

    def test_a_symlink_out_of_the_root_is_refused(self, as_, static_root: Path) -> None:
        (static_root / "escape.txt").symlink_to(static_root.parent / "outside.txt")
        status, body, _ = as_().get("/escape.txt")
        assert status == 404
        assert b"not served" not in body.get("_raw", b"")

    def test_no_static_root_means_404_not_500(self, tmp_path: Path, results, token_file) -> None:
        app = App(
            results=results,
            policy_root=tmp_path,
            authenticator=TokenFileAuthenticator(token_file),
            quiet=True,
        )
        httpd = serve(app, port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            assert Client(int(httpd.server_address[1])).get("/")[0] == 404
        finally:
            httpd.shutdown()
            httpd.server_close()


# --------------------------------------------------------------------- cli


class TestServeCommand:
    """`ironclad serve` and `ironclad hash-token`, through `main`."""

    def test_hash_token_reads_stdin_and_never_the_command_line(self, monkeypatch, capsys) -> None:
        import io

        from ironclad.cli import main

        monkeypatch.setattr("sys.stdin", io.StringIO("s3cret-token\n"))
        assert main(["hash-token"]) == 0
        assert capsys.readouterr().out.strip() == hash_token("s3cret-token")

    def test_hash_token_with_nothing_on_stdin_is_an_error(self, monkeypatch, capsys) -> None:
        import io

        from ironclad.cli import main

        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert main(["hash-token"]) == 2
        assert "no token" in capsys.readouterr().err

    def test_serve_refuses_without_a_store(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from ironclad.cli import main

        monkeypatch.delenv("IRONCLAD_STORE", raising=False)
        assert main(["serve", "--policy-root", str(tmp_path)]) == 2
        assert "no store target" in capsys.readouterr().err

    def test_serve_refuses_a_missing_policy_root(self, tmp_path: Path, capsys) -> None:
        from ironclad.cli import main

        code = main(
            ["serve", "--to", str(tmp_path / "results"), "--policy-root", str(tmp_path / "nope")]
        )
        assert code == 2
        assert "policy root" in capsys.readouterr().err

    def test_serve_refuses_a_missing_token_file(self, tmp_path: Path, capsys) -> None:
        from ironclad.cli import main

        code = main(
            [
                "serve",
                "--to",
                str(tmp_path / "results"),
                "--policy-root",
                str(tmp_path),
                "--tokens",
                str(tmp_path / "missing.json"),
            ]
        )
        assert code == 2
        assert "token file not found" in capsys.readouterr().err

    def test_serve_runs_as_a_process(self, tmp_path: Path, token_file: Path, static_root) -> None:
        # The whole command, as an operator would run it: a subprocess on a
        # port the OS chooses, found by reading the line the server prints.
        import re
        import subprocess
        import sys
        import time

        policy_root = tmp_path / "policies"
        policy_root.mkdir()
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ironclad.cli",
                "serve",
                "--to",
                str(tmp_path / "results"),
                "--policy-root",
                str(policy_root),
                "--tokens",
                str(token_file),
                "--static",
                str(static_root),
                "--port",
                "0",
                "--quiet",
            ],
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert process.stderr is not None
            line = ""
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                line = process.stderr.readline()
                if "serving" in line or not line:
                    break
            match = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
            assert match, f"the server did not announce a port: {line!r}"
            port = int(match.group(1))
            status, body, _ = Client(port).get("/api/v1/health")
            assert status == 200 and body["writable"] is True
            assert Client(port).get("/")[0] == 200
            assert Client(port).get("/api/v1/me")[0] == 401
        finally:
            process.terminate()
            process.wait(timeout=10)


# ------------------------------------------------------------ engine faults


class TestEngineFaults:
    def test_a_corrupt_policy_file_is_a_500_with_the_reason(self, as_, server) -> None:
        # A hand-edited policy.json that is not JSON. The tenant's register
        # must come back as an error naming the file, not as a dropped
        # connection from a handler thread that raised.
        _, _, policy_root = server
        (policy_root / "acme").mkdir()
        (policy_root / "acme" / "policy.json").write_text("{not json")
        status, body, _ = as_("acme-manager").get("/api/v1/tenants/acme/exceptions")
        assert status == 500
        assert "policy.json" in body["errors"][0]

    def test_a_policy_file_naming_another_tenant_is_refused_on_write(self, as_, server) -> None:
        # The store refuses to write an acceptance into a file that belongs to
        # a different tenant. That refusal is an engine error, and it reaches
        # the caller as one rather than as a silent 200.
        _, _, policy_root = server
        (policy_root / "acme").mkdir()
        (policy_root / "acme" / "policy.json").write_text(
            json.dumps({"policy_version": "1.0", "tenant_id": "beta", "exceptions": []})
        )
        status, body, _ = as_("acme-manager").post(
            "/api/v1/tenants/acme/exceptions",
            {"control_id": "CC1.1", "justification": "scheduled"},
        )
        assert status == 500
        assert "belongs to tenant 'beta'" in body["errors"][0]

    def test_the_limit_is_capped_not_refused(self, as_) -> None:
        status, _, _ = as_("acme-viewer").get("/api/v1/tenants/acme/assessments?limit=999999")
        assert status == 200

    def test_head_on_anything_but_health_is_405(self, port: int) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("HEAD", "/api/v1/me")
        assert conn.getresponse().status == 405

    def test_a_directory_under_the_static_root_serves_its_index(self, as_, static_root) -> None:
        (static_root / "sub").mkdir()
        (static_root / "sub" / "index.html").write_text("<title>sub</title>")
        status, body, _ = as_().get("/sub/")
        assert status == 200
        assert b"sub" in body["_raw"]

    def test_a_bad_content_length_is_400(self, port: int, secrets_for) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.putrequest("POST", "/api/v1/tenants/acme/exceptions")
        conn.putheader("Authorization", f"Bearer {secrets_for['acme-manager']}")
        conn.putheader("Content-Length", "lots")
        conn.endheaders()
        assert conn.getresponse().status == 400
