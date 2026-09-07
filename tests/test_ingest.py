"""The ingestion contract, extraction, and directory collection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironclad.errors import ValidationError
from ironclad.ingest.collectors import collect_from_directory, collect_from_manifest
from ironclad.ingest.contract import (
    CONTRACT_VERSION,
    build_manifest,
    load_manifest,
    manifest_from_directory,
    validate_manifest,
)
from ironclad.ingest.extractors import extract_text, supported_extensions


def valid_manifest(**overrides) -> dict:
    document = {
        "contract_version": CONTRACT_VERSION,
        "tenant_id": "acme",
        "framework": "soc2",
        "collected_at": "2026-09-05T12:00:00+00:00",
        "items": [
            {
                "name": "Access Control Policy.md",
                "uri": "/evidence/acp.md",
                "evidence_type": "Access control policy",
                "size_bytes": 1024,
                "classification": "confidential",
            }
        ],
    }
    document.update(overrides)
    return document


class TestManifestContract:
    def test_a_valid_manifest_reports_no_errors(self) -> None:
        assert validate_manifest(valid_manifest()) == []

    def test_an_unsupported_contract_version_is_refused(self) -> None:
        errors = validate_manifest(valid_manifest(contract_version="2.0"))
        assert any("not supported" in e for e in errors)

    def test_a_missing_tenant_is_refused(self) -> None:
        errors = validate_manifest(valid_manifest(tenant_id=""))
        assert any("tenant_id" in e for e in errors)

    def test_required_item_fields_are_enforced(self) -> None:
        errors = validate_manifest(valid_manifest(items=[{"evidence_type": "policy"}]))
        assert any("name is required" in e for e in errors)
        assert any("uri is required" in e for e in errors)

    def test_a_duplicate_uri_is_refused(self) -> None:
        item = valid_manifest()["items"][0]
        errors = validate_manifest(valid_manifest(items=[item, dict(item)]))
        assert any("more than once" in e for e in errors)

    def test_a_malformed_checksum_is_refused(self) -> None:
        errors = validate_manifest(
            valid_manifest(items=[{"name": "n", "uri": "u", "sha256": "nothex"}])
        )
        assert any("64 hex" in e for e in errors)

    def test_a_negative_size_is_refused(self) -> None:
        errors = validate_manifest(
            valid_manifest(items=[{"name": "n", "uri": "u", "size_bytes": -1}])
        )
        assert any("non-negative" in e for e in errors)

    def test_a_boolean_size_is_refused(self) -> None:
        # True is an int in Python; it must not slip through as a byte count.
        errors = validate_manifest(
            valid_manifest(items=[{"name": "n", "uri": "u", "size_bytes": True}])
        )
        assert any("non-negative" in e for e in errors)

    def test_an_unknown_classification_is_refused(self) -> None:
        errors = validate_manifest(
            valid_manifest(items=[{"name": "n", "uri": "u", "classification": "top-secret"}])
        )
        assert any("classification" in e for e in errors)

    def test_a_validity_window_must_run_forwards(self) -> None:
        errors = validate_manifest(
            valid_manifest(
                items=[
                    {
                        "name": "n",
                        "uri": "u",
                        "valid_from": "2026-06-01T00:00:00+00:00",
                        "valid_until": "2026-01-01T00:00:00+00:00",
                    }
                ]
            )
        )
        assert any("after valid_from" in e for e in errors)

    def test_a_bad_timestamp_is_refused(self) -> None:
        errors = validate_manifest(valid_manifest(collected_at="last tuesday"))
        assert any("ISO-8601" in e for e in errors)

    def test_an_empty_evidence_set_is_valid_when_declared(self) -> None:
        # A tenant that has submitted nothing yet is a legitimate state. It must
        # be declared, not inferred from a failed download.
        assert validate_manifest(valid_manifest(items=[])) == []

    def test_control_hints_must_be_a_list_of_ids(self) -> None:
        errors = validate_manifest(
            valid_manifest(items=[{"name": "n", "uri": "u", "control_hints": "CC6.1"}])
        )
        assert any("control_hints" in e for e in errors)

    def test_build_manifest_validates_its_own_output(self) -> None:
        with pytest.raises(ValidationError):
            build_manifest("acme", [{"name": "n"}])

    def test_loading_a_bad_manifest_raises_with_the_faults(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(valid_manifest(tenant_id="")))
        with pytest.raises(ValidationError) as caught:
            load_manifest(path)
        assert caught.value.errors


class TestExtraction:
    def test_text_formats_are_read(self, tmp_path: Path) -> None:
        path = tmp_path / "policy.md"
        path.write_text("Access control policy content")
        result = extract_text(path)
        assert result.ok
        assert "Access control" in result.text

    def test_a_missing_file_reports_rather_than_raises(self, tmp_path: Path) -> None:
        result = extract_text(tmp_path / "absent.md")
        assert not result.ok
        assert "not found" in result.error

    def test_an_unsupported_format_reports_the_format(self, tmp_path: Path) -> None:
        path = tmp_path / "evidence.dwg"
        path.write_bytes(b"\x00\x01")
        result = extract_text(path)
        assert not result.ok
        assert "unsupported" in result.error

    def test_oversized_text_is_truncated_and_says_so(self, tmp_path: Path) -> None:
        from ironclad.ingest.extractors import MAX_CHARS

        path = tmp_path / "huge.txt"
        path.write_text("a" * (MAX_CHARS + 500))
        result = extract_text(path)
        assert result.ok
        assert result.truncated
        assert len(result.text) == MAX_CHARS

    def test_a_corrupt_pdf_reports_instead_of_returning_a_placeholder(self, tmp_path: Path) -> None:
        # The original returned "[PDF: name]", which looked identical to a PDF
        # with no relevant content and hid the failure entirely.
        path = tmp_path / "broken.pdf"
        path.write_bytes(b"not a pdf at all")
        result = extract_text(path)
        assert not result.ok
        assert result.text == ""

    def test_the_supported_format_list_is_advertised(self) -> None:
        assert ".pdf" in supported_extensions()
        assert ".md" in supported_extensions()


class TestCollection:
    def test_a_directory_without_a_manifest_gets_one_derived(self, tmp_path: Path) -> None:
        (tmp_path / "Access Control Policy.md").write_text("least privilege")
        (tmp_path / "Q3 access review.csv").write_text("user,role\na,admin")

        evidence, warnings = collect_from_directory("Acme Corp", tmp_path)
        assert evidence.tenant_id == "acme-corp"
        assert len(evidence) == 2
        assert warnings == []

    def test_a_derived_manifest_checksums_every_item(self, tmp_path: Path) -> None:
        (tmp_path / "policy.md").write_text("content")
        manifest = manifest_from_directory("acme", tmp_path)
        assert all(len(item["sha256"]) == 64 for item in manifest["items"])

    def test_the_evidence_class_drives_the_freshness_window(self, tmp_path: Path) -> None:
        # An access review must age on the 90-day clock even when nothing
        # declared its type, or a year-old review would read as current.
        (tmp_path / "Q3 access review.csv").write_text("user,role")
        (tmp_path / "Security policy.md").write_text("policy")
        evidence, _ = collect_from_directory("acme", tmp_path)

        by_name = {a.name: a for a in evidence}
        review_window = by_name["Q3 access review.csv"].effective_valid_until
        policy_window = by_name["Security policy.md"].effective_valid_until
        assert review_window < policy_window

    def test_a_manifest_in_the_directory_is_preferred(self, tmp_path: Path) -> None:
        (tmp_path / "policy.md").write_text("least privilege access control")
        manifest = {
            "contract_version": CONTRACT_VERSION,
            "tenant_id": "acme",
            "items": [
                {
                    "name": "Declared Policy",
                    "uri": "policy.md",
                    "evidence_type": "Access control policy",
                    "control_hints": ["CC6.1"],
                }
            ],
        }
        (tmp_path / "evidence-manifest.json").write_text(json.dumps(manifest))

        evidence, _ = collect_from_directory("acme", tmp_path)
        assert len(evidence) == 1
        artifact = next(iter(evidence))
        assert artifact.name == "Declared Policy"
        assert artifact.control_hints == ["CC6.1"]
        assert "least privilege" in artifact.text

    def test_a_remote_uri_is_catalogued_without_text(self) -> None:
        manifest = {
            "contract_version": CONTRACT_VERSION,
            "tenant_id": "acme",
            "items": [{"name": "Remote", "uri": "gs://bucket/acme/policy.pdf"}],
        }
        evidence, warnings = collect_from_manifest(manifest)
        assert len(evidence) == 1
        assert next(iter(evidence)).text == ""
        assert warnings == []

    def test_an_unreadable_item_warns_but_is_still_catalogued(self, tmp_path: Path) -> None:
        (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
        evidence, warnings = collect_from_directory("acme", tmp_path)
        assert len(evidence) == 1
        assert any("broken.pdf" in w for w in warnings)

    def test_the_same_file_under_a_new_path_keeps_its_identity(self, tmp_path: Path) -> None:
        # Keyed on the checksum, so reorganising a folder does not present the
        # same evidence as something new.
        first = tmp_path / "a"
        second = tmp_path / "b"
        first.mkdir()
        second.mkdir()
        (first / "policy.md").write_text("identical content")
        (second / "renamed.md").write_text("identical content")

        one, _ = collect_from_directory("acme", first)
        two, _ = collect_from_directory("acme", second)
        assert next(iter(one)).artifact_id == next(iter(two)).artifact_id
