"""The CLI surface, report rendering, exports, and the update checker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironclad.cli import _StoredResult, main
from ironclad.engine import run_assessment
from ironclad.frameworks.updates import (
    FRAMEWORK_SOURCES,
    fingerprint,
    load_state,
    newer_versions,
    save_state,
    visible_text,
)
from ironclad.report.export import (
    export_audit_package,
    export_control_register_csv,
    export_json,
    export_remediation_csv,
)
from ironclad.report.render import render_html
from tests.conftest import NOW

# Names that must never appear on a client-facing surface.
TOOL_NAMES = ("zap", "nuclei", "wazuh", "prowler", "puppeteer", "openai", "anthropic", "groq")


@pytest.fixture
def result(tiny_framework, evidence):
    return run_assessment(
        tenant_id="acme",
        framework=tiny_framework,
        evidence=evidence,
        group="deep",
        as_of=NOW,
        assessment_id="acme-test-1",
    )


class TestReportRendering:
    def test_the_report_is_a_complete_document(self, result) -> None:
        html = render_html(result, "Acme Corp")
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")

    def test_the_report_names_the_client_and_the_framework(self, result) -> None:
        html = render_html(result, "Acme Corp")
        assert "Acme Corp" in html
        assert "Test Framework" in html

    def test_the_report_never_names_an_underlying_tool(self, result) -> None:
        html = render_html(result, "Acme Corp").lower()
        for name in TOOL_NAMES:
            assert name not in html, f"the report names {name}"

    def test_client_supplied_text_cannot_inject_markup(self, tiny_framework) -> None:
        from ironclad.model.evidence import EvidenceSet
        from tests.conftest import make_artifact

        evidence = EvidenceSet(tenant_id="acme")
        evidence.add(
            make_artifact(
                "<script>alert(1)</script>.md",
                "access control policy restricts logical access registers authorized users",
                evidence_type="Access control policy",
            )
        )
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            as_of=NOW,
        )
        html = render_html(result, "<img onerror=alert(1)>")
        assert "<script>alert(1)</script>" not in html
        assert "<img onerror" not in html

    def test_unavailable_commentary_is_not_presented_as_a_verdict(self, result) -> None:
        from ironclad.engine import merge_consensus

        merge_consensus(result, "")
        html = render_html(result, "Acme Corp")
        assert "Analyst commentary" not in html

    def test_a_capability_failure_is_disclosed_in_the_report(self, result) -> None:
        result.failed_modules["freshness_check"] = "RuntimeError: boom"
        html = render_html(result, "Acme Corp")
        assert "Assessment caveats" in html
        assert "freshness_check" in html


class TestExports:
    def test_the_json_export_satisfies_the_commit_gate(self, result) -> None:
        text = export_json(result)
        assert text.startswith("{")
        assert text.endswith("}\n")
        json.loads(text)

    def test_the_control_register_has_one_row_per_control(self, result) -> None:
        lines = export_control_register_csv(result).strip().splitlines()
        assert len(lines) == 1 + len(result.assessment.controls)

    def test_the_register_names_the_supporting_documents_when_evidence_is_given(
        self, result, evidence
    ) -> None:
        csv_text = export_control_register_csv(result, evidence)
        assert "Access Control Policy" in csv_text

    def test_the_remediation_export_is_in_priority_order(self, result) -> None:
        rows = export_remediation_csv(result).strip().splitlines()[1:]
        priorities = [float(row.split(",")[4]) for row in rows]
        assert priorities == sorted(priorities, reverse=True)

    def test_the_audit_package_contains_every_promised_file(
        self, result, evidence, tmp_path: Path
    ) -> None:
        written = export_audit_package(result, evidence, tmp_path / "package")
        names = {path.name for path in written}
        assert {
            "assessment.json",
            "control-register.csv",
            "remediation-plan.csv",
            "evidence-index.csv",
            "audit-trail.csv",
            "report.html",
            "package.json",
        } <= names

    def test_the_package_manifest_records_the_audit_chain_head(
        self, result, evidence, tmp_path: Path
    ) -> None:
        export_audit_package(result, evidence, tmp_path / "package")
        manifest = json.loads((tmp_path / "package" / "package.json").read_text())
        assert manifest["audit_chain_verified"] is True
        assert manifest["audit_chain_head"] == result.audit.head

    def test_the_package_states_that_it_excludes_the_evidence_itself(
        self, result, evidence, tmp_path: Path
    ) -> None:
        # Nobody should assume the evidence bytes travelled with the package.
        export_audit_package(result, evidence, tmp_path / "package")
        readme = (tmp_path / "package" / "README.txt").read_text()
        assert "DOES NOT CONTAIN" in readme

    def test_the_evidence_index_carries_checksums_not_content(
        self, result, evidence, tmp_path: Path
    ) -> None:
        export_audit_package(result, evidence, tmp_path / "package")
        index = (tmp_path / "package" / "evidence-index.csv").read_text()
        assert "sha256" in index
        # The extracted text must never leave the engine.
        assert "least privilege" not in index


class TestStoredResultRoundTrip:
    def test_a_stored_result_rehydrates_for_rendering(self, result, tmp_path: Path) -> None:
        path = tmp_path / "assessment.json"
        path.write_text(export_json(result))
        restored = _StoredResult(json.loads(path.read_text()))

        assert restored.assessment.assessment_id == result.assessment.assessment_id
        assert len(restored.assessment.controls) == len(result.assessment.controls)
        assert len(restored.plan) == len(result.plan)
        assert render_html(restored, "Acme Corp").startswith("<!DOCTYPE html>")

    def test_a_stored_result_renders_even_if_the_framework_file_is_gone(self, result) -> None:
        document = json.loads(export_json(result))
        document["framework"]["id"] = "framework-that-no-longer-exists"
        restored = _StoredResult(document)
        assert render_html(restored, "Acme Corp")


class TestCli:
    def test_list_modules_emits_the_catalog(self, capsys) -> None:
        assert main(["list-modules"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["modules"]
        assert "deep" in payload["groups"]

    def test_list_frameworks_emits_all_four(self, capsys) -> None:
        assert main(["list-frameworks"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["frameworks"]) == 4

    def test_validate_accepts_a_shipped_framework(self, capsys) -> None:
        assert main(["validate", "--framework", "soc2"]) == 0

    def test_validate_rejects_a_broken_manifest(self, tmp_path: Path, capsys) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"contract_version": "1.0", "items": []}))
        assert main(["validate", "--manifest", str(manifest)]) == 2

    def test_assess_writes_the_three_pipeline_artifacts(self, tmp_path: Path) -> None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "Access Control Policy.md").write_text(
            "Access control policy. Least privilege, role definitions, "
            "user access review, separation of duties."
        )
        out = tmp_path / "out"
        code = main(
            [
                "assess",
                "--client",
                "Acme Corp",
                "--framework",
                "soc2",
                "--evidence-dir",
                str(evidence_dir),
                "--group",
                "quick",
                "--out",
                str(out),
            ]
        )
        assert code == 0
        assert (out / "assessment.json").exists()
        assert (out / "findings.b64").exists()
        assert (out / "report.html").exists()

    def test_assess_refuses_a_missing_evidence_directory(self, tmp_path: Path) -> None:
        assert (
            main(
                [
                    "assess",
                    "--client",
                    "acme",
                    "--framework",
                    "soc2",
                    "--evidence-dir",
                    str(tmp_path / "absent"),
                    "--out",
                    str(tmp_path / "out"),
                ]
            )
            == 2
        )

    def test_an_unknown_framework_exits_with_a_message(self, tmp_path: Path, capsys) -> None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "policy.md").write_text("content")
        assert (
            main(
                [
                    "assess",
                    "--client",
                    "acme",
                    "--framework",
                    "iso-27001",
                    "--evidence-dir",
                    str(evidence_dir),
                    "--out",
                    str(tmp_path / "out"),
                ]
            )
            == 2
        )

    def test_an_unknown_capability_exits_with_a_selection_error(
        self, tmp_path: Path, capsys
    ) -> None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "policy.md").write_text("content")
        assert (
            main(
                [
                    "assess",
                    "--client",
                    "acme",
                    "--framework",
                    "soc2",
                    "--evidence-dir",
                    str(evidence_dir),
                    "--modules",
                    "nope",
                    "--out",
                    str(tmp_path / "out"),
                ]
            )
            == 2
        )
        assert "selection error" in capsys.readouterr().err

    def test_crosswalk_reports_coverage_between_two_frameworks(self, capsys) -> None:
        assert main(["crosswalk", "--from", "soc2", "--to", "hipaa"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["coverage"] > 0.5
        assert payload["mappings"]


class TestUpdateChecker:
    def test_visible_text_drops_scripts_and_styles(self) -> None:
        html = "<style>x{}</style><p>Real content</p><script>evil()</script>"
        text = visible_text(html)
        assert text == "Real content"

    def test_the_fingerprint_ignores_whitespace_and_case(self) -> None:
        # A re-flow or a copy-edit of casing is not a revision.
        assert fingerprint("PCI  DSS v4.0") == fingerprint("pci dss v4.0")

    def test_only_a_higher_version_counts(self) -> None:
        pattern = FRAMEWORK_SOURCES["pci-dss"]["version_pattern"]
        text = "PCI DSS v4.0 and PCI DSS v4.1 are published"
        assert newer_versions(text, pattern, "4.0") == ["4.1"]
        assert newer_versions(text, pattern, "4.1") == []

    def test_a_patch_release_is_detected(self) -> None:
        pattern = FRAMEWORK_SOURCES["pci-dss"]["version_pattern"]
        assert "4.0.1" in newer_versions("PCI DSS v4.0.1", pattern, "4.0")

    def test_an_unversioned_framework_never_reports_a_version(self) -> None:
        # The HIPAA Security Rule is not versioned; only content changes matter.
        assert newer_versions("anything at all", "", "current") == []

    def test_fingerprint_state_round_trips(self, tmp_path: Path) -> None:
        from ironclad.frameworks.updates import CheckResult

        path = tmp_path / "state.json"
        save_state(path, [CheckResult(framework_id="soc2", name="SOC 2", fingerprint="abc")])
        assert load_state(path) == {"soc2": "abc"}

    def test_corrupt_state_is_treated_as_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text("{ not json")
        assert load_state(path) == {}

    def test_a_source_that_cannot_be_read_is_unchecked_not_changed(self, monkeypatch) -> None:
        # A standards body being down must not open a PR claiming a revision.
        from ironclad.frameworks.updates import check_framework

        monkeypatch.setattr(
            "ironclad.frameworks.updates._fetch", lambda url: ("", "connection refused")
        )
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {})
        assert result.status == "unchecked"
        assert not result.update_detected

    def test_an_unchanged_page_reports_no_update(self, monkeypatch) -> None:
        from ironclad.frameworks.updates import check_framework

        page = "<p>The Trust Services Criteria (2017) remain current.</p>"
        monkeypatch.setattr("ironclad.frameworks.updates._fetch", lambda url: (page, ""))
        seen = fingerprint(visible_text(page))
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {"soc2": seen})
        assert result.status == "unchanged"
        assert not result.update_detected

    def test_a_changed_page_reports_a_content_change(self, monkeypatch) -> None:
        from ironclad.frameworks.updates import check_framework

        monkeypatch.setattr(
            "ironclad.frameworks.updates._fetch",
            lambda url: ("<p>Substantially different wording here.</p>", ""),
        )
        result = check_framework("soc2", FRAMEWORK_SOURCES["soc2"], {"soc2": "an-old-digest"})
        assert result.status == "content_changed"
        assert result.update_detected
