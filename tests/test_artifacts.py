"""The deliverables, on a volume.

The target architecture splits persistence in two: relational state in MariaDB,
object and artifact files on a volume. The record store handles the first; this
handles the second — the report a client is issued and the auditor package.

The rule that matters: a deliverable that cannot be shown to be the one that was
issued is not evidence of anything. Every stored file is checksummed into a
manifest, and `verify()` re-checksums what is on disk against it — the same
argument the evidence index makes about the client's own documents, turned on
the documents this product produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironclad.cli import ARTIFACT_ROOT_ENV, main
from ironclad.engine import run_assessment
from ironclad.report.export import export_json
from ironclad.report.render import render_html
from ironclad.store import ArtifactStore, StoreError
from tests.conftest import NOW

TENANT = "acme"
ASSESSMENT = "acme-artifacts-1"


@pytest.fixture
def deliverables(tmp_path: Path, tiny_framework, evidence) -> Path:
    """What a run issues: a report, the machine record, and a package."""
    result = run_assessment(
        tenant_id=TENANT,
        framework=tiny_framework,
        evidence=evidence,
        group="deep",
        as_of=NOW,
        assessment_id=ASSESSMENT,
    )
    out = tmp_path / "out"
    (out / "package").mkdir(parents=True)
    (out / "assessment.json").write_text(export_json(result), encoding="utf-8")
    (out / "report.html").write_text(render_html(result, "Acme Corp"), encoding="utf-8")
    (out / "package" / "control-register.csv").write_text("control_id\nCC6.1\n", encoding="utf-8")
    return out


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "volume")


class TestStoringDeliverables:
    def test_a_directory_is_stored_keeping_its_layout(self, store, deliverables) -> None:
        stored = store.put(TENANT, ASSESSMENT, deliverables)
        assert {a.name for a in stored} == {
            "assessment.json",
            "report.html",
            "package/control-register.csv",
        }

    def test_a_single_file_is_stored_under_its_own_name(
        self, store, deliverables, tmp_path: Path
    ) -> None:
        stored = store.put(TENANT, ASSESSMENT, deliverables / "report.html")
        assert [a.name for a in stored] == ["report.html"]

    def test_the_layout_is_tenant_and_assessment_prefixed(self, store, deliverables) -> None:
        store.put(TENANT, ASSESSMENT, deliverables)
        location = Path(store.location(TENANT, ASSESSMENT))
        assert location.parts[-4:] == (TENANT, "assessments", ASSESSMENT, "artifacts")
        assert (location / "report.html").exists()

    def test_every_file_is_checksummed(self, store, deliverables) -> None:
        stored = store.put(TENANT, ASSESSMENT, deliverables)
        for artifact in stored:
            assert len(artifact.sha256) == 64
            assert artifact.size_bytes > 0

    def test_the_manifest_records_what_was_stored(self, store, deliverables) -> None:
        stored = store.put(TENANT, ASSESSMENT, deliverables)
        manifest = store.manifest(TENANT, ASSESSMENT)
        assert manifest is not None
        assert manifest["tenant_id"] == TENANT
        assert manifest["assessment_id"] == ASSESSMENT
        assert {a["name"] for a in manifest["artifacts"]} == {a.name for a in stored}
        assert manifest["stored_at"]

    def test_re_issuing_replaces_rather_than_accumulates(self, store, deliverables) -> None:
        # Two versions of a client's deliverable in circulation is the failure
        # this prevents.
        store.put(TENANT, ASSESSMENT, deliverables)
        (deliverables / "report.html").write_text("<html>revised</html>", encoding="utf-8")
        store.put(TENANT, ASSESSMENT, deliverables)
        location = Path(store.location(TENANT, ASSESSMENT))
        assert (location / "report.html").read_text(encoding="utf-8") == "<html>revised</html>"
        assert store.verify(TENANT, ASSESSMENT)["verified"] is True

    def test_two_tenants_do_not_share_a_directory(self, store, deliverables) -> None:
        store.put(TENANT, ASSESSMENT, deliverables)
        store.put("beta", "beta-1", deliverables)
        assert store.location(TENANT, ASSESSMENT) != store.location("beta", "beta-1")
        assert store.manifest("beta", ASSESSMENT) is None


class TestRefusals:
    def test_an_unsafe_tenant_cannot_escape_its_directory(self, store, deliverables) -> None:
        with pytest.raises(StoreError, match="not a usable tenant directory"):
            store.put("../escape", ASSESSMENT, deliverables)

    def test_an_unsafe_assessment_id_cannot_either(self, store, deliverables) -> None:
        with pytest.raises(StoreError, match="not a usable assessment directory"):
            store.put(TENANT, "a/b/c", deliverables)

    def test_a_missing_source_is_refused(self, store, tmp_path: Path) -> None:
        with pytest.raises(StoreError, match="does not exist"):
            store.put(TENANT, ASSESSMENT, tmp_path / "absent")

    def test_an_empty_directory_is_refused(self, store, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(StoreError, match="holds no files"):
            store.put(TENANT, ASSESSMENT, empty)

    def test_a_symlink_out_of_the_set_is_not_followed(
        self, store, deliverables, tmp_path: Path
    ) -> None:
        # A deliverable set must contain only what was issued.
        outside = tmp_path / "elsewhere.txt"
        outside.write_text("not part of this deliverable", encoding="utf-8")
        (deliverables / "borrowed.txt").symlink_to(outside)
        stored = store.put(TENANT, ASSESSMENT, deliverables)
        assert "borrowed.txt" not in {a.name for a in stored}

    def test_health_fails_closed_on_an_unusable_root(self, tmp_path: Path) -> None:
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("a file", encoding="utf-8")
        health = ArtifactStore(blocker / "volume").health()
        assert health["writable"] is False
        assert health["detail"]


class TestVerification:
    def test_untouched_deliverables_verify(self, store, deliverables) -> None:
        store.put(TENANT, ASSESSMENT, deliverables)
        verdict = store.verify(TENANT, ASSESSMENT)
        assert verdict["verified"] is True
        assert verdict["checked"] == 3

    def test_an_edited_deliverable_is_caught_and_named(self, store, deliverables) -> None:
        # The check to run on a restore from backup, and the reason the report
        # is checksummed at all.
        store.put(TENANT, ASSESSMENT, deliverables)
        report = Path(store.location(TENANT, ASSESSMENT)) / "report.html"
        report.write_text(report.read_text(encoding="utf-8") + "<!-- edited -->", "utf-8")
        verdict = store.verify(TENANT, ASSESSMENT)
        assert verdict["verified"] is False
        assert "report.html" in verdict["detail"]
        assert "checksum" in verdict["detail"]

    def test_a_removed_deliverable_is_caught_and_named(self, store, deliverables) -> None:
        store.put(TENANT, ASSESSMENT, deliverables)
        (Path(store.location(TENANT, ASSESSMENT)) / "report.html").unlink()
        verdict = store.verify(TENANT, ASSESSMENT)
        assert verdict["verified"] is False
        assert "report.html" in verdict["detail"]

    def test_nothing_stored_is_not_verified(self, store) -> None:
        verdict = store.verify(TENANT, "never-published")
        assert verdict["verified"] is False
        assert verdict["checked"] == 0


class TestThePublishCommand:
    def test_deliverables_are_stored_alongside_the_record(
        self, deliverables, tmp_path: Path, capsys
    ) -> None:
        root = str(tmp_path / "volume")
        code = main(
            [
                "store",
                "publish",
                "--to",
                root,
                "--input",
                str(deliverables / "assessment.json"),
                "--artifacts",
                str(deliverables),
            ]
        )
        assert code == 0
        reported = json.loads(capsys.readouterr().out)
        assert reported["assessment_id"] == ASSESSMENT
        assert len(reported["artifacts"]["files"]) == 3

    def test_a_volume_record_store_needs_no_second_root(
        self, deliverables, tmp_path: Path, capsys
    ) -> None:
        # One volume holds both. The layouts are chosen so that works.
        root = tmp_path / "volume"
        main(
            [
                "store",
                "publish",
                "--to",
                str(root),
                "--input",
                str(deliverables / "assessment.json"),
                "--artifacts",
                str(deliverables),
            ]
        )
        capsys.readouterr()
        assert (root / TENANT / "assessments" / ASSESSMENT / "assessment.json").exists()
        assert (root / TENANT / "assessments" / ASSESSMENT / "artifacts" / "report.html").exists()

    def test_an_explicit_artifact_volume_is_used(
        self, deliverables, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        artifacts = tmp_path / "artifact-volume"
        monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(artifacts))
        main(
            [
                "store",
                "publish",
                "--to",
                str(tmp_path / "records"),
                "--input",
                str(deliverables / "assessment.json"),
                "--artifacts",
                str(deliverables),
            ]
        )
        reported = json.loads(capsys.readouterr().out)
        assert str(artifacts) in reported["artifacts"]["location"]

    def test_verify_exits_zero_when_untouched(self, deliverables, tmp_path: Path, capsys) -> None:
        root = str(tmp_path / "volume")
        main(
            [
                "store",
                "publish",
                "--to",
                root,
                "--input",
                str(deliverables / "assessment.json"),
                "--artifacts",
                str(deliverables),
            ]
        )
        capsys.readouterr()
        code = main(
            ["store", "verify", "--to", root, "--client", TENANT, "--assessment-id", ASSESSMENT]
        )
        assert code == 0
        assert json.loads(capsys.readouterr().out)["verified"] is True

    def test_verify_exits_non_zero_when_edited(self, deliverables, tmp_path: Path, capsys) -> None:
        root = tmp_path / "volume"
        main(
            [
                "store",
                "publish",
                "--to",
                str(root),
                "--input",
                str(deliverables / "assessment.json"),
                "--artifacts",
                str(deliverables),
            ]
        )
        capsys.readouterr()
        report = root / TENANT / "assessments" / ASSESSMENT / "artifacts" / "report.html"
        report.write_text("<html>substituted</html>", encoding="utf-8")
        code = main(
            [
                "store",
                "verify",
                "--to",
                str(root),
                "--client",
                TENANT,
                "--assessment-id",
                ASSESSMENT,
            ]
        )
        assert code == 2
        assert json.loads(capsys.readouterr().out)["verified"] is False
