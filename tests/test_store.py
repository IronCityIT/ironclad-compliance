"""Where a finished assessment goes.

Firestore is retired from the target architecture; persistent state moves to
NAS-backed MariaDB with artifact files on a NAS volume. This is the seam that
makes that move possible without the engine knowing about it.

The properties asserted here are the ones the product is built on, and they are
asserted against *every* store rather than per backend — a store that is
tenant-scoped on disk and leaky in SQL is not a store this product can use.

The MariaDB tests run against a real server when one is configured
(`IRONCLAD_TEST_DSN`), and skip otherwise. They are not mocked: a mock of a
database proves that the mock matches the code, which is the one thing never in
doubt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from ironclad.engine import run_assessment
from ironclad.store import (
    TABLES,
    FileResultStore,
    ResultStore,
    StoreError,
    rows_from_document,
    store_from_target,
    target_summary,
)
from ironclad.store.mariadb import Dsn, MariaDBResultStore
from tests.conftest import NOW

TEST_DSN = os.environ.get("IRONCLAD_TEST_DSN", "")
needs_mariadb = pytest.mark.skipif(
    not TEST_DSN, reason="set IRONCLAD_TEST_DSN to run against a real MariaDB"
)


@pytest.fixture
def document(tiny_framework, evidence) -> dict[str, Any]:
    result = run_assessment(
        tenant_id="acme",
        framework=tiny_framework,
        evidence=evidence,
        group="deep",
        as_of=NOW,
        assessment_id="acme-store-1",
    )
    return json.loads(json.dumps(result.to_dict()))


@pytest.fixture
def other_document(document) -> dict[str, Any]:
    """A second tenant's result.

    Re-labelled rather than re-run: the engine refuses to assess one tenant's
    evidence into another's record, which is the right behaviour and makes a
    genuine second run awkward to build. A store is handed a document and has to
    partition on what the document says, which is exactly what this exercises.
    """
    other = json.loads(json.dumps(document))
    other["tenant_id"] = "beta"
    other["assessment_id"] = "beta-store-1"
    for key in ("controls", "findings"):
        for row in other.get(key, []):
            row["tenant_id"] = "beta"
    other["remediation"]["tenant_id"] = "beta"
    other["remediation"]["assessment_id"] = "beta-store-1"
    for item in other["remediation"]["items"]:
        item["tenant_id"] = "beta"
        item["item_id"] = item["item_id"].replace("acme", "beta", 1)
    other["audit"]["tenant_id"] = "beta"
    for event in other["audit"]["events"]:
        event["tenant_id"] = "beta"
    return other


class TestTheProjection:
    """A document in, tenant-scoped rows out. No storage, no I/O."""

    def test_every_table_is_produced(self, document) -> None:
        rows = rows_from_document(document)
        assert set(rows.counts()) == set(TABLES)
        assert rows.total() > 0

    def test_every_row_carries_its_tenant(self, document) -> None:
        # The whole of the tenant partition is a filter, and a row with no
        # tenant cannot be filtered.
        rows = rows_from_document(document)
        for table in TABLES:
            for row in rows.table(table):
                assert row.get("tenant_id") == "acme", f"{table} row without a tenant"

    def test_one_row_per_control(self, document) -> None:
        rows = rows_from_document(document)
        assert len(rows.assessment_controls) == len(document["controls"])

    def test_no_evidence_content_is_projected(self, document, evidence) -> None:
        # References and checksums only. The artifacts stay in the client's own
        # storage; this is the index, not a copy.
        rows = rows_from_document(document)
        serialized = json.dumps({table: rows.table(table) for table in TABLES}, default=str)
        for artifact in evidence:
            if artifact.text:
                assert artifact.text[:60] not in serialized, "evidence text was projected"

    def test_the_audit_chain_keeps_its_order_and_digests(self, document) -> None:
        rows = rows_from_document(document)
        events = document["audit"]["events"]
        assert [r["event_id"] for r in rows.audit_events] == [e["event_id"] for e in events]
        assert [r["ordinal"] for r in rows.audit_events] == list(range(len(events)))
        for stored, original in zip(rows.audit_events, events, strict=True):
            assert stored["prev_hash"] == original["prev_hash"]
            assert stored["hash"] == original["hash"]

    def test_a_document_with_no_tenant_is_refused(self, document) -> None:
        # Both halves of the identity are required: a store that invented either
        # would file a client's result where nobody would look for it.
        for missing in ("tenant_id", "assessment_id"):
            broken = dict(document)
            broken[missing] = ""
            broken.pop("client_id", None)
            with pytest.raises(ValueError, match=missing):
                rows_from_document(broken)

    def test_client_id_stands_in_for_tenant_id(self, document) -> None:
        # The ICIT standard workflow input is client_id; the engine's is
        # tenant_id. Either names the same partition.
        document.pop("tenant_id")
        document["client_id"] = "acme"
        assert rows_from_document(document).tenant_id == "acme"


class TestTheTarget:
    def test_a_path_is_a_volume(self, tmp_path: Path) -> None:
        assert isinstance(store_from_target(str(tmp_path)), FileResultStore)

    def test_a_file_url_is_a_volume(self, tmp_path: Path) -> None:
        assert isinstance(store_from_target(f"file://{tmp_path}"), FileResultStore)

    @pytest.mark.parametrize("scheme", ["mysql", "mariadb"])
    def test_a_sql_url_is_mariadb(self, scheme: str) -> None:
        store = store_from_target(f"{scheme}://u:p@db.example:3306/ironclad")
        assert isinstance(store, MariaDBResultStore)

    @pytest.mark.parametrize("target", ["https://example.com/x", "s3://bucket/x", "gs://b/x"])
    def test_an_unknown_scheme_is_refused_not_guessed(self, target: str) -> None:
        # Silently writing a client's assessment into a directory called "gs:"
        # is worse than failing.
        with pytest.raises(StoreError, match="not a store"):
            store_from_target(target)

    def test_an_empty_target_is_refused(self) -> None:
        with pytest.raises(StoreError, match="no store target"):
            store_from_target("   ")

    def test_a_dsn_never_prints_its_password(self) -> None:
        secret = "hunter2correcthorse"  # noqa: S105 — a fixture, not a credential
        target = f"mysql://icit:{secret}@db.example:3306/ironclad"
        for rendered in (target_summary(target), str(Dsn(target)), repr(Dsn(target))):
            assert secret not in rendered
            assert "icit@db.example:3306/ironclad" == rendered

    def test_a_dsn_must_name_a_host_and_a_database(self) -> None:
        with pytest.raises(StoreError, match="no database"):
            Dsn("mysql://u:p@db.example:3306/")
        with pytest.raises(StoreError, match="no host"):
            Dsn("mysql:///ironclad")

    def test_a_non_sql_scheme_is_refused_by_the_dsn(self) -> None:
        with pytest.raises(StoreError, match="mysql:// or mariadb://"):
            Dsn("postgres://u:p@db.example/ironclad")


class StoreContract:
    """The behaviour every store must have. Subclassed per backend."""

    def store(self, tmp_path: Path) -> Any:
        raise NotImplementedError

    def test_it_satisfies_the_protocol(self, tmp_path: Path) -> None:
        assert isinstance(self.store(tmp_path), ResultStore)

    def test_a_stored_assessment_reads_back(self, tmp_path: Path, document) -> None:
        store = self.store(tmp_path)
        assert store.put_assessment(document) == "acme-store-1"
        found = store.get_assessment("acme", "acme-store-1")
        assert found is not None
        assert found["framework_id"] == document["framework"]["id"]
        assert float(found["readiness_score"]) == pytest.approx(
            document["summary"]["readiness_score"], abs=0.01
        )

    def test_storing_twice_leaves_one_record(self, tmp_path: Path, document) -> None:
        # Re-running a pipeline is normal. It must not accumulate duplicates.
        store = self.store(tmp_path)
        store.put_assessment(document)
        store.put_assessment(document)
        assert len(store.list_assessments("acme")) == 1
        assert len(store.list_audit("acme")) == len(document["audit"]["events"])

    def test_a_re_run_replaces_its_own_detail(self, tmp_path: Path, document) -> None:
        store = self.store(tmp_path)
        store.put_assessment(document)
        before = len(store.list_remediation("acme"))
        store.put_assessment(document)
        assert len(store.list_remediation("acme")) == before, "detail rows duplicated"

    def test_no_read_crosses_a_tenant(self, tmp_path: Path, document, other_document) -> None:
        store = self.store(tmp_path)
        store.put_assessment(document)
        store.put_assessment(other_document)

        assert store.get_assessment("acme", "beta-store-1") is None
        assert store.get_assessment("beta", "acme-store-1") is None
        assert [a["assessment_id"] for a in store.list_assessments("acme")] == ["acme-store-1"]
        assert [a["assessment_id"] for a in store.list_assessments("beta")] == ["beta-store-1"]
        for row in store.list_remediation("acme"):
            assert row["tenant_id"] == "acme"
        for event in store.list_audit("beta"):
            assert event["tenant_id"] == "beta"

    def test_an_unknown_assessment_is_none_not_an_error(self, tmp_path: Path) -> None:
        assert self.store(tmp_path).get_assessment("acme", "never-happened") is None

    def test_an_unknown_tenant_reads_empty(self, tmp_path: Path, document) -> None:
        store = self.store(tmp_path)
        store.put_assessment(document)
        assert store.list_assessments("nobody") == []
        assert store.list_remediation("nobody") == []
        assert store.list_audit("nobody") == []

    def test_the_audit_trail_survives_a_re_publish_intact(self, tmp_path: Path, document) -> None:
        store = self.store(tmp_path)
        store.put_assessment(document)
        store.put_assessment(document)
        events = store.list_audit("acme")
        assert [e["event_id"] for e in events] == [
            e["event_id"] for e in document["audit"]["events"]
        ]
        previous = ""
        for index, event in enumerate(events):
            if index:
                assert event["prev_hash"] == previous
            previous = event["hash"]

    def test_health_reports_a_writable_store(self, tmp_path: Path) -> None:
        health = self.store(tmp_path).health()
        assert health["writable"] is True
        assert "store" in health


class TestTheVolume(StoreContract):
    def store(self, tmp_path: Path) -> Any:
        return FileResultStore(tmp_path / "nas")

    def test_the_layout_is_tenant_prefixed(self, tmp_path: Path, document) -> None:
        store = self.store(tmp_path)
        store.put_assessment(document)
        written = {
            p.relative_to(tmp_path / "nas").as_posix()
            for p in (tmp_path / "nas").rglob("*")
            if p.is_file()
        }
        assert "acme/audit.jsonl" in written
        assert "acme/assessments/acme-store-1/assessment.json" in written
        assert all(path.startswith("acme/") for path in written)

    def test_the_whole_document_is_kept_alongside_the_rows(self, tmp_path: Path, document) -> None:
        # The rows are a projection; the document is the record as issued.
        store = self.store(tmp_path)
        store.put_assessment(document)
        assert store.get_document("acme", "acme-store-1") == document

    def test_a_tenant_id_cannot_escape_its_own_prefix(self, tmp_path: Path, document) -> None:
        # The tenant id becomes a path segment, so it is checked, not trusted.
        store = self.store(tmp_path)
        document["tenant_id"] = "../escape"
        with pytest.raises(StoreError, match="not a usable tenant directory"):
            store.put_assessment(document)

    def test_an_assessment_id_cannot_escape_either(self, tmp_path: Path, document) -> None:
        store = self.store(tmp_path)
        document["assessment_id"] = "a/b/c"
        with pytest.raises(StoreError, match="not a usable assessment directory"):
            store.put_assessment(document)

    def test_health_fails_closed_on_an_unusable_root(self, tmp_path: Path) -> None:
        # A NAS volume that is not mounted must report unwritable rather than
        # look fine and lose the result later. Checked by writing, not by a
        # stat: an absent mount point looks like an ordinary empty directory.
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("this is a file", encoding="utf-8")
        health = FileResultStore(blocker / "volume").health()
        assert health["writable"] is False
        assert health["detail"]

    def test_a_corrupt_audit_line_is_named_not_skipped(self, tmp_path: Path, document) -> None:
        # Skipping the bad line would silently shorten an audit trail, which is
        # the one file where a quiet omission is the whole problem.
        store = self.store(tmp_path)
        store.put_assessment(document)
        trail = tmp_path / "nas" / "acme" / "audit.jsonl"
        line = len(document["audit"]["events"]) + 1
        trail.write_text(trail.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
        with pytest.raises(StoreError, match=f"line {line} is not a valid audit event"):
            store.list_audit("acme")


@needs_mariadb
class TestMariaDB(StoreContract):
    def store(self, tmp_path: Path) -> Any:
        store = MariaDBResultStore(TEST_DSN)
        store.init_schema()
        connection = store._connect()  # noqa: SLF001 — the test owns this database
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                for table in ("audit_events", *reversed(TABLES[:-1])):
                    cursor.execute(f"TRUNCATE TABLE `{table}`")
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            connection.commit()
        finally:
            connection.close()
        return store

    def test_the_schema_applies_twice(self, tmp_path: Path) -> None:
        store = MariaDBResultStore(TEST_DSN)
        assert len(store.init_schema()) == len(TABLES)
        assert len(store.init_schema()) == len(TABLES)

    def test_health_names_the_server_without_the_password(self, tmp_path: Path) -> None:
        health = self.store(tmp_path).health()
        assert health["writable"] is True
        assert "MariaDB" in health["server_version"] or health["server_version"]
        assert Dsn(TEST_DSN).password not in json.dumps(health)

    def test_the_chain_verifies_out_of_the_database(self, tmp_path: Path, document) -> None:
        store = self.store(tmp_path)
        store.put_assessment(document)
        verdict = store.verify_audit_chain("acme")
        assert verdict["verified"] is True
        assert verdict["events"] == len(document["audit"]["events"])

    def test_a_tampered_chain_is_caught_and_named(self, tmp_path: Path, document) -> None:
        # The free integrity check on any restore: the digests are stored
        # verbatim, so an edited row breaks the link and says where.
        store = self.store(tmp_path)
        store.put_assessment(document)
        connection = store._connect()  # noqa: SLF001
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE audit_events SET prev_hash = 'tampered' "
                    "WHERE tenant_id = 'acme' ORDER BY id DESC LIMIT 1"
                )
            connection.commit()
        finally:
            connection.close()
        verdict = store.verify_audit_chain("acme")
        assert verdict["verified"] is False
        assert verdict["broken_at"]

    def test_a_control_row_carries_its_verdict(self, tmp_path: Path, document) -> None:
        store = self.store(tmp_path)
        store.put_assessment(document)
        controls = store.list_controls("acme", "acme-store-1")
        assert len(controls) == len(document["controls"])
        by_id = {c["control_id"]: c for c in controls}
        for original in document["controls"]:
            assert by_id[original["control_id"]]["status"] == original["status"]

    def test_a_failed_write_leaves_nothing_behind(self, tmp_path: Path, document) -> None:
        # All or nothing: half an assessment reads as a client who lost thirty
        # controls, which is worse than a failed publish.
        store = self.store(tmp_path)
        document["controls"][0]["control_id"] = "x" * 200  # longer than the column
        with pytest.raises(StoreError):
            store.put_assessment(document)
        assert store.get_assessment("acme", "acme-store-1") is None


class TestTheStoreCommand:
    def test_health_exits_zero_on_a_writable_volume(self, tmp_path: Path, capsys) -> None:
        from ironclad.cli import main

        assert main(["store", "health", "--to", str(tmp_path / "nas")]) == 0
        assert json.loads(capsys.readouterr().out)["writable"] is True

    def test_health_exits_non_zero_on_an_unusable_store(self, tmp_path: Path) -> None:
        # So a pipeline stops before it produces a result it cannot publish.
        from ironclad.cli import main

        blocker = tmp_path / "not-a-directory"
        blocker.write_text("this is a file", encoding="utf-8")
        assert main(["store", "health", "--to", str(blocker / "volume")]) == 2

    def test_publish_then_list(self, tmp_path: Path, document, capsys) -> None:
        from ironclad.cli import main

        source = tmp_path / "assessment.json"
        source.write_text(json.dumps(document), encoding="utf-8")
        root = str(tmp_path / "nas")

        assert main(["store", "publish", "--to", root, "--input", str(source)]) == 0
        capsys.readouterr()
        assert main(["store", "list", "--to", root, "--client", "acme"]) == 0
        listed = json.loads(capsys.readouterr().out)["assessments"]
        assert [a["assessment_id"] for a in listed] == ["acme-store-1"]

    def test_the_target_comes_from_the_environment_when_not_given(
        self, tmp_path: Path, document, monkeypatch, capsys
    ) -> None:
        # A DSN carries a password: a command line ends up in a process list, a
        # shell history and a CI log. The environment is where it belongs.
        from ironclad.cli import STORE_ENV, main

        monkeypatch.setenv(STORE_ENV, str(tmp_path / "nas"))
        assert main(["store", "health"]) == 0
        assert json.loads(capsys.readouterr().out)["writable"] is True

    def test_no_target_at_all_is_refused(self, monkeypatch, capsys) -> None:
        from ironclad.cli import STORE_ENV, main

        monkeypatch.delenv(STORE_ENV, raising=False)
        assert main(["store", "health"]) == 2
        assert "no store target" in capsys.readouterr().err

    def test_a_missing_result_file_is_refused(self, tmp_path: Path, capsys) -> None:
        from ironclad.cli import main

        code = main(
            ["store", "publish", "--to", str(tmp_path), "--input", str(tmp_path / "absent.json")]
        )
        assert code == 2
        assert "result not found" in capsys.readouterr().err

    def test_init_is_a_no_op_for_a_volume(self, tmp_path: Path, capsys) -> None:
        from ironclad.cli import main

        assert main(["store", "init", "--to", str(tmp_path / "nas")]) == 0
        assert "needs no schema" in capsys.readouterr().err
