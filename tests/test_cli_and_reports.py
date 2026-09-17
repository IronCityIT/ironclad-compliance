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

    def test_commentary_names_the_worst_rated_controls_and_no_model(self, result) -> None:
        # The models' wording stays on the record, off the report: only ids
        # and counts reach the client, and nothing that could name a tool or
        # a vendor under Iron City's name.
        import base64
        import json

        from ironclad.engine import consensus_findings, merge_consensus

        sent = consensus_findings(result.findings_payload())
        assert len(sent) >= 2
        answers = [
            {
                "consensus_severity": "CRITICAL" if i == 0 else "MEDIUM",
                "confidence_percent": 81.4,
                "total_models": 15,
                "successful_models": 12,
                "aggregated_remediation": ["Deploy VendorScanner Pro on every host"],
            }
            for i, _ in enumerate(sent)
        ]
        merge_consensus(result, base64.b64encode(json.dumps(answers).encode()).decode())
        html = render_html(result, "Acme Corp")
        assert "Analyst commentary" in html
        assert "overall position Critical" in html
        assert "(confidence 81%)" in html
        assert f"Rated critical: {sent[0]['target']}." in html
        assert "VendorScanner" not in html

    def test_no_model_responding_is_not_presented_as_commentary(self, result) -> None:
        import base64
        import json

        from ironclad.engine import consensus_findings, merge_consensus

        answers = [
            {
                "consensus_severity": "HIGH",
                "confidence_percent": 0,
                "total_models": 15,
                "successful_models": 0,
            }
            for _ in consensus_findings(result.findings_payload())
        ]
        merge_consensus(result, base64.b64encode(json.dumps(answers).encode()).decode())
        html = render_html(result, "Acme Corp")
        assert "Analyst commentary" not in html
        assert "no model responded" in html  # as a caveat, not as a verdict

    def test_a_capability_failure_is_disclosed_in_the_report(self, result) -> None:
        result.failed_modules["freshness_check"] = "RuntimeError: boom"
        html = render_html(result, "Acme Corp")
        assert "Assessment caveats" in html
        assert "freshness_check" in html


