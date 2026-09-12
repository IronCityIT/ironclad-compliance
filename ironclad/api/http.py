"""The HTTP surface over `ComplianceService`.

This is what gives the dashboard a backend that is not Firebase: the same
service the CLI drives, reachable over HTTP, reading assessments from the
result store (a NAS volume or MariaDB) and the risk-acceptance workflow from
each tenant's policy file. Standard library only, like the rest of the engine —
`http.server` and `json` — so it runs on the NAS with nothing installed.

Three rules, each of which has already bitten this product once elsewhere:

**Fail closed.** A server with no authenticator refuses every request with 503
rather than serving anything. The retired ingest function treated an unset
key as "open by config" and would have accepted any tenant's writes from
anyone; this surface does not have that setting.

**The caller's tenant comes from their credential, never from the URL.** The
tenant in the path is what the caller is asking about; the service's own
`authorize` compares it with the principal and refuses a mismatch. Nothing
here reinterprets a request to mean the caller's own tenant.

**A refusal names its kind, not its wording.** `ServiceResponse.kind` maps to
the status code — 400, 403, 404, 503 — so the transport never guesses from
message text which refusal it is holding.

What is deliberately not here: running an assessment. The pipeline runs
assessments, with evidence staged from the tenant's volume; a POST carrying
evidence is a different product. The surface reads results and works the
acceptance workflow, which is everything the dashboard does.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from ironclad import registry
from ironclad.api.policy_store import PolicyStore
from ironclad.api.schemas import ExceptionRequest, ServiceResponse
from ironclad.api.service import ComplianceService
from ironclad.errors import IroncladError
from ironclad.frameworks.loader import available_frameworks
from ironclad.ids import slugify
from ironclad.model.tenant import Principal
from ironclad.store.base import StoreError
from ironclad.version import __version__

API_PREFIX = "/api/v1"
POLICY_FILENAME = "policy.json"

#: The most a request body may carry. The largest legitimate body is a risk
#: acceptance with a 4,000-character justification; anything near this is not
#: one of those.
MAX_BODY_BYTES = 64 * 1024

STATUS_FOR_KIND = {
    "validation": HTTPStatus.BAD_REQUEST,
    "authorization": HTTPStatus.FORBIDDEN,
    "not_found": HTTPStatus.NOT_FOUND,
    "unavailable": HTTPStatus.SERVICE_UNAVAILABLE,
}


# --------------------------------------------------------------- authentication


class Authenticator(Protocol):
    """Turns a bearer token into a principal, or nothing."""

    def principal_for(self, token: str) -> Principal | None: ...


class TokenFileAuthenticator:
    """Service tokens from a JSON file, stored hashed.

    The shape:

        {"tokens": [
          {"sha256": "<hex of the token>", "user_id": "alice@example.com",
           "tenant_id": "acme", "roles": ["compliance_manager"]}
        ]}

    The file holds digests, never tokens, so reading it grants nothing. Every
    request re-reads it — the file is the record, not a cache, the same rule
    the policy store follows — so a revoked token stops working on the next
    request rather than at the next restart.

    This is the authenticator for a LAN deployment behind a reverse proxy. An
    Auth0-issued JWT needs RSA signature verification the standard library does
    not provide; that is a separate authenticator behind a dependency decision,
    and it plugs in through the same protocol.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _entries(self) -> list[dict[str, Any]]:
        document = json.loads(self.path.read_text(encoding="utf-8"))
        entries = document.get("tokens") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            raise IroncladError(f"{self.path} is not a token file")
        return [e for e in entries if isinstance(e, dict)]

    def principal_for(self, token: str) -> Principal | None:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        for entry in self._entries():
            stored = str(entry.get("sha256", "")).strip().lower()
            if not stored or not hmac.compare_digest(stored, digest):
                continue
            tenant = str(entry.get("tenant_id", "")).strip()
            if not tenant or slugify(tenant) != tenant:
                # A token bound to no tenant, or to a name that is not a
                # tenant id, is a misconfiguration; it authenticates nobody.
                return None
            return Principal.from_claims(
                {
                    "sub": str(entry.get("user_id", "")),
                    "client_id": tenant,
                    "roles": list(entry.get("roles") or []),
                    "email": str(entry.get("email", "")),
                }
            )
        return None


