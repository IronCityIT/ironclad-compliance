"""Multi-tenancy and RBAC.

The rule under test everywhere here: a principal acts on their own tenant, with
the permissions their roles grant, and nothing else. Both halves are checked
because failing either one is a data breach rather than a bug.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ironclad.errors import AuthorizationError
from ironclad.ids import slugify
from ironclad.model.tenant import (
    ALL_PERMISSIONS,
    PERMISSIONS,
    Principal,
    Role,
    SystemPrincipal,
    authorize,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def principal(*roles: Role, tenant: str = "acme", user: str = "u1") -> Principal:
    return Principal(user_id=user, tenant_id=tenant, roles=frozenset(roles))


class TestPermissionMatrix:
    def test_every_role_grants_only_known_permissions(self) -> None:
        for role, granted in PERMISSIONS.items():
            unknown = granted - ALL_PERMISSIONS
            assert not unknown, f"{role} grants unknown permissions: {unknown}"

    def test_an_auditor_reads_everything_and_writes_nothing(self) -> None:
        auditor = principal(Role.AUDITOR)
        for permission in ("assessment:read", "evidence:read", "audit:read", "report:export"):
            assert auditor.can(permission)
        for permission in ("assessment:run", "evidence:write", "remediation:write"):
            assert not auditor.can(permission)

    def test_an_auditor_cannot_approve_the_risk_they_are_auditing(self) -> None:
        assert not principal(Role.AUDITOR).can("exception:approve")

    def test_a_viewer_cannot_see_the_evidence_or_the_audit_trail(self) -> None:
        viewer = principal(Role.VIEWER)
        assert viewer.can("assessment:read")
        assert not viewer.can("evidence:read")
        assert not viewer.can("audit:read")

    def test_a_contributor_may_request_but_not_approve_an_acceptance(self) -> None:
        contributor = principal(Role.CONTRIBUTOR)
        assert contributor.can("exception:request")
        assert not contributor.can("exception:approve")

    def test_only_the_owner_manages_the_tenant(self) -> None:
        assert principal(Role.OWNER).can("tenant:manage")
        for role in (Role.COMPLIANCE_MANAGER, Role.CONTRIBUTOR, Role.AUDITOR, Role.VIEWER):
            assert not principal(role).can("tenant:manage")

    def test_roles_are_additive(self) -> None:
        combined = principal(Role.VIEWER, Role.AUDITOR)
        assert combined.can("audit:read")


class TestAuthorize:
    def test_a_permitted_call_in_the_callers_own_tenant_passes(self) -> None:
        authorize(principal(Role.COMPLIANCE_MANAGER), "assessment:run", "acme")

    def test_a_cross_tenant_call_is_refused_even_with_the_permission(self) -> None:
        caller = principal(Role.OWNER, tenant="acme")
        with pytest.raises(AuthorizationError, match="another tenant"):
            authorize(caller, "assessment:read", "other-co")

    def test_the_tenant_check_runs_before_the_permission_check(self) -> None:
        # A cross-tenant probe must fail identically whether or not the caller
        # holds the permission, so the message cannot be used to discover
        # whether the other tenant exists.
        privileged = principal(Role.OWNER, tenant="acme")
        unprivileged = principal(Role.VIEWER, tenant="acme")
        messages = set()
        for caller in (privileged, unprivileged):
            with pytest.raises(AuthorizationError) as caught:
                authorize(caller, "assessment:run", "other-co")
            messages.add(str(caught.value))
        assert len(messages) == 1

    def test_a_missing_permission_is_refused_in_the_callers_own_tenant(self) -> None:
        with pytest.raises(AuthorizationError, match="lacks"):
            authorize(principal(Role.VIEWER), "assessment:run", "acme")

    def test_an_unknown_permission_is_a_hard_error(self) -> None:
        with pytest.raises(AuthorizationError, match="unknown permission"):
            authorize(principal(Role.OWNER), "assessment:destroy", "acme")

    def test_a_principal_with_no_roles_can_do_nothing(self) -> None:
        with pytest.raises(AuthorizationError):
            authorize(principal(), "assessment:read", "acme")


class TestSystemPrincipal:
    def test_the_pipeline_may_run_assessments_for_any_tenant(self) -> None:
        authorize(SystemPrincipal(), "assessment:run", "acme")
        authorize(SystemPrincipal(), "assessment:run", "other-co")

    def test_the_pipeline_may_not_approve_a_risk_acceptance(self) -> None:
        # Accepting risk is a human decision. Automation must never sign for it.
        with pytest.raises(AuthorizationError, match="lacks"):
            authorize(SystemPrincipal(), "exception:approve", "acme")


class TestPrincipalFromClaims:
    def test_claims_map_onto_a_principal(self) -> None:
        caller = Principal.from_claims(
            {
                "sub": "auth0|1",
                "client_id": "acme",
                "roles": ["compliance_manager"],
                "email": "a@b.c",
            }
        )
        assert caller.tenant_id == "acme"
        assert caller.roles == frozenset({Role.COMPLIANCE_MANAGER})

    def test_an_unrecognised_role_is_dropped_not_guessed(self) -> None:
        # A typo in an Auth0 role must never become a permission grant.
        caller = Principal.from_claims(
            {"sub": "auth0|1", "client_id": "acme", "roles": ["complaince_manager", "viewer"]}
        )
        assert caller.roles == frozenset({Role.VIEWER})

    def test_claims_without_roles_grant_nothing(self) -> None:
        caller = Principal.from_claims({"sub": "auth0|1", "client_id": "acme"})
        assert caller.permissions == frozenset()


class TestTheSlugIsTheSameInBothLanguages:
    """The tenant partition depends on Python and JavaScript agreeing.

    `ironclad.ids.slugify` mints the client_id the pipeline writes under;
    `functions/core.js::toClientId` derives the one the ingest, the Auth0 bridge
    and the dispatcher address. If the two ever disagree on a character, a
    client's results land in a document their dashboard does not read — and the
    only symptom is an empty dashboard.
    """

    CASES = [
        "Acme Corp",
        "  ACME  Corp  ",
        "Acme, Inc.",
        "a---b",
        "--acme--",
        "!!!",
        "",
        "ACME",
        "acme",
        "Örebro Kommun",
        "St. Mary's Hospital",
        "client/beta",
        "../../etc/passwd",
        "__proto__",
        "123",
        "a b  c   d",
        "Iron City IT Advisors",
        "tenant_with_underscores",
        "trailing-",
        "-leading",
        "MiXeD CaSe 42",
    ]

    def test_the_two_implementations_agree(self) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not available; the parity check runs in CI")

        script = (
            "const {toClientId} = require(process.argv[1]);"
            "const cases = JSON.parse(process.argv[2]);"
            "console.log(JSON.stringify(cases.map(toClientId)));"
        )
        completed = subprocess.run(
            [
                node,
                "-e",
                script,
                str(REPO_ROOT / "functions" / "core.js"),
                json.dumps(self.CASES),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        from_js = json.loads(completed.stdout)
        from_python = [slugify(case) for case in self.CASES]
        assert from_js == from_python, dict(
            zip(self.CASES, zip(from_python, from_js, strict=True), strict=True)
        )
