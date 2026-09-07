"""Staging a tenant's evidence from a NAS-backed volume.

GCP storage is retired from the target architecture, so evidence comes from a
volume laid out one prefix per tenant rather than from a `gs://` path. The rule
deciding which prefix a run may read lives in Python rather than in the
workflow's shell, because a containment test written in shell is a `--recursive`
away from reading another client's documents and nothing tests shell.

Two failure modes are worth more than the happy path. Reading outside the
tenant's prefix is a cross-tenant disclosure. Producing an empty evidence set is
a delivery problem that reads to a client as a catastrophic result — every
control a gap — and this pipeline has made exactly that mistake before
(PRODUCTIZE_NOTES.md §2.2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironclad.cli import EVIDENCE_ROOT_ENV, main
from ironclad.evidence_root import EvidenceRootError, resolve_prefix, stage_evidence


@pytest.fixture
def volume(tmp_path: Path) -> Path:
    """A volume with two tenants on it."""
    root = tmp_path / "volume"
    (root / "acme-corp").mkdir(parents=True)
    (root / "acme-corp" / "access-policy.txt").write_text("Access control policy.", "utf-8")
    (root / "acme-corp" / "reviews" / "q3").mkdir(parents=True)
    (root / "acme-corp" / "reviews" / "q3" / "review.txt").write_text("Q3 review.", "utf-8")
    (root / "beta-industries").mkdir(parents=True)
    (root / "beta-industries" / "their-policy.txt").write_text("Beta's own policy.", "utf-8")
    return root


class TestResolvingAPrefix:
    def test_a_tenant_gets_its_own_prefix(self, volume: Path) -> None:
        prefix = resolve_prefix(volume, "acme-corp")
        assert prefix.tenant_id == "acme-corp"
        assert prefix.path == (volume.resolve() / "acme-corp")
        assert prefix.file_count == 2

    def test_a_display_name_is_normalised(self, volume: Path) -> None:
        # "Acme Corp" is what a person types and what the workflow input carries.
        assert resolve_prefix(volume, "Acme Corp").tenant_id == "acme-corp"

    def test_a_path_shaped_client_id_is_refused_not_reinterpreted(self, volume: Path) -> None:
        # slugify turns "../beta-industries" into "beta-industries" — a different
        # valid tenant. Not a traversal, but a silent reinterpretation of what
        # was asked for, and this product refuses those rather than guessing.
        for hostile in ("../beta-industries", "acme/../beta-industries", "a/b", "..\\beta"):
            with pytest.raises(EvidenceRootError, match="not a client identifier"):
                resolve_prefix(volume, hostile)

    def test_a_symlink_out_of_the_tenant_tree_is_refused(self, volume: Path) -> None:
        # The one a textual check misses entirely.
        (volume / "sneaky").symlink_to(volume / "beta-industries")
        with pytest.raises(EvidenceRootError, match="resolves outside its own directory"):
            resolve_prefix(volume, "sneaky")

    def test_an_unknown_tenant_is_refused(self, volume: Path) -> None:
        with pytest.raises(EvidenceRootError, match="no evidence prefix"):
            resolve_prefix(volume, "nobody")

    def test_an_empty_prefix_is_refused_with_the_reason(self, volume: Path) -> None:
        # Not an assessment of nothing: every control would read as a gap, which
        # is a delivery problem rather than a client result.
        (volume / "quiet-client").mkdir()
        with pytest.raises(EvidenceRootError, match="refusing to assess nothing"):
            resolve_prefix(volume, "quiet-client")

    def test_a_missing_root_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(EvidenceRootError, match="not a directory"):
            resolve_prefix(tmp_path / "absent", "acme-corp")

    def test_an_empty_client_is_refused(self, volume: Path) -> None:
        with pytest.raises(EvidenceRootError, match="does not name a tenant"):
            resolve_prefix(volume, "!!!")


class TestStaging:
    def test_the_tenant_s_files_are_copied_keeping_their_layout(
        self, volume: Path, tmp_path: Path
    ) -> None:
        staged = stage_evidence(volume, "acme-corp", tmp_path / "work")
        assert staged.file_count == 2
        written = {
            p.relative_to(tmp_path / "work").as_posix()
            for p in (tmp_path / "work").rglob("*")
            if p.is_file()
        }
        assert written == {"access-policy.txt", "reviews/q3/review.txt"}

    def test_nothing_from_another_tenant_is_staged(self, volume: Path, tmp_path: Path) -> None:
        stage_evidence(volume, "acme-corp", tmp_path / "work")
        staged = (tmp_path / "work").rglob("*")
        assert not any(p.is_file() and "Beta" in p.read_text("utf-8") for p in staged)

    def test_the_volume_is_not_modified(self, volume: Path, tmp_path: Path) -> None:
        # Copied, not read in place: a run must not be able to alter the record.
        before = {p: p.stat().st_mtime for p in volume.rglob("*") if p.is_file()}
        stage_evidence(volume, "acme-corp", tmp_path / "work")
        after = {p: p.stat().st_mtime for p in volume.rglob("*") if p.is_file()}
        assert before == after

    def test_a_symlink_inside_the_prefix_pointing_out_is_skipped(
        self, volume: Path, tmp_path: Path
    ) -> None:
        # Planted inside the tenant's own tree, so the prefix check passes and
        # only the per-file resolution catches it.
        (volume / "acme-corp" / "borrowed.txt").symlink_to(
            volume / "beta-industries" / "their-policy.txt"
        )
        staged = stage_evidence(volume, "acme-corp", tmp_path / "work")
        assert staged.file_count == 2
        assert not (tmp_path / "work" / "borrowed.txt").exists()

    def test_staging_twice_is_stable(self, volume: Path, tmp_path: Path) -> None:
        first = stage_evidence(volume, "acme-corp", tmp_path / "work")
        second = stage_evidence(volume, "acme-corp", tmp_path / "work")
        assert first.file_count == second.file_count


class TestTheEvidenceCommand:
    def test_it_stages_and_reports(self, volume: Path, tmp_path: Path, capsys) -> None:
        code = main(
            [
                "evidence",
                "stage",
                "--root",
                str(volume),
                "--client",
                "Acme Corp",
                "--out",
                str(tmp_path / "work"),
            ]
        )
        assert code == 0
        reported = json.loads(capsys.readouterr().out)
        assert reported["tenant_id"] == "acme-corp"
        assert reported["files"] == 2

    def test_the_root_comes_from_the_environment(
        self, volume: Path, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setenv(EVIDENCE_ROOT_ENV, str(volume))
        assert (
            main(["evidence", "stage", "--client", "acme-corp", "--out", str(tmp_path / "w")]) == 0
        )
        assert json.loads(capsys.readouterr().out)["files"] == 2

    def test_no_root_at_all_is_refused(self, tmp_path: Path, monkeypatch, capsys) -> None:
        monkeypatch.delenv(EVIDENCE_ROOT_ENV, raising=False)
        assert main(["evidence", "stage", "--client", "acme", "--out", str(tmp_path / "w")]) == 2
        assert "no evidence root" in capsys.readouterr().err

    def test_a_cross_tenant_attempt_exits_non_zero(
        self, volume: Path, tmp_path: Path, capsys
    ) -> None:
        code = main(
            [
                "evidence",
                "stage",
                "--root",
                str(volume),
                "--client",
                "../beta-industries",
                "--out",
                str(tmp_path / "work"),
            ]
        )
        assert code == 2
        assert "not a client identifier" in capsys.readouterr().err

    def test_an_empty_prefix_exits_non_zero(self, volume: Path, tmp_path: Path, capsys) -> None:
        # The failure this pipeline has made before: an empty fetch that ran on.
        (volume / "quiet").mkdir()
        code = main(
            [
                "evidence",
                "stage",
                "--root",
                str(volume),
                "--client",
                "quiet",
                "--out",
                str(tmp_path / "work"),
            ]
        )
        assert code == 2
        assert "refusing to assess nothing" in capsys.readouterr().err


class TestStagedEvidenceAssesses:
    def test_a_staged_prefix_runs_through_the_engine(self, tmp_path: Path) -> None:
        # The point of the whole thing: what is staged is what gets assessed.
        from ironclad.engine import run_assessment
        from ironclad.ingest import collect_from_directory

        repo_root = Path(__file__).resolve().parents[1]
        volume = tmp_path / "volume" / "icit-internal"
        volume.mkdir(parents=True)
        for source in (repo_root / "examples" / "evidence").glob("*.txt"):
            (volume / source.name).write_text(source.read_text("utf-8"), "utf-8")

        staged = stage_evidence(tmp_path / "volume", "icit-internal", tmp_path / "work")
        assert staged.file_count == 5

        evidence, _ = collect_from_directory("icit-internal", tmp_path / "work", "soc2")
        result = run_assessment(
            tenant_id="icit-internal", framework="soc2", evidence=evidence, group="quick"
        )
        assert result.assessment.summary.evidence_artifacts == 5
        assert result.assessment.summary.total_controls > 0