def hash_token(token: str) -> str:
    """The digest a token file stores for a token. Here so an operator has it."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------- app


@dataclass
class Request:
    """One parsed request, with the routing already done."""

    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes
    params: dict[str, str] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        """The body as a JSON object. Anything else is a 400."""
        if not self.body:
            return {}
        try:
            payload = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpError(HTTPStatus.BAD_REQUEST, f"body is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise HttpError(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
        return payload

    def int_query(self, name: str, default: int, maximum: int) -> int:
        raw = self.query.get(name, [""])[0]
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise HttpError(HTTPStatus.BAD_REQUEST, f"{name} must be an integer") from exc
        if value < 1:
            raise HttpError(HTTPStatus.BAD_REQUEST, f"{name} must be at least 1")
        return min(value, maximum)


@dataclass
class Response:
    status: HTTPStatus
    body: dict[str, Any]


class HttpError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


Handler = Callable[[Request, Principal], Response]

_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._@:+-]*"


class App:
    """The routes, and the collaborators every route shares.

    Built once, then served by as many handler instances as there are
    connections. Holds no per-request state.
    """

    def __init__(
        self,
        results: Any,
        policy_root: Path | str,
        authenticator: Authenticator | None,
        static_root: Path | str | None = None,
        quiet: bool = False,
    ) -> None:
        self.results = results
        self.quiet = quiet
        self.policy_root = Path(policy_root)
        self.authenticator = authenticator
        self.static_root = Path(static_root).resolve() if static_root else None
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = []
        self._register()

    # ------------------------------------------------------------- wiring

    def _route(self, method: str, pattern: str, handler: Handler) -> None:
        regex = "^" + re.sub(r"\{(\w+)\}", rf"(?P<\1>{_SEGMENT})", pattern) + "$"
        self._routes.append((method, re.compile(regex), handler))

    def _register(self) -> None:
        tenant = API_PREFIX + "/tenants/{tenant_id}"
        self._route("GET", API_PREFIX + "/me", self.me)
        self._route("GET", API_PREFIX + "/catalog", self.catalog)
        self._route("GET", tenant + "/assessments", self.list_assessments)
        self._route("GET", tenant + "/assessments/{assessment_id}", self.get_assessment)
        self._route("GET", tenant + "/remediation", self.list_remediation)
        self._route("GET", tenant + "/exceptions", self.list_exceptions)
        self._route("POST", tenant + "/exceptions", self.request_exception)
        self._route("POST", tenant + "/exceptions/{exception_id}/approve", self.approve_exception)
        self._route("POST", tenant + "/exceptions/{exception_id}/revoke", self.revoke_exception)
        self._route("GET", tenant + "/audit", self.audit_trail)

    def service_for(self, tenant_id: str) -> ComplianceService:
        """The service bound to one tenant's policy file and the shared results.

        The tenant id is a path segment on the policy volume, so it is checked
        against its own slug before it becomes one: a value that would
        normalise into a different name is refused, not normalised. Nothing is
        created here — the policy store makes the tenant's directory when it
        first writes, which is after the service has authorized the write.
        """
        if not tenant_id or slugify(tenant_id) != tenant_id:
            raise HttpError(HTTPStatus.BAD_REQUEST, f"{tenant_id!r} is not a tenant id")
        return ComplianceService(
            store=PolicyStore(self.policy_root / tenant_id / POLICY_FILENAME),
            results=self.results,
        )

    # ----------------------------------------------------------- dispatch

    def handle(self, request: Request) -> Response:
        """Authenticate, route, and translate the service's answer."""
        if request.path == API_PREFIX + "/health" and request.method == "GET":
            return self.health()

        if not request.path.startswith(API_PREFIX + "/"):
            raise HttpError(HTTPStatus.NOT_FOUND, "no such route")

        principal = self._authenticate(request)

        path_known = False
        for method, regex, handler in self._routes:
            match = regex.match(request.path)
            if not match:
                continue
            path_known = True
            if method != request.method:
                # The same path may be registered under two verbs; keep looking
                # before deciding the verb is the problem.
                continue
            request.params = match.groupdict()
            return handler(request, principal)
        if path_known:
            raise HttpError(HTTPStatus.METHOD_NOT_ALLOWED, f"{request.method} not allowed here")
        raise HttpError(HTTPStatus.NOT_FOUND, "no such route")

    def _authenticate(self, request: Request) -> Principal:
        if self.authenticator is None:
            # Not 401: there is nothing the caller could present. The server is
            # misconfigured and says so rather than serving anyone.
            raise HttpError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "this server has no authenticator configured and serves nothing until it does",
            )
        header = request.headers.get("authorization", "")
        scheme, _, token = header.strip().partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HttpError(HTTPStatus.UNAUTHORIZED, "a bearer token is required")
        try:
            principal = self.authenticator.principal_for(token.strip())
        except (OSError, ValueError, IroncladError) as exc:
            # The token file is unreadable or malformed. Nobody is
            # authenticated, and the reason is the operator's, not the caller's.
            raise HttpError(
                HTTPStatus.SERVICE_UNAVAILABLE, f"the authenticator cannot answer: {exc}"
            ) from exc
        if principal is None:
            raise HttpError(HTTPStatus.UNAUTHORIZED, "the token is not recognised")
        return principal

    @staticmethod
    def _translate(response: ServiceResponse) -> Response:
        if response.ok:
            return Response(HTTPStatus.OK, {"ok": True, "data": response.data, "errors": []})
        status = STATUS_FOR_KIND.get(response.kind, HTTPStatus.BAD_REQUEST)
        return Response(status, {"ok": False, "data": {}, "errors": list(response.errors)})

    # ------------------------------------------------------------- routes

    def health(self) -> Response:
        """Alive, and whether the store can be written. No path, no DSN.

        Unauthenticated so a load balancer can ask; says nothing a stranger
        could use, which is why the store's own health dict is not returned.
        """
        try:
            health = self.results.health()
        except (StoreError, OSError) as exc:  # pragma: no cover — backend-specific
            return Response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "version": __version__, "store": "unreachable", "detail": str(exc)},
            )
        writable = bool(health.get("writable"))
        status = HTTPStatus.OK if writable else HTTPStatus.SERVICE_UNAVAILABLE
        return Response(
            status,
            {
                "ok": writable,
                "version": __version__,
                "store": str(health.get("store", "")),
                "writable": writable,
            },
        )

    def me(self, request: Request, principal: Principal) -> Response:
        return Response(
            HTTPStatus.OK,
            {
                "ok": True,
                "data": {
                    "principal": principal.to_dict(),
                    "permissions": sorted(principal.permissions),
                },
                "errors": [],
            },
        )

    def catalog(self, request: Request, principal: Principal) -> Response:
        """What the dashboard renders its selection from. One source of truth."""
        reg = registry.discover()
        return Response(
            HTTPStatus.OK,
            {
                "ok": True,
                "data": {
                    "modules": registry.catalog(reg),
                    "groups": sorted(registry.all_groups(reg)),
                    "frameworks": available_frameworks(),
                },
                "errors": [],
            },
        )

    def list_assessments(self, request: Request, principal: Principal) -> Response:
        tenant = request.params["tenant_id"]
        limit = request.int_query("limit", default=25, maximum=200)
        service = self.service_for(tenant)
        return self._translate(service.list_assessments(principal, tenant, limit))

    def get_assessment(self, request: Request, principal: Principal) -> Response:
        tenant = request.params["tenant_id"]
        service = self.service_for(tenant)
        return self._translate(
            service.get_assessment(principal, tenant, request.params["assessment_id"])
        )

    def list_remediation(self, request: Request, principal: Principal) -> Response:
        tenant = request.params["tenant_id"]
        limit = request.int_query("limit", default=200, maximum=1000)
        service = self.service_for(tenant)
        return self._translate(service.list_remediation(principal, tenant, limit))

    def list_exceptions(self, request: Request, principal: Principal) -> Response:
        tenant = request.params["tenant_id"]
        status = request.query.get("status", [""])[0]
        service = self.service_for(tenant)
        return self._translate(service.list_exceptions(principal, tenant, status))

    def request_exception(self, request: Request, principal: Principal) -> Response:
        tenant = request.params["tenant_id"]
        payload = request.json()
        # The tenant is the one in the path. A body naming another is not a
        # second opinion; it is dropped, and the path is what gets authorized.
        payload["tenant_id"] = tenant
        payload.pop("client_id", None)
        # The requester is the caller. The service accepts a `requested_by` for
        # the CLI, where the actor is a flag; over HTTP the identity is the
        # token's, and letting the body name someone else would let one person
        # raise an acceptance "for" a colleague and then approve it themselves.
        payload["requested_by"] = principal.user_id
        try:
            exception_request = ExceptionRequest.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise HttpError(HTTPStatus.BAD_REQUEST, f"malformed request: {exc}") from exc
        service = self.service_for(tenant)
        return self._translate(service.request_exception(principal, exception_request))

    def approve_exception(self, request: Request, principal: Principal) -> Response:
        tenant = request.params["tenant_id"]
        service = self.service_for(tenant)
        return self._translate(
            service.approve_exception(principal, tenant, request.params["exception_id"])
        )

    def revoke_exception(self, request: Request, principal: Principal) -> Response:
        tenant = request.params["tenant_id"]
        reason = str(request.json().get("reason", "")).strip()
        if not reason:
            raise HttpError(HTTPStatus.BAD_REQUEST, "a revocation needs a reason")
        service = self.service_for(tenant)
        return self._translate(
            service.revoke_exception(principal, tenant, request.params["exception_id"], reason)
        )

    def audit_trail(self, request: Request, principal: Principal) -> Response:
        tenant = request.params["tenant_id"]
        limit = request.int_query("limit", default=200, maximum=5000)
        service = self.service_for(tenant)
        return self._translate(service.get_audit_trail(principal, tenant, limit))

    # ------------------------------------------------------------- static

    def static_file(self, path: str) -> Path | None:
        """The file a non-API path names, if it is inside the static root.

        Resolved and then checked to still be under the root, so `..` and a
        symlink pointing out of the directory are both refused. Nothing under
        the root is secret — it is the dashboard — but a path that escapes it
        would be.
        """
        if self.static_root is None:
            return None
        relative = path.lstrip("/") or "index.html"
        candidate = (self.static_root / relative).resolve()
        if candidate == self.static_root or self.static_root not in candidate.parents:
            return None
        if candidate.is_dir():
            candidate = candidate / "index.html"
            if self.static_root not in candidate.resolve().parents:  # pragma: no cover
                return None
        return candidate if candidate.is_file() else None


