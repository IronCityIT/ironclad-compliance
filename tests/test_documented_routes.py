"""The route table in `docs/http-api.md` is the router `ironclad serve` builds.

The table is what a dashboard author, a partner's integrator or an auditor reads
to learn what the server answers and who may ask. Nothing held it to
`App._register()`: a route added without a row would be a surface nobody
reviewed, a row left behind by a removed route would be a promise the server
breaks, and a "Needs" cell out of step with the permission the service checks
would tell an auditor the wrong access rule for PHI-adjacent data.

Each row's method and path must be a registered route, and each registered
route a row. The query parameters a row shows must be the ones its handler
reads, and no more. The "Needs" cell must be what the handler enforces: the
permission the service method it calls authorizes, a role anywhere in the
tenant, the register's maintainer roles, a token alone, or nothing.
"""

from __future__ import annotations

import inspect
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

from ironclad import oversight
from ironclad.api.http import API_PREFIX, App, Request
from ironclad.api.service import ComplianceService
from ironclad.model.tenant import Role

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "http-api.md"

_ROW = re.compile(r"^\| (GET|POST|PUT|PATCH|DELETE) \| `([^`]+)` \| ([^|]+) \|")
_PLACEHOLDER = re.compile(r"\{\w+\}")
_NAMED_GROUP = re.compile(r"\(\?P<\w+>[^)]*\)")
_QUERY_READ = re.compile(r"""(?:int_query|query\.get)\(\s*"(\w+)\"""")
_SERVICE_CALL = re.compile(r"\bservice\.(\w+)\(")
_AUTHORIZED = re.compile(r"""authorize\(\s*principal,\s*"([a-z]+:[a-z]+)\"""")
_PERMISSION = re.compile(r"^`([a-z]+:[a-z]+)`$")


def _section(text: str, heading: str) -> str:
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def documented_routes() -> list[tuple[str, str, list[str], str]]:
    """(method, path without its query, query names, needs) for each row."""
    text = DOC.read_text(encoding="utf-8").replace("\r\n", "\n")
    rows = []
    for line in _section(text, "Routes").split("\n"):
        match = _ROW.match(line)
        if not match:
            continue
        method, written, needs = match.groups()
        path, _, query = written.partition("?")
        names = [part.split("=")[0] for part in query.split("&") if part]
        rows.append((method, path, names, needs.strip()))
    return rows


def _shape(path: str) -> str:
    return _PLACEHOLDER.sub("{}", path)


@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory) -> App:
    return App(
        results=_Healthy(), policy_root=tmp_path_factory.mktemp("policy"), authenticator=None
    )


class _Healthy:
    def health(self) -> dict[str, Any]:
        return {"store": "stub", "writable": True}


def _registered(app: App) -> dict[tuple[str, str], Any]:
    """(method, shape) -> handler, for every route the router matches."""
    found = {}
    for method, regex, handler in app._routes:
        pattern = regex.pattern.removeprefix("^").removesuffix("$")
        found[(method, _NAMED_GROUP.sub("{}", pattern))] = handler
    return found


def _source(handler: Any) -> str:
    return inspect.getsource(handler)


ROWS = documented_routes()
ROW_IDS = [f"{method} {path}" for method, path, _, _ in ROWS]


def test_the_table_was_found() -> None:
    # A heading or table reshaped out of the parser's reach would pass every
    # case below with nothing checked.
    assert len(ROWS) >= 20
    assert ("GET", "/health") in {(m, p) for m, p, _, _ in ROWS}


def test_no_row_is_listed_twice() -> None:
    keys = [(method, _shape(path)) for method, path, _, _ in ROWS]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(("method", "path", "query", "needs"), ROWS, ids=ROW_IDS)
def test_each_row_is_a_route_the_server_has(
    app: App, method: str, path: str, query: list[str], needs: str
) -> None:
    if path == "/health":
        # Answered before routing and before authentication; asked the way a
        # load balancer would, with no authenticator configured at all.
        response = app.handle(Request(method, API_PREFIX + path, {}, {}, b""))
        assert response.status == HTTPStatus.OK
        return
    assert (method, _shape(API_PREFIX + path)) in _registered(app)


def test_each_route_the_server_has_is_a_row(app: App) -> None:
    documented = {(method, _shape(API_PREFIX + path)) for method, path, _, _ in ROWS}
    undocumented = sorted(set(_registered(app)) - documented)
    assert not undocumented, f"routes docs/http-api.md does not list: {undocumented}"


@pytest.mark.parametrize(("method", "path", "query", "needs"), ROWS, ids=ROW_IDS)
def test_the_query_a_row_shows_is_what_its_handler_reads(
    app: App, method: str, path: str, query: list[str], needs: str
) -> None:
    if path == "/health":
        handler_source = _source(App.health)
    else:
        handler_source = _source(_registered(app)[(method, _shape(API_PREFIX + path))])
    assert sorted(query) == sorted(set(_QUERY_READ.findall(handler_source)))


@pytest.mark.parametrize(("method", "path", "query", "needs"), ROWS, ids=ROW_IDS)
def test_the_needs_cell_is_what_the_handler_enforces(
    app: App, method: str, path: str, query: list[str], needs: str
) -> None:
    if path == "/health":
        assert needs == "nothing"
        return
    source = _source(_registered(app)[(method, _shape(API_PREFIX + path))])
    scoped = re.search(r"_oversight_scope\([^)]*write=(True|False)", source)
    calls = _SERVICE_CALL.findall(source)

    if needs == "a token":
        # Authenticated by `handle`, and nothing further asked of the caller.
        assert not scoped and not calls
    elif needs == "any role in the tenant":
        assert scoped and scoped.group(1) == "False"
    elif needs == "owner, compliance manager, contributor":
        assert scoped and scoped.group(1) == "True"
        named = {name.strip().replace(" ", "_") for name in needs.split(",")}
        assert named == {str(role) for role in oversight.MAINTAIN_ROLES}
    else:
        permission = _PERMISSION.match(needs)
        assert permission, f"{method} {path}: unrecognised Needs cell {needs!r}"
        assert len(calls) == 1, calls
        checked = _AUTHORIZED.findall(_source(getattr(ComplianceService, calls[0])))
        assert checked == [permission.group(1)]


def test_every_role_the_doc_names_exists() -> None:
    text = DOC.read_text(encoding="utf-8").replace("\r\n", "\n")
    sentence = re.search(r"a set of roles \(([^)]*)\)", _section(text, "Authentication"))
    assert sentence
    named = re.findall(r"`(\w+)`", sentence.group(1))
    assert sorted(named) == sorted(role.value for role in Role)


def test_the_register_kinds_the_table_names_are_the_registers() -> None:
    text = DOC.read_text(encoding="utf-8").replace("\r\n", "\n")
    row = next(line for line in text.split("\n") if "| `/tenants/{t}/oversight/{kind}` |" in line)
    assert re.findall(r"`kind` is `(\w+)` or `(\w+)`", row) == [oversight.KINDS]
