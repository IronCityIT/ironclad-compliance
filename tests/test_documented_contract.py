"""The field tables and examples in `docs/ingestion-contract.md` are the validators.

The contract is what a client's evidence collector and a client's compliance
lead write files against. `test_ingest.py` already holds its freshness windows,
version and classifications to the engine. Nothing held the rest: which fields
are required, which are read at all, what the examples look like to the
validator, and the limits the prose quotes. The exception section had already
drifted: it listed five statuses where the loader accepts six, and it never
said that `justification` and `requested_by` are required.

Each table row is checked by behaviour, not by reading code: a field marked
required is removed from the document's own example and the validator must name
it; a field marked optional is removed and the file must still validate and
load. Every field a validator reads must have a row.

Checking the example also exposed a defect. An acceptance with no
`requested_at` was dated from the moment the file was read, so the example's own
acceptance would have made the whole policy refuse to load once it had run out,
and an approval running 20 months loaded because the 365-day cap was measured
from today. The request date now falls back to `approved_at`.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from ironclad import policy
from ironclad.errors import ExceptionWorkflowError
from ironclad.ingest import contract, extractors
from ironclad.model.exception import MAX_EXCEPTION_DAYS, ExceptionStatus
from ironclad.modules import scope_review

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "ingestion-contract.md"

_ROW = re.compile(r"^\| `(\w+)` \| ([^|]+?) \|", re.M)
_JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.S)
_READ = re.compile(r"""\b(?:document|item|raw)(?:\.get\(|\[)\s*"(\w+)\"""")
_FOR_APPROVED = "for `approved` and `expired`"


def _text() -> str:
    return DOC.read_text(encoding="utf-8").replace("\r\n", "\n")


def _section(heading: str) -> str:
    text = _text()
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n#", start + len(heading) + 5)
    return text[start : end if end != -1 else len(text)]


def _table(heading: str) -> dict[str, str]:
    return {name: required.strip() for name, required in _ROW.findall(_section(heading))}


def _examples() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, tenant_policy = (json.loads(block) for block in _JSON_BLOCK.findall(_text()))
    return manifest, tenant_policy


def _example_manifest() -> dict[str, Any]:
    # The document writes the digest as an elision rather than 64 characters.
    manifest = _examples()[0]
    manifest["items"][0]["sha256"] = "0" * 64
    return manifest


def _reads(source: str) -> set[str]:
    return set(_READ.findall(source))


@pytest.fixture
def within_the_example(monkeypatch: pytest.MonkeyPatch) -> None:
    # The example acceptance runs for three months. "Now" is pinned inside it so
    # a check that removes its dates does not depend on the day the suite runs.
    approved = datetime.fromisoformat(_examples()[1]["exceptions"][0]["approved_at"])
    monkeypatch.setattr(policy, "utc_now", lambda: approved + timedelta(days=1))


class TestTheManifestTables:
    def test_the_example_is_valid_but_for_its_elided_digest(self) -> None:
        manifest = _examples()[0]
        faults = contract.validate_manifest(manifest)
        assert faults == ["items[0].sha256 must be 64 hex characters"]
        assert contract.validate_manifest(_example_manifest()) == []

    def test_the_example_shows_every_field_in_the_tables(self) -> None:
        manifest = _example_manifest()
        assert set(manifest) == set(_table("Document fields"))
        assert set(manifest["items"][0]) == set(_table("Item fields"))

    def test_every_field_the_validator_reads_has_a_row(self) -> None:
        documented = set(_table("Document fields")) | set(_table("Item fields"))
        read = _reads(inspect.getsource(contract.validate_manifest))
        assert read, "the read pattern found nothing; the check would be empty"
        assert read <= documented, f"read but not documented: {read - documented}"

    @pytest.mark.parametrize("field", sorted(_table("Document fields")))
    def test_a_document_field_is_required_exactly_when_the_table_says(self, field: str) -> None:
        manifest = _example_manifest()
        del manifest[field]
        faults = contract.validate_manifest(manifest)
        if _table("Document fields")[field] == "yes":
            assert any(field in fault for fault in faults), faults
        else:
            assert faults == []

    @pytest.mark.parametrize("field", sorted(_table("Item fields")))
    def test_an_item_field_is_required_exactly_when_the_table_says(self, field: str) -> None:
        manifest = _example_manifest()
        del manifest["items"][0][field]
        faults = contract.validate_manifest(manifest)
        if _table("Item fields")[field] == "yes":
            assert faults == [f"items[0].{field} is required"]
        else:
            assert faults == []


class TestThePolicyTables:
    def test_the_example_validates_and_loads(self, within_the_example: None) -> None:
        document = _examples()[1]
        assert policy.validate_policy(document) == []
        loaded = policy.policy_from_document(document)
        assert [str(e.status) for e in loaded.exceptions] == ["approved"]
        assert [e.control_id for e in loaded.exclusions] == ["CC6.4"]

    def test_the_example_reads_no_top_level_field_it_does_not_show(self) -> None:
        read = _reads(inspect.getsource(policy.validate_policy))
        top_level = {"policy_version", "tenant_id", "scope_exclusions", "exceptions", "owners"}
        assert set(_examples()[1]) == top_level
        assert read <= top_level | set(_table("Scope exclusions")) | set(_table("Exceptions"))

    def test_every_field_the_loader_reads_has_a_row(self) -> None:
        documented = set(_table("Scope exclusions")) | set(_table("Exceptions"))
        top_level = {"tenant_id", "scope_exclusions", "exceptions", "owners"}
        read = _reads(inspect.getsource(policy.policy_from_document)) - top_level
        assert read, "the read pattern found nothing; the check would be empty"
        assert read <= documented, f"read but not documented: {read - documented}"

    @pytest.mark.parametrize("field", sorted(_table("Scope exclusions")))
    def test_an_exclusion_field_is_required_exactly_when_the_table_says(
        self, field: str, within_the_example: None
    ) -> None:
        document = _examples()[1]
        del document["scope_exclusions"][0][field]
        faults = policy.validate_policy(document)
        if _table("Scope exclusions")[field] == "yes":
            assert any(f".{field} is required" in fault for fault in faults), faults
        else:
            assert faults == []
            policy.policy_from_document(document)

    @pytest.mark.parametrize("field", sorted(_table("Exceptions")))
    @pytest.mark.parametrize("status", [s.value for s in ExceptionStatus])
    def test_an_exception_field_is_required_exactly_when_the_table_says(
        self, field: str, status: str, within_the_example: None
    ) -> None:
        example = _examples()[1]
        acceptance = example["exceptions"][0]
        acceptance["status"] = status
        acceptance.pop(field, None)
        document = example
        faults = policy.validate_policy(document)
        rule = _table("Exceptions")[field]
        if field == "status" and rule != "yes":
            # absent means approved, and the example carries what that needs
            assert faults == []
            assert str(policy.policy_from_document(document).exceptions[0].status) == "approved"
        elif rule == "yes" or (rule == _FOR_APPROVED and status in ("approved", "expired")):
            assert any(f".{field} is required" in fault for fault in faults), faults
        else:
            assert rule in ("no", _FOR_APPROVED), rule
            assert faults == []
            assert str(policy.policy_from_document(document).exceptions[0].status) == status

    def test_the_documented_statuses_are_the_workflow_s(self) -> None:
        sentence = re.search(r"`status` may be (.*?)\.", _section("Exceptions"), re.S)
        assert sentence, "the status sentence is gone"
        assert set(re.findall(r"`(\w+)`", sentence.group(1))) == {s.value for s in ExceptionStatus}


class TestTheRequestDate:
    """Measured from the request, not from the day the file is read."""

    @staticmethod
    def _acceptance(**dates: str) -> dict[str, Any]:
        document = _examples()[1]
        acceptance = document["exceptions"][0]
        acceptance.pop("approved_at")
        acceptance.update(dates)
        return document

    def test_the_example_still_loads_after_its_acceptance_has_run_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        document = _examples()[1]
        expires = datetime.fromisoformat(document["exceptions"][0]["expires_at"])
        later = expires + timedelta(days=60)
        monkeypatch.setattr(policy, "utc_now", lambda: later)
        acceptance = policy.policy_from_document(document).exceptions[0]
        assert str(acceptance.status) == "approved"
        assert not acceptance.is_active(as_of=later)
        assert acceptance.requested_at == datetime.fromisoformat(
            document["exceptions"][0]["approved_at"]
        )

    def test_the_cap_is_measured_from_the_approval_when_that_is_all_there_is(self) -> None:
        document = self._acceptance(
            approved_at="2025-10-01T00:00:00+00:00", expires_at="2027-06-01T00:00:00+00:00"
        )
        assert policy.validate_policy(document) == []  # the schema is fine
        with pytest.raises(ExceptionWorkflowError, match=f"beyond {MAX_EXCEPTION_DAYS} days"):
            policy.policy_from_document(document)

    def test_an_explicit_request_date_still_wins(self) -> None:
        document = self._acceptance(
            requested_at="2025-09-01T00:00:00+00:00",
            approved_at="2025-09-20T00:00:00+00:00",
            expires_at="2026-08-31T00:00:00+00:00",
        )
        acceptance = policy.policy_from_document(document).exceptions[0]
        assert acceptance.requested_at == datetime(2025, 9, 1, tzinfo=timezone.utc)
        assert acceptance.approved_at == datetime(2025, 9, 20, tzinfo=timezone.utc)

    def test_the_identity_is_stable_across_reads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The id is derived from the request date; read twice, it must not move.
        ids = []
        for day in (1, 30):
            moment = datetime(2026, 9, day, tzinfo=timezone.utc)
            monkeypatch.setattr(policy, "utc_now", lambda moment=moment: moment)
            ids.append(policy.policy_from_document(_examples()[1]).exceptions[0].exception_id)
        assert ids[0] == ids[1]


class TestTheNumbersInTheProse:
    @pytest.mark.parametrize(
        "phrase, value",
        [
            ("no acceptance may run beyond {} days", MAX_EXCEPTION_DAYS),
            ("an exclusion **falling due** within {} days", scope_review.REVIEW_WARNING_DAYS),
            ("first {:,} characters of any item are matched", extractors.MAX_CHARS),
            ("would expand past {} MB", extractors.MAX_ZIP_MEMBER_BYTES // (1024 * 1024)),
            (
                "any other file\nover {} MB is not parsed",
                extractors.MAX_FILE_BYTES // (1024 * 1024),
            ),
        ],
    )
    def test_a_quoted_limit_is_the_engine_s(self, phrase: str, value: int) -> None:
        assert phrase.format(value) in _text()
