"""The publish step's endpoint guard.

scripts/store_results.py publishes to an operator-supplied URL. It uses
http.client rather than urllib.request, so a file:// endpoint is structurally
impossible rather than merely rejected — which is how the bandit B310 finding was
resolved without a suppression. These tests cover the remaining scheme policy and
the response handling.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "store_results", REPO_ROOT / "scripts" / "store_results.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def store_results() -> Any:
    return _load_module()


class TestEndpointGuard:
    @pytest.mark.parametrize(
        "endpoint",
        ["file:///etc/passwd", "ftp://host/path", "gopher://host", "", "not-a-url"],
    )
    def test_a_non_network_scheme_is_refused(self, store_results: Any, endpoint: str) -> None:
        ok, message = store_results.post_result(endpoint, {"a": 1})
        assert not ok
        assert "refusing to publish" in message

    def test_plain_http_to_a_remote_host_is_refused(self, store_results: Any) -> None:
        # The result and the ingest key would otherwise go over the wire in clear.
        ok, message = store_results.post_result("http://ingest.example.com/x", {"a": 1})
        assert not ok
        assert "https" in message

    def test_an_endpoint_with_no_host_is_refused(self, store_results: Any) -> None:
        ok, message = store_results.post_result("https:///no-host", {"a": 1})
        assert not ok
        assert "no host" in message

    def test_loopback_http_is_allowed_for_the_emulator(
        self, store_results: Any, monkeypatch
    ) -> None:
        captured = _capture(store_results, monkeypatch, status=200)
        ok, _ = store_results.post_result("http://localhost:5001/ingest", {"a": 1})
        assert ok
        assert captured["class"] == "HTTPConnection"
        assert captured["host"] == "localhost"
        assert captured["port"] == 5001
        assert captured["path"] == "/ingest"

    def test_https_is_allowed_and_carries_the_ingest_key(
        self, store_results: Any, monkeypatch
    ) -> None:
        captured = _capture(store_results, monkeypatch, status=200)
        ok, _ = store_results.post_result(
            "https://ingest.example.com/x?v=1", {"client_id": "acme"}, api_key="k" * 20
        )
        assert ok
        assert captured["class"] == "HTTPSConnection"
        assert captured["path"] == "/x?v=1"
        assert captured["headers"]["X-Ingest-Key"] == "k" * 20
        assert json.loads(captured["body"])["client_id"] == "acme"

    def test_a_non_2xx_response_is_a_failure_carrying_the_upstream_words(
        self, store_results: Any, monkeypatch
    ) -> None:
        # An ingest misconfiguration has to be diagnosable from the workflow log.
        _capture(store_results, monkeypatch, status=404, payload=b'{"error":"not found"}')
        ok, message = store_results.post_result("https://ingest.example.com/x", {"a": 1})
        assert not ok
        assert "404" in message
        assert "not found" in message

    def test_a_transport_failure_is_reported_not_raised(
        self, store_results: Any, monkeypatch
    ) -> None:
        class Exploding:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def request(self, *args: object, **kwargs: object) -> None:
                raise OSError("connection refused")

            def close(self) -> None:
                return None

        monkeypatch.setattr(store_results.http.client, "HTTPSConnection", Exploding)
        ok, message = store_results.post_result("https://ingest.example.com/x", {"a": 1})
        assert not ok
        assert "connection refused" in message


class TestResultDiscovery:
    def test_the_canonical_filename_is_preferred(self, store_results: Any, tmp_path: Path) -> None:
        (tmp_path / "other.json").write_text(json.dumps({"assessment_id": "wrong"}))
        (tmp_path / "assessment.json").write_text(json.dumps({"assessment_id": "right"}))
        assert store_results.find_result(tmp_path)["assessment_id"] == "right"

    def test_a_directory_with_no_assessment_returns_nothing(
        self, store_results: Any, tmp_path: Path
    ) -> None:
        (tmp_path / "unrelated.json").write_text(json.dumps({"not": "an assessment"}))
        assert store_results.find_result(tmp_path) is None

    def test_a_malformed_json_file_is_skipped_not_fatal(
        self, store_results: Any, tmp_path: Path
    ) -> None:
        (tmp_path / "broken.json").write_text("{ not json")
        (tmp_path / "good.json").write_text(json.dumps({"assessment_id": "found"}))
        assert store_results.find_result(tmp_path)["assessment_id"] == "found"


def _capture(store_results: Any, monkeypatch: Any, status: int, payload: bytes = b"{}") -> dict:
    """Stand in for the HTTP connection and record what would have been sent."""
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __init__(self) -> None:
            self.status = status

        def read(self) -> bytes:
            return payload

    def make(name: str):  # type: ignore[no-untyped-def]
        class FakeConnection:
            def __init__(self, host: str, port: int | None = None, timeout: int = 0) -> None:
                captured["class"] = name
                captured["host"] = host
                captured["port"] = port

            def request(self, method: str, path: str, body: bytes, headers: dict) -> None:
                captured["method"] = method
                captured["path"] = path
                captured["body"] = body
                captured["headers"] = headers

            def getresponse(self) -> FakeResponse:
                return FakeResponse()

            def close(self) -> None:
                captured["closed"] = True

        return FakeConnection

    monkeypatch.setattr(store_results.http.client, "HTTPSConnection", make("HTTPSConnection"))
    monkeypatch.setattr(store_results.http.client, "HTTPConnection", make("HTTPConnection"))
    return captured
