"""The publish step's endpoint guard.

scripts/store_results.py opens an operator-supplied URL. urlopen honours file://
and other schemes, so an endpoint that was mistyped — or tampered with upstream —
could turn "publish a result" into "read a local file and report it as an HTTP
response". These are the checks that stop that, and the reason the bandit B310
finding was fixed rather than suppressed.
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

    def test_loopback_http_is_allowed_for_the_emulator(
        self, store_results: Any, monkeypatch
    ) -> None:
        opened: dict[str, Any] = {}

        class FakeResponse:
            status = 200

            def read(self) -> bytes:
                return b'{"status":"stored"}'

            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        def fake_urlopen(request: Any, timeout: int = 0) -> FakeResponse:
            opened["url"] = request.full_url
            return FakeResponse()

        monkeypatch.setattr(store_results.urllib.request, "urlopen", fake_urlopen)
        ok, message = store_results.post_result("http://localhost:5001/ingest", {"a": 1})
        assert ok
        assert opened["url"] == "http://localhost:5001/ingest"

    def test_https_is_allowed_and_carries_the_ingest_key(
        self, store_results: Any, monkeypatch
    ) -> None:
        captured: dict[str, Any] = {}

        class FakeResponse:
            status = 200

            def read(self) -> bytes:
                return b'{"status":"stored"}'

            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        def fake_urlopen(request: Any, timeout: int = 0) -> FakeResponse:
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.data)
            return FakeResponse()

        monkeypatch.setattr(store_results.urllib.request, "urlopen", fake_urlopen)
        ok, _ = store_results.post_result(
            "https://ingest.example.com/x", {"client_id": "acme"}, api_key="k" * 20
        )
        assert ok
        assert captured["body"]["client_id"] == "acme"
        assert captured["headers"]["X-ingest-key"] == "k" * 20


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