# -------------------------------------------------------------------- server


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class ApiHandler(BaseHTTPRequestHandler):
        server_version = f"IronCityIT-Ironclad/{__version__}"
        sys_version = ""  # the Python version is nobody's business
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            # Method, path and status only. A query string can carry a filter
            # a client typed; the authorization header is never here at all.
            if app.quiet:
                return
            super().log_message(format, *args)

        # -- plumbing

        def _send_json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
            raw = json.dumps(body, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)

        def _send_file(self, path: Path) -> None:
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            raw = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def _read_body(self) -> bytes:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise HttpError(HTTPStatus.BAD_REQUEST, "Content-Length is not a number") from exc
            if length < 0:
                raise HttpError(HTTPStatus.BAD_REQUEST, "Content-Length is negative")
            if length > MAX_BODY_BYTES:
                raise HttpError(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    f"body exceeds {MAX_BODY_BYTES} bytes",
                )
            return self.rfile.read(length) if length else b""

        def _dispatch(self, method: str) -> None:
            parts = urlsplit(self.path)
            body_consumed = False
            try:
                body = self._read_body()
                body_consumed = True
                if not parts.path.startswith(API_PREFIX + "/") and method == "GET":
                    served = app.static_file(parts.path)
                    if served is not None:
                        self._send_file(served)
                        return
                request = Request(
                    method=method,
                    path=parts.path,
                    query=parse_qs(parts.query),
                    headers={k.lower(): v for k, v in self.headers.items()},
                    body=body,
                )
                response = app.handle(request)
            except HttpError as exc:
                if not body_consumed:
                    # The body was refused unread. On a kept-alive connection
                    # the unread bytes would be parsed as the next request
                    # line, so the connection ends with this answer.
                    self.close_connection = True
                self._send_json(exc.status, {"ok": False, "data": {}, "errors": [exc.message]})
                return
            except (IroncladError, StoreError) as exc:
                # The engine refused something the routes did not anticipate:
                # a policy file that will not load, a store that cannot read.
                # Reported as the engine's fault, with its message, never as
                # a stack trace.
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "data": {}, "errors": [str(exc)]},
                )
                return
            self._send_json(response.status, response.body)

        # -- verbs

        def do_GET(self) -> None:  # noqa: N802 — http.server's contract
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def do_HEAD(self) -> None:  # noqa: N802
            # Answer without a body rather than 501, so a probe that only wants
            # the status gets one.
            parts = urlsplit(self.path)
            if parts.path == API_PREFIX + "/health":
                self.send_response(app.health().status)
            else:
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return ApiHandler


def serve(app: App, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    """Bind and return the server. The caller decides when to serve forever.

    Loopback by default: this speaks plain HTTP and expects a reverse proxy to
    terminate TLS in front of it. Binding wider is an explicit choice.
    """
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server
