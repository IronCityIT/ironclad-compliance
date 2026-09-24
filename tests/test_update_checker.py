"""The quarterly framework update checker.

The only automation in this repository that runs unattended, on a schedule,
against pages nobody controls, and opens a pull request from what it finds. A
defect here is a defect nobody is watching when it happens — PR #3 on `main` is
one sitting open since August.

Two defects this file exists for, both found by measuring the real sources
rather than by reading the code:

**The extractor returned nothing for three of the four sources.** `meta` and
`link` were in the skip set. Both are void — `<meta charset="utf-8">` has no
closing tag — so the skip counter went up on the first one in `<head>` and never
came back down, and every text node after it was discarded. The checker had been
fingerprinting the empty string, comparing nothing to nothing, and reporting
"unchanged" with confidence. It could not have detected a change to SOC 2, PCI
DSS or HIPAA, ever. NIST worked only because that page self-closes its meta
tags, which makes HTMLParser synthesise the end tag.

**An empty response read as a content change.** A WAF interstitial, a CDN error
or an empty 200 produced a fingerprint of nothing, which differs from the stored
one, so the checker reported a change *and* recorded the digest of nothing as
the new baseline — poisoning it, so the next run compared the real page against
nothing and reported a change again. Two false pull requests from one blip.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ironclad.frameworks import updates
from ironclad.frameworks.updates import (
    FRAMEWORK_SOURCES,
    MIN_VISIBLE_CHARS,
    check_all,
    check_framework,
    fingerprint,
    load_state,
    save_state,
    visible_text,
)

# Long enough to clear the floor, so these fixtures test the comparison rather
# than the guard.
FILLER = "The Trust Services Criteria describe the controls in scope. " * 20


def page(body: str) -> str:
    """A page in the shape that broke the extractor: HTML5, unclosed meta."""
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<link rel="stylesheet" href="/s.css"><title>Ignored</title></head>'
        f"<body><div id='root'>{body}</div></body></html>"
    )


@pytest.fixture
def fetches(monkeypatch):
    """Replace the network with a page of the test's choosing."""

    def serve(html: str, error: str = "") -> None:
        monkeypatch.setattr(updates, "_fetch", lambda url: (html, error))

    return serve


class TestTheExtractorReadsRealPages:
    def test_html5_void_tags_do_not_swallow_the_document(self) -> None:
        # The regression. Every real source but NIST is written this way.
        text = visible_text(page("Trust Services Criteria 2017 remain current."))
        assert "Trust Services Criteria 2017 remain current." in text

    def test_a_self_closed_meta_still_works(self) -> None:
        # XHTML style, which is why the bug looked like it worked on NIST.
        html = '<html><head><meta charset="utf-8" /></head><body>Visible.</body></html>'
        assert "Visible." in visible_text(html)

    def test_many_void_tags_do_not_accumulate(self) -> None:
        head = '<meta charset="utf-8">' + '<link rel="x" href="y">' * 20
        html = f"<html><head>{head}</head><body>Still visible.</body></html>"
        assert "Still visible." in visible_text(html)

    def test_script_and_style_are_still_skipped(self) -> None:
        html = (
            "<html><body><script>var secret = 1;</script>"
            "<style>.a{color:red}</style>Real text.</body></html>"
        )
        text = visible_text(html)
        assert "Real text." in text
        assert "secret" not in text
        assert "color:red" not in text

    def test_the_title_is_not_treated_as_page_content(self) -> None:
        # `head` has an end tag, so it can stay in the skip set.
        html = "<html><head><title>Page title</title></head><body>Body text.</body></html>"
        text = visible_text(html)
        assert "Body text." in text
        assert "Page title" not in text

    def test_a_noscript_notice_is_not_page_content(self) -> None:
        html = page("<noscript>You need to enable JavaScript.</noscript>Real content here.")
        text = visible_text(html)
        assert "Real content here." in text
        assert "enable JavaScript" not in text


class TestAnUnreadableResponseIsNotAChange:
    @pytest.mark.parametrize(
        "html",
        [
            "",
            "<html><body>Access denied. Ref 1234</body></html>",
            "<html><head><title>502</title></head><body><h1>502 Bad Gateway</h1></body></html>",
            "<html><body><div id='root'></div><script>window.x=1</script></body></html>",
        ],
    )
    def test_a_short_or_empty_page_is_unchecked(self, fetches, html: str) -> None:
        fetches(html)
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {"soc2": "recorded-digest"})
        assert result.status == "unchecked"
        assert not result.update_detected

    def test_it_does_not_poison_the_recorded_fingerprint(self, fetches, tmp_path: Path) -> None:
        # The damage that outlasts the blip: a baseline of nothing makes the
        # next run report the real page as changed.
        state = tmp_path / "state.json"
        save_state(state, [check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {})])  # unchecked
        fetches("")
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {"soc2": "recorded-digest"})
        assert result.fingerprint == ""
        save_state(state, [result])
        assert load_state(state).get("soc2", "") != fingerprint("")

    def test_the_floor_is_clear_of_a_real_page(self, fetches) -> None:
        # Set against the real sources, which yield 5,368-9,139 characters.
        fetches(page(FILLER))
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {})
        assert len(visible_text(page(FILLER)).strip()) > MIN_VISIBLE_CHARS
        assert result.status != "unchecked"

    def test_a_transport_failure_is_unchecked_too(self, fetches) -> None:
        fetches("", "ConnectionError: refused")
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {"soc2": "recorded"})
        assert result.status == "unchecked"
        assert "refused" in result.error
        assert result.fingerprint == ""


