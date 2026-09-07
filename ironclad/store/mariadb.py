"""MariaDB as the store of record.

The target for persistent state now that Firestore is retired. It writes exactly
the rows `rows.py` produces, so this backend and the filesystem one are the same
data in two places rather than two shapes that have to be kept in step.

The driver is an optional import. The engine core is standard-library only by
design, and a compliance assessment does not need a database to run — it needs
one to publish. So `PyMySQL` is installed by the job that publishes and absent
everywhere else, and its absence is a clear refusal rather than an ImportError
from three frames down.

**Nothing here logs a DSN.** A connection string carries a password, and the one
place a password reliably escapes is a log line written to help somebody debug.
Errors name the host, the port and the database, never the credential.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from ironclad.store.base import StoreError
from ironclad.store.rows import RowSet, rows_from_document

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_PORT = 3306


class Dsn:
    """A parsed connection target that will not print its own password."""

    def __init__(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("mysql", "mariadb"):
            raise StoreError(
                f"the store DSN must be mysql:// or mariadb://, not {parsed.scheme or 'nothing'}://"
            )
        if not parsed.hostname:
            raise StoreError("the store DSN names no host")
        database = (parsed.path or "").lstrip("/")
        if not database:
            raise StoreError("the store DSN names no database")

        self.host = parsed.hostname
        self.port = parsed.port or DEFAULT_PORT
        self.user = urllib.parse.unquote(parsed.username or "")
        self.password = urllib.parse.unquote(parsed.password or "")
        self.database = database

    def __str__(self) -> str:
        # What is safe to print, and what every error message here uses.
        return f"{self.user}@{self.host}:{self.port}/{self.database}"

    __repr__ = __str__


def _driver() -> Any:
    try:
        import pymysql  # noqa: PLC0415 — optional: only the publish path needs it
    except ImportError as exc:  # pragma: no cover — exercised by absence, not by CI
        raise StoreError(
            "the MariaDB store needs PyMySQL, which is not installed; "
            "`pip install PyMySQL` in the job that publishes"
        ) from exc
    return pymysql


class MariaDBResultStore:
    """Result storage in MariaDB, partitioned by tenant."""

    def __init__(self, dsn: str, connect_timeout: int = 10) -> None:
        self.dsn = Dsn(dsn)
        self.connect_timeout = connect_timeout

    # -------------------------------------------------------------- internals

    def _connect(self) -> Any:
        pymysql = _driver()
        try:
            return pymysql.connect(
                host=self.dsn.host,
                port=self.dsn.port,
                user=self.dsn.user,
                password=self.dsn.password,
                database=self.dsn.database,
                charset="utf8mb4",
                autocommit=False,
                connect_timeout=self.connect_timeout,
                cursorclass=pymysql.cursors.DictCursor,
            )
        except Exception as exc:  # noqa: BLE001 — every driver failure is one refusal
            raise StoreError(f"cannot connect to {self.dsn}: {type(exc).__name__}") from exc

    @staticmethod
    def _insert(cursor: Any, table: str, rows: list[dict[str, Any]], ignore: bool = False) -> None:
        if not rows:
            return
        columns = list(rows[0])
        placeholders = ", ".join(["%s"] * len(columns))
        names = ", ".join(f"`{c}`" for c in columns)
        verb = "INSERT IGNORE" if ignore else "INSERT"
        # Column names come from rows.py, never from a payload; only values are
        # parameterised because only values are caller-influenced.
        cursor.executemany(
            f"{verb} INTO `{table}` ({names}) VALUES ({placeholders})",
            [tuple(row[c] for c in columns) for row in rows],
        )

    # ------------------------------------------------------------------ admin

    def init_schema(self) -> list[str]:
        """Apply schema.sql. Safe to re-run; returns the statements applied."""
        applied = statements_in(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                for statement in applied:
                    cursor.execute(statement)
            connection.commit()
        finally:
            connection.close()
        return applied

    def health(self) -> dict[str, Any]:
        """Whether this store can be reached and written to.

        Reports rather than raises: a pipeline calls this to decide whether to
        publish at all, and an unreachable database is an answer, not a crash.
        """
        try:
            connection = self._connect()
        except StoreError as exc:
            return {
                "store": "mariadb",
                "target": str(self.dsn),
                "writable": False,
                "detail": str(exc),
            }
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION() AS version")
                version = (cursor.fetchone() or {}).get("version", "")
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = 'assessments'",
                    (self.dsn.database,),
                )
                ready = bool((cursor.fetchone() or {}).get("n"))
            return {
                "store": "mariadb",
                "target": str(self.dsn),
                "writable": ready,
                "server_version": version,
                "detail": "" if ready else "the schema is not applied; run `ironclad store init`",
            }
        finally:
            connection.close()

    # ------------------------------------------------------------------ write

    def put_assessment(self, document: dict[str, Any]) -> str:
        rows = rows_from_document(document)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._put(cursor, rows)
            connection.commit()
        except Exception as exc:
            # All or nothing. Half an assessment reads as a client who lost
            # thirty controls, which is worse than a failed publish.
            connection.rollback()
            if isinstance(exc, StoreError):
                raise
            raise StoreError(
                f"storing {rows.assessment_id} in {self.dsn} failed: {type(exc).__name__}"
            ) from exc
        finally:
            connection.close()
        return rows.assessment_id

    def _put(self, cursor: Any, rows: RowSet) -> None:
        tenant = rows.tenants[0]
        cursor.execute(
            "INSERT INTO tenants (tenant_id, name) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE name = VALUES(name)",
            (tenant["tenant_id"], tenant["name"]),
        )

        # Idempotent on assessment_id: the child rows cascade away with the old
        # assessment row, so a re-run replaces its own record exactly and never
        # leaves half of a previous run behind.
        cursor.execute(
            "DELETE FROM assessments WHERE assessment_id = %s AND tenant_id = %s",
            (rows.assessment_id, rows.tenant_id),
        )
        self._insert(cursor, "assessments", rows.assessments)
        self._insert(cursor, "assessment_controls", rows.assessment_controls)
        self._insert(cursor, "control_evidence", rows.control_evidence)
        self._insert(cursor, "remediation_items", rows.remediation_items)
        self._insert(cursor, "findings", rows.findings)
        # Append-only: never deleted with the assessment, never updated, and
        # inserted with IGNORE so re-publishing stores each event once.
        self._insert(cursor, "audit_events", rows.audit_events, ignore=True)

    # ------------------------------------------------------------------- read

    def _query(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
        finally:
            connection.close()

    def get_assessment(self, tenant_id: str, assessment_id: str) -> dict[str, Any] | None:
        # Tenant in the WHERE clause, always. An id alone would be enough to
        # find the row, and that is exactly the query that leaks across tenants.
        found = self._query(
            "SELECT * FROM assessments WHERE tenant_id = %s AND assessment_id = %s",
            (tenant_id, assessment_id),
        )
        return found[0] if found else None

    def list_assessments(self, tenant_id: str, limit: int = 25) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM assessments WHERE tenant_id = %s ORDER BY started_at DESC LIMIT %s",
            (tenant_id, int(limit)),
        )

    def list_controls(self, tenant_id: str, assessment_id: str) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM assessment_controls WHERE tenant_id = %s AND assessment_id = %s "
            "ORDER BY control_id",
            (tenant_id, assessment_id),
        )

    def list_remediation(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM remediation_items WHERE tenant_id = %s "
            "ORDER BY priority ASC, due_date ASC LIMIT %s",
            (tenant_id, int(limit)),
        )

    def list_audit(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        events = self._query(
            "SELECT * FROM audit_events WHERE tenant_id = %s ORDER BY id DESC LIMIT %s",
            (tenant_id, int(limit)),
        )
        return list(reversed(events))

    def verify_audit_chain(self, tenant_id: str) -> dict[str, Any]:
        """Re-verify the stored chain rather than trusting it.

        The digests are stored verbatim, so a chain that was sound when written
        stays sound unless something edited the table. This is how that is found
        out — and it is the free integrity check on any restore from backup.
        """
        events = self._query(
            "SELECT * FROM audit_events WHERE tenant_id = %s ORDER BY id", (tenant_id,)
        )
        previous = ""
        for index, event in enumerate(events):
            if index and event.get("prev_hash") != previous:
                return {
                    "tenant_id": tenant_id,
                    "events": len(events),
                    "verified": False,
                    "broken_at": event.get("event_id"),
                    "detail": "prev_hash does not match the previous event's hash",
                }
            previous = str(event.get("hash", ""))
        return {
            "tenant_id": tenant_id,
            "events": len(events),
            "verified": True,
            "broken_at": None,
            "detail": "",
        }


def statements_in(sql: str) -> list[str]:
    """The executable statements in a SQL file.

    Comments are stripped *before* splitting on the separator, because a comment
    may contain one — this schema's own header says "Applied by `ironclad store
    init`; safe to re-run", and splitting first hands the server the second half
    of that sentence as a statement.
    """
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [statement.strip() for statement in body.split(";") if statement.strip()]


def dsn_summary(url: str) -> str:
    """A DSN with its password removed, for a log line or an error."""
    return str(Dsn(url))