def _sha256sums(path: Path) -> dict[str, str]:
    """Parse a `sha256sum -c` file into {name: digest}."""
    sums: dict[str, str] = {}
    for line in path.read_text().splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    return sums


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

    def test_the_package_carries_a_checksum_for_every_file_it_ships(
        self, result, evidence, tmp_path: Path
    ) -> None:
        # package.json used to list the file names and nothing else, so an
        # auditor had no way to tell the package they received from one with
        # a verdict edited in control-register.csv. The audit chain protects
        # the trail, not the CSVs.
        import hashlib

        package = tmp_path / "package"
        export_audit_package(result, evidence, package)
        manifest = json.loads((package / "package.json").read_text())
        sums = _sha256sums(package / "SHA256SUMS")
        on_disk = {p.name for p in package.iterdir()}

        assert set(manifest["files"]) == on_disk
        assert set(sums) == on_disk - {"SHA256SUMS"}
        for name, digest in sums.items():
            assert hashlib.sha256((package / name).read_bytes()).hexdigest() == digest, name
        # package.json carries the same digests for the files written before it
        for name, digest in manifest["sha256"].items():
            assert sums[name] == digest, name
        assert "control-register.csv" in manifest["sha256"]

    def test_an_edited_verdict_no_longer_matches_the_package(
        self, result, evidence, tmp_path: Path
    ) -> None:
        import hashlib
        import shutil
        import subprocess

        package = tmp_path / "package"
        export_audit_package(result, evidence, package)
        register = package / "control-register.csv"
        register.write_text(register.read_text().replace("partial", "compliant", 1))

        sums = _sha256sums(package / "SHA256SUMS")
        assert hashlib.sha256(register.read_bytes()).hexdigest() != sums["control-register.csv"]
        # and the stock tool the README tells the auditor to run agrees
        if shutil.which("sha256sum"):
            check = subprocess.run(
                ["sha256sum", "-c", "SHA256SUMS"], cwd=package, capture_output=True, text=True
            )
            assert check.returncode != 0
            assert "control-register.csv: FAILED" in check.stdout

    def test_the_package_carries_the_report_as_issued_not_a_re_render(
        self, result, evidence, tmp_path: Path
    ) -> None:
        # The issued report can carry what the stored result cannot — the
        # "Since the last assessment" section rendered against a previous
        # assessment. The first pipeline run with a trend produced two
        # different reports, one issued and one in the package labelled "the
        # deliverable as issued".
        import hashlib

        issued = tmp_path / "issued.html"
        issued.write_text("<html><body>Since the last assessment: as issued</body></html>")
        package = tmp_path / "package"
        export_audit_package(result, evidence, package, issued_report=issued)
        assert (package / "report.html").read_bytes() == issued.read_bytes()
        sums = _sha256sums(package / "SHA256SUMS")
        assert sums["report.html"] == hashlib.sha256(issued.read_bytes()).hexdigest()

        # without one, the package still renders a report from the result
        plain = tmp_path / "plain"
        export_audit_package(result, evidence, plain)
        assert "<html" in (plain / "report.html").read_text()

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

    def test_a_stored_result_carries_its_audit_trail(self, result, tmp_path: Path) -> None:
        # The report job exports the auditor package from the stored JSON. The
        # stand-in used to start with an empty log, so the package it produced
        # had a header-only audit-trail.csv and certified the genesis hash as
        # a verified chain head — for every assessment the pipeline issued.
        from ironclad.report.export import export_audit_package

        restored = _StoredResult(json.loads(export_json(result)))
        assert len(restored.audit.events) == len(result.audit.events) >= 1
        assert restored.audit.head == result.audit.head
        assert restored.audit.is_valid()

        export_audit_package(restored, restored.evidence, tmp_path)
        manifest = json.loads((tmp_path / "package.json").read_text())
        assert manifest["audit_chain_head"] == result.audit.head
        assert manifest["audit_chain_verified"] is True
        rows = (tmp_path / "audit-trail.csv").read_text().splitlines()
        assert len(rows) == 1 + len(result.audit.events)

    def test_a_tampered_stored_trail_does_not_verify(self, result) -> None:
        # The stored digests are kept, not recomputed: editing an event on
        # disk has to show, or the package's "verified" means nothing.
        document = json.loads(export_json(result))
        document["audit"]["events"][0]["actor"] = "someone-else"
        restored = _StoredResult(document)
        assert restored.audit.is_valid() is False


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

    def test_validate_reports_a_file_that_is_not_json_as_a_finding(
        self, tmp_path: Path, capsys
    ) -> None:
        # The command exists to be handed dubious files. Handed one that was
        # not JSON, all three flags produced a JSONDecodeError traceback.
        not_json = tmp_path / "policy.json"
        not_json.write_text("tenant: acme\n")
        binary = tmp_path / "framework.json"
        binary.write_bytes(b"\xff\xfe\x00")

        assert main(["validate", "--policy", str(not_json), "--manifest", str(not_json)]) == 2
        report = json.loads(capsys.readouterr().out)
        assert report["valid"] is False
        assert "not valid JSON" in report["problems"]["policy"][0]
        assert "not valid JSON" in report["problems"]["manifest"][0]

        assert main(["validate", "--framework", str(binary)]) == 2
        report = json.loads(capsys.readouterr().out)
        assert "not a text file" in report["problems"]["framework"][0]

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

    @pytest.mark.parametrize("client", ["../beta", "acme/../beta", "a\\b", "acme..", "", "  "])
    def test_assess_refuses_a_client_that_would_be_reinterpreted(
        self, tmp_path: Path, capsys, client: str
    ) -> None:
        # `--client ../beta` assessed, and filed the record, as tenant "beta":
        # slugify strips what it does not like and what is left is a different
        # valid tenant. Staging already refused this; the record now does too.
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "policy.md").write_text("access control policy")
        out = tmp_path / "out"
        code = main(
            [
                "assess",
                "--client",
                client,
                "--framework",
                "soc2",
                "--evidence-dir",
                str(evidence_dir),
                "--out",
                str(out),
            ]
        )
        assert code == 2, client
        err = capsys.readouterr().err
        assert "refused rather than reinterpreted" in err or "does not name a tenant" in err
        assert not out.exists()

    def test_report_and_compare_refuse_a_file_that_is_not_an_assessment(
        self, tmp_path: Path, capsys
    ) -> None:
        # `report --input findings.b64` and `--compare-to README.md` were both
        # JSONDecodeError tracebacks; a JSON file of the wrong shape was worse,
        # a KeyError somewhere inside the renderer.
        not_json = tmp_path / "notes.md"
        not_json.write_text("# not an assessment")
        wrong_shape = tmp_path / "versions.json"
        wrong_shape.write_text(json.dumps({"frameworks": []}))
        out = tmp_path / "report.html"

        for bad, reason in ((not_json, "not valid JSON"), (wrong_shape, "expected the assessment")):
            assert main(["report", "--input", str(bad), "--out", str(out)]) == 2
            assert reason in capsys.readouterr().err
            assert main(["compare", "--from", str(bad), "--to", str(bad)]) == 2
            assert reason in capsys.readouterr().err
            assert main(["export", "--input", str(bad), "--out", str(tmp_path / "x")]) == 2
            capsys.readouterr()
        assert not out.exists()

        assert main(["report", "--input", str(tmp_path / "absent.json"), "--out", str(out)]) == 2
        assert "not found" in capsys.readouterr().err

    def test_compare_across_tenants_is_a_refusal_not_a_traceback(
        self, tmp_path: Path, capsys
    ) -> None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "policy.md").write_text("access control policy")
        for client in ("acme", "beta"):
            assert (
                main(
                    [
                        "assess",
                        "--client",
                        client,
                        "--framework",
                        "soc2",
                        "--evidence-dir",
                        str(evidence_dir),
                        "--group",
                        "quick",
                        "--out",
                        str(tmp_path / client),
                    ]
                )
                == 0
            )
        acme = str(tmp_path / "acme" / "assessment.json")
        beta = str(tmp_path / "beta" / "assessment.json")
        assert main(["compare", "--from", acme, "--to", beta]) == 2
        assert "different tenants" in capsys.readouterr().err
        assert (
            main(
                ["report", "--input", beta, "--out", str(tmp_path / "r.html"), "--compare-to", acme]
            )
            == 2
        )
        assert "different tenants" in capsys.readouterr().err

    def test_export_refuses_a_missing_issued_report(self, tmp_path: Path, capsys) -> None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "policy.md").write_text("access control policy")
        out = tmp_path / "out"
        assert (
            main(
                [
                    "assess",
                    "--client",
                    "acme",
                    "--framework",
                    "soc2",
                    "--group",
                    "quick",
                    "--evidence-dir",
                    str(evidence_dir),
                    "--out",
                    str(out),
                ]
            )
            == 0
        )
        code = main(
            [
                "export",
                "--input",
                str(out / "assessment.json"),
                "--format",
                "package",
                "--report",
                str(tmp_path / "absent.html"),
                "--out",
                str(tmp_path / "pkg"),
            ]
        )
        assert code == 2
        assert "issued report not found" in capsys.readouterr().err
        code = main(
            [
                "export",
                "--input",
                str(out / "assessment.json"),
                "--format",
                "package",
                "--report",
                str(out / "report.html"),
                "--out",
                str(tmp_path / "pkg"),
            ]
        )
        assert code == 0
        assert (tmp_path / "pkg" / "report.html").read_bytes() == (out / "report.html").read_bytes()

    def test_assess_refuses_an_id_the_store_would_refuse(self, tmp_path: Path, capsys) -> None:
        # Found by passing `../../escape`: assess accepted it, the AI stage
        # would have run, and the volume store refused it at publish. Same
        # rule, applied before anything has been paid for.
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "policy.md").write_text("access control policy")
        out = tmp_path / "out"
        for bad in ("../../escape", "x/y", "..", "__proto__"):
            code = main(
                [
                    "assess",
                    "--client",
                    "acme",
                    "--framework",
                    "soc2",
                    "--evidence-dir",
                    str(evidence_dir),
                    "--assessment-id",
                    bad,
                    "--out",
                    str(out),
                ]
            )
            assert code == 2, bad
            assert "cannot be stored" in capsys.readouterr().err
            assert not out.exists()

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

    # The three `check_framework` cases that used to live here — a source that
    # cannot be read, an unchanged page and a changed one — moved to
    # tests/test_update_checker.py. They were written against pages a few dozen
    # characters long, which no real source is, and which the checker now
    # correctly refuses to compare: a response that short is a blocked or empty
    # fetch, not a change. Rewriting them with realistic pages belonged beside
    # the rest of the checker's behaviour rather than here.
