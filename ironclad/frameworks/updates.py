"""Watch the official sources for framework revisions.

The original checker searched each page for the words "new version", "updated",
"revision" or "latest" and reported an update if any appeared. Those words appear
on essentially every standards-body page, so the check fired on every run and a
quarterly PR that always says "updates detected" is a check nobody reads.

This does two things that can actually be false:

  1. Looks for a version token in the page that is higher than the version
     recorded in framework-versions.json. A page advertising PCI DSS 4.1 when
     the repository tracks 4.0 is a real signal.
  2. Fingerprints the page's visible text and compares it to the fingerprint
     stored from the previous run. Unchanged content is reported as unchanged.

Network access and `requests` are both optional. Without either, the checker
reports every framework as unchecked rather than failing the workflow.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ironclad.ids import iso, utc_now

USER_AGENT = "IronClad-Compliance-Checker/1.0"
TIMEOUT_SECONDS = 30

# Where the last run's fingerprints live, so a change can be detected between
# runs rather than re-reported every quarter.
STATE_FILE = "framework-check-state.json"

FRAMEWORK_SOURCES: dict[str, dict[str, Any]] = {
    "soc2": {
        "name": "SOC 2 Trust Service Criteria",
        "url": "https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",
        "version_pattern": r"trust services criteria[^.]{0,40}?(20\d{2})",
        "current_version": "2017",
    },
    "nist-csf": {
        "name": "NIST Cybersecurity Framework",
        "url": "https://www.nist.gov/cyberframework",
        "version_pattern": r"\bcsf\s*v?(\d+\.\d+(?:\.\d+)?)",
        "current_version": "2.0",
    },
    "pci-dss": {
        "name": "PCI Data Security Standard",
        "url": "https://www.pcisecuritystandards.org/document_library/",
        "version_pattern": r"pci\s*dss\s*v?(\d+\.\d+(?:\.\d+)?)",
        "current_version": "4.0",
    },
    "hipaa": {
        "name": "HIPAA Security Rule",
        "url": "https://www.hhs.gov/hipaa/for-professionals/security/index.html",
        # The Security Rule is not versioned; only a content change is meaningful.
        "version_pattern": "",
        "current_version": "current",
    },
}


class _TextExtractor(HTMLParser):
    """Visible text only. Replaces the BeautifulSoup dependency."""

    SKIP = frozenset({"script", "style", "noscript", "head", "meta", "link"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skipping += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            text = data.strip()
            if text:
                self.chunks.append(text)

    @property
    def text(self) -> str:
        return " ".join(self.chunks)


def visible_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text


def fingerprint(text: str) -> str:
    """Digest of the normalized visible text.

    Whitespace and case are normalized so a re-flow or a copy-edit of casing
    does not read as a revision.
    """
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)) or (0,)


def newer_versions(text: str, pattern: str, current: str) -> list[str]:
    """Version tokens on the page that are higher than the tracked version."""
    if not pattern or current == "current":
        return []
    found = {match.group(1) for match in re.finditer(pattern, text.lower())}
    baseline = _version_tuple(current)
    return sorted(
        (v for v in found if _version_tuple(v) > baseline),
        key=_version_tuple,
        reverse=True,
    )


@dataclass
class CheckResult:
    """The outcome of checking one framework."""

    framework_id: str
    name: str
    checked_at: str = field(default_factory=lambda: iso(utc_now()))
    status: str = "unchanged"  # unchanged | content_changed | version_detected | unchecked
    current_version: str = ""
    detected_versions: list[str] = field(default_factory=list)
    fingerprint: str = ""
    previous_fingerprint: str = ""
    detail: str = ""
    error: str = ""

    @property
    def update_detected(self) -> bool:
        return self.status in ("content_changed", "version_detected")

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework_id": self.framework_id,
            "name": self.name,
            "checked_at": self.checked_at,
            "status": self.status,
            "update_detected": self.update_detected,
            "current_version": self.current_version,
            "detected_versions": list(self.detected_versions),
            "fingerprint": self.fingerprint,
            "previous_fingerprint": self.previous_fingerprint,
            "detail": self.detail,
            "error": self.error,
        }


def _fetch(url: str) -> tuple[str, str]:
    """Fetch a page. Returns (html, error); one of the two is always empty."""
    try:
        import requests  # noqa: PLC0415 — optional dependency
    except ImportError:
        return "", "HTTP support is not installed (requests)"

    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text, ""
    except Exception as exc:  # noqa: BLE001 — a source being down is not a build failure
        return "", f"{type(exc).__name__}: {exc}"


def check_framework(
    framework_id: str, config: dict[str, Any], previous: dict[str, str]
) -> CheckResult:
    """Check one framework against its official source."""
    result = CheckResult(
        framework_id=framework_id,
        name=config["name"],
        current_version=str(config.get("current_version", "")),
        previous_fingerprint=previous.get(framework_id, ""),
    )

    html, error = _fetch(config["url"])
    if error:
        result.status = "unchecked"
        result.error = error
        result.detail = "The source could not be read; the tracked version is unchanged."
        return result

    text = visible_text(html)
    result.fingerprint = fingerprint(text)
    result.detected_versions = newer_versions(
        text, str(config.get("version_pattern", "")), result.current_version
    )

    if result.detected_versions:
        result.status = "version_detected"
        result.detail = (
            f"The source advertises {', '.join(result.detected_versions)} while this "
            f"repository tracks {result.current_version}. Review the published document "
            f"and update the control set."
        )
    elif result.previous_fingerprint and result.previous_fingerprint != result.fingerprint:
        result.status = "content_changed"
        result.detail = (
            "The source page changed since the last check with no new version number. "
            "Usually an editorial change; review before updating the control set."
        )
    elif not result.previous_fingerprint:
        result.status = "unchanged"
        result.detail = "First check for this source; the fingerprint is now recorded."
    else:
        result.detail = "No change since the last check."

    return result


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in (document.get("fingerprints") or {}).items()}


def save_state(path: Path, results: list[CheckResult]) -> None:
    existing = load_state(path)
    for result in results:
        if result.fingerprint:
            existing[result.framework_id] = result.fingerprint
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"updated_at": iso(utc_now()), "fingerprints": existing}, indent=2) + "\n",
        encoding="utf-8",
    )


def check_all(
    framework: str = "",
    state_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Check one framework or all of them, and report.

    `framework` accepts "" and "all" interchangeably for every framework. Both
    exist because the scheduled trigger passes nothing while a workflow_dispatch
    choice option cannot be an empty string -- GitHub rejects the workflow file
    outright if it is.
    """
    selected = "" if framework in ("", "all") else framework
    if selected and selected not in FRAMEWORK_SOURCES:
        raise KeyError(
            f"unknown framework {selected!r}; known: {', '.join(sorted(FRAMEWORK_SOURCES))}"
        )

    sources = {selected: FRAMEWORK_SOURCES[selected]} if selected else FRAMEWORK_SOURCES
    previous = load_state(state_path) if state_path else {}

    results = [check_framework(fid, config, previous) for fid, config in sources.items()]

    if state_path:
        save_state(state_path, results)

    changed = [r for r in results if r.update_detected]
    return {
        "checked_at": iso(now or utc_now()),
        "updates_found": bool(changed),
        "frameworks": [r.framework_id for r in changed],
        "checks": [r.to_dict() for r in results],
    }
