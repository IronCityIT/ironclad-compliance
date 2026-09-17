"""The ingestion contract, extraction, and directory collection."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ironclad.errors import ValidationError
from ironclad.ingest.collectors import collect_from_directory, collect_from_manifest
from ironclad.ingest.contract import (
    CONTRACT_VERSION,
    VALID_CLASSIFICATIONS,
    build_manifest,
    load_manifest,
    manifest_from_directory,
    validate_manifest,
)
from ironclad.ingest.extractors import extract_text, supported_extensions
from ironclad.model.evidence import DEFAULT_VALIDITY_DAYS, VALIDITY_DAYS

REPO_ROOT = Path(__file__).resolve().parents[1]


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

    def test_hidden_and_resource_fork_files_are_skipped_and_said(self, tmp_path: Path) -> None:
        # A client's zip arrives with .DS_Store, a .git directory and the
        # __MACOSX resource forks. Each used to be an evidence item — counted
        # on the report, and reported as unreadable when it could not be read.
        (tmp_path / "policy.md").write_text("least privilege access control")
        (tmp_path / ".DS_Store").write_bytes(b"\x00\x01")
        (tmp_path / ".git" / "objects").mkdir(parents=True)
        (tmp_path / ".git" / "objects" / "ab").write_bytes(b"x")
        (tmp_path / "__MACOSX").mkdir()
        (tmp_path / "__MACOSX" / "._policy.pdf").write_bytes(b"\x00\x05\x16\x07")

        evidence, warnings = collect_from_directory("acme", tmp_path)
        assert [a.name for a in evidence] == ["policy.md"]
        assert len(warnings) == 1
        assert "3 hidden or resource-fork file(s)" in warnings[0]
        assert ".DS_Store" in warnings[0] and "__MACOSX/._policy.pdf" in warnings[0]

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


class TestACopyIsNotCorroboration:
    """The corroboration bar asks for two independent items. A copy of the
    same document under a second name was counted as the second: the contract
    said the checksum was its identity, and the set appended it anyway."""

    def test_a_byte_identical_copy_is_counted_once_and_named(self, tmp_path: Path) -> None:
        import os
        import time

        original = tmp_path / "access-control-policy.md"
        original.write_text("least privilege access control review")
        copy = tmp_path / "access-control-policy (copy).md"
        copy.write_text("least privilege access control review")
        then = time.time() - 3600
        os.utime(original, (then, then))  # the original is the older file

        evidence, warnings = collect_from_directory("acme", tmp_path)
        assert [a.name for a in evidence] == ["access-control-policy.md"]
        assert warnings == [
            "access-control-policy (copy).md: byte-identical to access-control-policy.md; "
            "counted once"
        ]

    def test_the_same_text_under_a_different_byte_layout_is_counted_once(
        self, tmp_path: Path
    ) -> None:
        # One byte appended, a CRLF, a change of case: a different checksum,
        # the same document.
        import os
        import time

        original = tmp_path / "policy.md"
        original.write_text("Least privilege\naccess control review\n")
        copy = tmp_path / "policy-final-v2.md"
        copy.write_text("least  privilege\r\naccess control review\r\n\n")
        then = time.time() - 3600
        os.utime(original, (then, then))

        evidence, warnings = collect_from_directory("acme", tmp_path)
        assert [a.name for a in evidence] == ["policy.md"]
        assert warnings == ["policy-final-v2.md: same content as policy.md; counted once"]

    def test_the_earlier_submission_is_the_one_kept_whatever_sorts_first(
        self, tmp_path: Path
    ) -> None:
        manifest = {
            "contract_version": CONTRACT_VERSION,
            "tenant_id": "acme",
            "items": [
                {
                    "name": "later copy",
                    "uri": "policy-copy.md",
                    "collected_at": "2026-09-01T00:00:00+00:00",
                    "control_hints": ["CC6.2"],
                },
                {
                    "name": "original",
                    "uri": "policy.md",
                    "collected_at": "2026-01-01T00:00:00+00:00",
                    "control_hints": ["CC6.1"],
                },
            ],
        }
        (tmp_path / "policy.md").write_text("least privilege")
        (tmp_path / "policy-copy.md").write_text("least privilege")
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))

        evidence, warnings = collect_from_directory("acme", tmp_path)
        kept = next(iter(evidence))
        assert kept.name == "original"
        # and the operator's asserted links ride with the document, not the copy
        assert kept.control_hints == ["CC6.1", "CC6.2"]
        # no sha256 declared, so identity comes from the URI and the match is
        # on content rather than on bytes
        assert warnings == ["later copy: same content as original; counted once"]

    def test_two_different_documents_are_two(self, tmp_path: Path) -> None:
        (tmp_path / "policy.md").write_text("least privilege access control")
        (tmp_path / "review.md").write_text("quarterly user access review completed")
        evidence, warnings = collect_from_directory("acme", tmp_path)
        assert len(evidence) == 2
        assert warnings == []

    def test_a_copy_does_not_move_the_verdict(self, tmp_path: Path) -> None:
        # The assessment-level fact: readiness and every evidence_count are the
        # same with and without the copy.
        from ironclad.engine import run_assessment

        one = tmp_path / "one"
        two = tmp_path / "two"
        for d in (one, two):
            d.mkdir()
            (d / "access-control-policy.md").write_text(
                "Access control policy. Least privilege, role definitions, "
                "user access review, separation of duties."
            )
        (two / "access-control-policy (1).md").write_text(
            "Access control policy. Least privilege, role definitions, "
            "user access review, separation of duties.\n"
        )

        def counts(directory: Path) -> dict[str, tuple[str, int]]:
            evidence, _ = collect_from_directory("acme", directory)
            result = run_assessment("acme", "soc2", evidence, group="standard")
            return {
                v.control_id: (str(v.status), len(v.evidence_links))
                for v in result.assessment.controls
            }

        assert counts(one) == counts(two)


class TestTheEvidenceDirectoryIsABoundary:
    """A tenant's manifest is tenant-supplied, and so is every URI in it.

    Found by writing one: `../other/policy.txt` and `/etc/passwd` were both
    read, matched and linked to the tenant's controls, with the path recorded
    in their evidence inventory. Staging confines the prefix a run may read;
    nothing confined what a manifest inside that prefix could point at.
    """

    def _manifest(self, tmp_path: Path, *uris: str) -> None:
        document = {
            "contract_version": CONTRACT_VERSION,
            "tenant_id": "acme",
            "items": [{"name": f"item-{i}", "uri": uri} for i, uri in enumerate(uris)],
        }
        (tmp_path / "manifest.json").write_text(json.dumps(document))

    def test_a_relative_uri_that_climbs_out_is_refused_and_named(self, tmp_path: Path) -> None:
        outside = tmp_path / "other"
        outside.mkdir()
        (outside / "beta-policy.txt").write_text("least privilege access control")
        evidence_dir = tmp_path / "acme"
        evidence_dir.mkdir()
        (evidence_dir / "own.txt").write_text("code of conduct")
        self._manifest(evidence_dir, "own.txt", "../other/beta-policy.txt")

        with pytest.raises(ValidationError) as caught:
            collect_from_directory("acme", evidence_dir)
        assert "outside the evidence directory" in str(caught.value)
        assert any("beta-policy.txt" in e for e in caught.value.errors)
        assert not any("own.txt" in e for e in caught.value.errors)

    def test_an_absolute_uri_elsewhere_is_refused_even_if_it_exists(self, tmp_path: Path) -> None:
        evidence_dir = tmp_path / "acme"
        evidence_dir.mkdir()
        self._manifest(evidence_dir, "/etc/passwd", "/nonexistent/but/outside.txt")

        with pytest.raises(ValidationError) as caught:
            collect_from_directory("acme", evidence_dir)
        assert len(caught.value.errors) == 2

    def test_an_absolute_uri_inside_the_directory_is_fine(self, tmp_path: Path) -> None:
        # The derived manifest writes resolved absolute paths itself; a
        # declared one that lands inside the directory is the same thing.
        (tmp_path / "policy.md").write_text("least privilege access control")
        self._manifest(tmp_path, str((tmp_path / "policy.md").resolve()))

        evidence, warnings = collect_from_directory("acme", tmp_path)
        assert len(evidence) == 1
        assert "least privilege" in next(iter(evidence)).text
        assert warnings == []

    def test_a_symlink_that_resolves_out_is_judged_by_where_it_lands(self, tmp_path: Path) -> None:
        outside = tmp_path / "other"
        outside.mkdir()
        (outside / "secret.txt").write_text("not this tenant's")
        evidence_dir = tmp_path / "acme"
        evidence_dir.mkdir()
        (evidence_dir / "link.txt").symlink_to(outside / "secret.txt")
        self._manifest(evidence_dir, "link.txt")

        with pytest.raises(ValidationError) as caught:
            collect_from_directory("acme", evidence_dir)
        assert any("link.txt" in e for e in caught.value.errors)

    def test_a_remote_uri_is_not_a_local_path_and_is_not_judged(self, tmp_path: Path) -> None:
        self._manifest(tmp_path, "gs://bucket/acme/policy.pdf", "https://example.test/x.pdf")
        evidence, _ = collect_from_directory("acme", tmp_path)
        assert len(evidence) == 2

    def test_without_a_base_dir_nothing_can_be_confined(self, tmp_path: Path) -> None:
        # The API caller who passes no root has chosen not to have one. The
        # CLI and the workflow always pass the evidence directory.
        (tmp_path / "policy.md").write_text("content")
        manifest = {
            "contract_version": CONTRACT_VERSION,
            "tenant_id": "acme",
            "items": [{"name": "p", "uri": str(tmp_path / "policy.md")}],
        }
        evidence, _ = collect_from_manifest(manifest)
        assert next(iter(evidence)).text == "content"

    def test_a_derived_manifest_refuses_a_symlinked_file(self, tmp_path: Path) -> None:
        outside = tmp_path / "other"
        outside.mkdir()
        (outside / "secret.txt").write_text("not this tenant's")
        evidence_dir = tmp_path / "acme"
        evidence_dir.mkdir()
        (evidence_dir / "own.txt").write_text("code of conduct")
        (evidence_dir / "secret.txt").symlink_to(outside / "secret.txt")

        with pytest.raises(ValidationError) as caught:
            collect_from_directory("acme", evidence_dir)
        assert "symbolic links" in str(caught.value)
        assert caught.value.errors == ["symbolic link: secret.txt"]

    def test_a_derived_manifest_refuses_a_symlinked_directory(self, tmp_path: Path) -> None:
        # rglob does not descend into a directory link, so without the check
        # the link would be neither read nor mentioned.
        evidence_dir = tmp_path / "acme"
        (evidence_dir / "nested").mkdir(parents=True)
        (evidence_dir / "nested" / "up").symlink_to(tmp_path)
        (evidence_dir / "loop").symlink_to(evidence_dir)

        with pytest.raises(ValidationError) as caught:
            collect_from_directory("acme", evidence_dir)
        assert caught.value.errors == ["symbolic link: loop", "symbolic link: nested/up"]

    def test_the_cli_refuses_with_the_item_named_and_writes_nothing(
        self, tmp_path: Path, capsys
    ) -> None:
        from ironclad.cli import main

        evidence_dir = tmp_path / "acme"
        evidence_dir.mkdir()
        (evidence_dir / "own.txt").write_text("code of conduct")
        self._manifest(evidence_dir, "own.txt", "/etc/passwd")
        out = tmp_path / "out"

        code = main(
            [
                "assess",
                "--client",
                "acme",
                "--framework",
                "soc2",
                "--evidence-dir",
                str(evidence_dir),
                "--out",
                str(out),
            ]
        )
        assert code == 2
        assert "/etc/passwd" in capsys.readouterr().err
        assert not out.exists()


class TestTheContractDocumentMatchesTheEngine:
    """The document a client is asked to submit evidence against.

    `docs/ingestion-contract.md` is the agreement: it tells whoever collects a
    client's evidence what shape to send and how long each class of document
    counts for. A contract that has drifted from the implementation is the same
    defect as a wrapper that has — it states something the engine does not do,
    and the person who finds out is the client whose control read as a gap.

    Checked rather than read. The freshness table was already one class short:
    a bare `scan` is a 30-day class in the code and the document did not say so,
    so a client submitting `Q3 scan.pdf` got a 30-day clock the contract never
    mentioned.
    """

    DOC = REPO_ROOT / "docs" / "ingestion-contract.md"

    def _documented_windows(self) -> dict[str, int]:
        text = self.DOC.read_text(encoding="utf-8")
        windows: dict[str, int] = {}
        for classes, days in re.findall(r"^\| ([^|]+?) \| (\d+) days \|$", text, re.M):
            for name in (c.strip() for c in classes.split(",")):
                windows[name] = int(days)
        return windows

    def test_every_evidence_class_is_documented(self) -> None:
        documented = self._documented_windows()
        assert set(VALIDITY_DAYS) <= set(documented), (
            f"undocumented evidence classes: {set(VALIDITY_DAYS) - set(documented)}"
        )

    def test_no_class_is_documented_with_the_wrong_window(self) -> None:
        documented = self._documented_windows()
        wrong = {
            name: (documented[name], VALIDITY_DAYS[name])
            for name in set(documented) & set(VALIDITY_DAYS)
            if documented[name] != VALIDITY_DAYS[name]
        }
        assert not wrong, f"documented window != engine window: {wrong}"

    def test_the_default_window_is_documented(self) -> None:
        assert self._documented_windows().get("anything else") == DEFAULT_VALIDITY_DAYS

    def test_no_class_is_documented_that_the_engine_does_not_have(self) -> None:
        # A client reading the contract must not plan around a class the engine
        # will not recognise; it would silently take the default window.
        documented = set(self._documented_windows()) - {"anything else"}
        assert documented <= set(VALIDITY_DAYS), (
            f"documented but not in the engine: {documented - set(VALIDITY_DAYS)}"
        )

    def test_the_documented_contract_version_is_the_supported_one(self) -> None:
        text = self.DOC.read_text(encoding="utf-8")
        assert f'must be `"{CONTRACT_VERSION}"`' in text

    def test_the_documented_classifications_are_the_accepted_ones(self) -> None:
        text = self.DOC.read_text(encoding="utf-8")
        for classification in VALID_CLASSIFICATIONS:
            assert f"`{classification}`" in text, classification
