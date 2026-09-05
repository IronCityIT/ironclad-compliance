"""Tenants, roles and the permission matrix.

Multi-tenancy here is not a filter applied late — a Principal is bound to one
tenant, and every service call checks both "may this role do this" and "is this
the caller's own tenant". The two checks are separate on purpose: a compliance
manager at one client holds real authority and no authority at all next door.

Roles map to Auth0 Organization roles. The claim names used by firestore.rules
(`client_id`) and by the token exchange are the contract between this matrix and
the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ironclad.errors import AuthorizationError


class Role(str, Enum):
    """Least privilege first; each role adds only what its job needs."""

    OWNER = "owner"  # tenant administrator
    COMPLIANCE_MANAGER = "compliance_manager"  # runs the programme
    CONTRIBUTOR = "contributor"  # uploads evidence, works remediation
    AUDITOR = "auditor"  # external reader: sees everything, changes nothing
    VIEWER = "viewer"  # internal reader, no evidence access

    def __str__(self) -> str:
        return self.value


# Every permission the service surface gates on. Named <object>:<verb>.
PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.OWNER: frozenset(
        {
            "assessment:read", "assessment:run",
            "evidence:read", "evidence:write",
            "remediation:read", "remediation:write",
            "exception:read", "exception:request", "exception:approve",
            "audit:read",
            "report:read", "report:export",
            "tenant:read", "tenant:manage",
        }
    ),
    Role.COMPLIANCE_MANAGER: frozenset(
        {
            "assessment:read", "assessment:run",
            "evidence:read", "evidence:write",
            "remediation:read", "remediation:write",
            "exception:read", "exception:request", "exception:approve",
            "audit:read",
            "report:read", "report:export",
            "tenant:read",
        }
    ),
    Role.CONTRIBUTOR: frozenset(
        {
            "assessment:read",
            "evidence:read", "evidence:write",
            "remediation:read", "remediation:write",
            "exception:read", "exception:request",
            "report:read",
            "tenant:read",
        }
    ),
    # An auditor reads everything, including the evidence and the audit trail,
    # and writes nothing. No exception:approve — an auditor signing off on the
    # risk they are auditing is exactly the conflict the role exists to avoid.
    Role.AUDITOR: frozenset(
        {
            "assessment:read",
            "evidence:read",
            "remediation:read",
            "exception:read",
            "audit:read",
            "report:read", "report:export",
            "tenant:read",
        }
    ),
    Role.VIEWER: frozenset(
        {
            "assessment:read",
            "remediation:read",
            "report:read",
            "tenant:read",
        }
    ),
}

ALL_PERMISSIONS: frozenset[str] = frozenset().union(*PERMISSIONS.values())


@dataclass(frozen=True)
class Tenant:
    """One client of the platform."""

    tenant_id: str
    name: str
    auth0_org_id: str = ""
    frameworks: tuple[str, ...] = ()
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "auth0_org_id": self.auth0_org_id,
            "frameworks": list(self.frameworks),
            "active": self.active,
        }


@dataclass(frozen=True)
class Principal:
    """Who is calling, and on behalf of which tenant."""

    user_id: str
    tenant_id: str
    roles: frozenset[Role] = field(default_factory=frozenset)
    email: str = ""

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> Principal:
        """Build a principal from the verified Auth0 -> Firebase token claims.

        Unknown role strings are dropped rather than guessed at: a typo in an
        Auth0 role must not silently become a permission grant.
        """
        raw_roles = claims.get("roles") or []
        roles = {Role(r) for r in raw_roles if r in {member.value for member in Role}}
        return cls(
            user_id=str(claims.get("sub", "")),
            tenant_id=str(claims.get("client_id", "")),
            roles=frozenset(roles),
            email=str(claims.get("email", "")),
        )

    @property
    def permissions(self) -> frozenset[str]:
        """The union of every permission the principal's roles grant."""
        granted: set[str] = set()
        for role in self.roles:
            granted |= PERMISSIONS[role]
        return frozenset(granted)

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "roles": sorted(str(r) for r in self.roles),
            "email": self.email,
        }


# The service account the scan workflows run as. It may run assessments and
# write results for any tenant, because the workflow is the ingestion path; it
# may not approve a risk acceptance, which is a human decision by design.
SYSTEM_PERMISSIONS: frozenset[str] = frozenset(
    {
        "assessment:read", "assessment:run",
        "evidence:read", "evidence:write",
        "remediation:read", "remediation:write",
        "exception:read",
        "audit:read",
        "report:read", "report:export",
        "tenant:read",
    }
)


@dataclass(frozen=True)
class SystemPrincipal:
    """The pipeline's own identity. Tenant-agnostic, deliberately limited."""

    user_id: str = "system:pipeline"
    tenant_id: str = "*"
    email: str = ""

    @property
    def roles(self) -> frozenset[Role]:
        return frozenset()

    @property
    def permissions(self) -> frozenset[str]:
        return SYSTEM_PERMISSIONS

    def can(self, permission: str) -> bool:
        return permission in SYSTEM_PERMISSIONS

    def to_dict(self) -> dict[str, Any]:
        return {"user_id": self.user_id, "tenant_id": self.tenant_id, "roles": [], "email": ""}


def authorize(principal: Any, permission: str, tenant_id: str) -> None:
    """Gate one call. Raises AuthorizationError; returns nothing on success.

    Both halves are checked. The tenant check runs first so a cross-tenant probe
    fails the same way whether or not the caller holds the permission, and the
    message never reveals whether the other tenant exists.
    """
    if permission not in ALL_PERMISSIONS:
        raise AuthorizationError(f"unknown permission {permission!r}")

    caller_tenant = getattr(principal, "tenant_id", "")
    if caller_tenant != "*" and caller_tenant != tenant_id:
        raise AuthorizationError(
            f"{getattr(principal, 'user_id', 'caller')} may not act on another tenant"
        )

    if not principal.can(permission):
        raise AuthorizationError(
            f"{getattr(principal, 'user_id', 'caller')} lacks {permission!r} "
            f"(roles: {', '.join(sorted(str(r) for r in getattr(principal, 'roles', []))) or 'none'})"
        )