class TestWhatCountsAsAChange:
    def test_a_first_check_records_without_claiming_a_change(self, fetches) -> None:
        fetches(page(FILLER))
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {})
        assert result.status == "unchanged"
        assert not result.update_detected
        assert result.fingerprint

    def test_the_same_page_twice_is_unchanged(self, fetches) -> None:
        fetches(page(FILLER))
        first = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {})
        second = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {"soc2": first.fingerprint})
        assert second.status == "unchanged"
        assert not second.update_detected

    def test_edited_wording_is_a_content_change(self, fetches) -> None:
        fetches(page(FILLER))
        before = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {}).fingerprint
        fetches(page(FILLER + " An additional paragraph was published."))
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {"soc2": before})
        assert result.status == "content_changed"
        assert result.update_detected

    def test_a_newer_version_outranks_a_content_change(self, fetches) -> None:
        fetches(page(FILLER + " Trust services criteria 2029 published."))
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {"soc2": "an-old-digest"})
        assert result.status == "version_detected"
        assert "2029" in " ".join(result.detected_versions)
        assert result.current_version in result.detail

    def test_the_tracked_version_on_the_page_is_not_a_change(self, fetches) -> None:
        # The old checker's whole failure: a word that is always there.
        fetches(page(FILLER + " These are the latest trust services criteria 2017."))
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {})
        assert result.detected_versions == []
        assert not result.update_detected


class TestCheckingEverything:
    def test_all_and_the_empty_string_mean_the_same(self, fetches) -> None:
        # The scheduled trigger passes nothing; a workflow_dispatch choice
        # cannot be an empty string, so the workflow passes "all".
        fetches(page(FILLER))
        assert [c["framework_id"] for c in check_all("")["checks"]] == [
            c["framework_id"] for c in check_all("all")["checks"]
        ]

    def test_every_shipped_framework_is_checked(self, fetches) -> None:
        fetches(page(FILLER))
        checked = {c["framework_id"] for c in check_all("all")["checks"]}
        assert checked == set(FRAMEWORK_SOURCES)

    def test_one_framework_can_be_checked_alone(self, fetches) -> None:
        fetches(page(FILLER))
        report = check_all("hipaa")
        assert [c["framework_id"] for c in report["checks"]] == ["hipaa"]

    def test_an_unknown_framework_names_the_known_ones(self) -> None:
        with pytest.raises(KeyError) as raised:
            check_all("iso-27001")
        assert "soc2" in str(raised.value)

    def test_nothing_changed_reports_nothing_changed(self, fetches, tmp_path: Path) -> None:
        fetches(page(FILLER))
        state = tmp_path / "state.json"
        check_all("all", state_path=state)
        report = check_all("all", state_path=state)
        assert report["updates_found"] is False
        assert report["frameworks"] == []

    def test_a_change_is_named_by_framework(self, fetches, tmp_path: Path) -> None:
        fetches(page(FILLER))
        state = tmp_path / "state.json"
        check_all("all", state_path=state)
        fetches(page(FILLER + " Newly published guidance."))
        report = check_all("all", state_path=state)
        assert report["updates_found"] is True
        assert set(report["frameworks"]) == set(FRAMEWORK_SOURCES)

    def test_checking_one_framework_preserves_the_others_baselines(
        self, fetches, tmp_path: Path
    ) -> None:
        # A partial run that wiped the rest would make every other framework
        # report "first check" next time, losing the ability to detect a change.
        fetches(page(FILLER))
        state = tmp_path / "state.json"
        check_all("all", state_path=state)
        before = load_state(state)
        assert len(before) == len(FRAMEWORK_SOURCES)

        check_all("hipaa", state_path=state)
        after = load_state(state)
        assert set(after) == set(before)
        for framework_id in before:
            if framework_id != "hipaa":
                assert after[framework_id] == before[framework_id]

    def test_a_failed_fetch_leaves_every_baseline_alone(self, fetches, tmp_path: Path) -> None:
        fetches(page(FILLER))
        state = tmp_path / "state.json"
        check_all("all", state_path=state)
        before = load_state(state)

        fetches("", "ConnectionError: the source is down")
        report = check_all("all", state_path=state)
        assert report["updates_found"] is False
        assert load_state(state) == before

    def test_the_report_is_json_serialisable(self, fetches, tmp_path: Path) -> None:
        # It is written to a file and read back by jq in the workflow.
        fetches(page(FILLER))
        report: dict[str, Any] = check_all("all", state_path=tmp_path / "state.json")
        assert json.loads(json.dumps(report)) == report
        for check in report["checks"]:
            assert set(check) >= {"framework_id", "status", "update_detected", "detail"}
