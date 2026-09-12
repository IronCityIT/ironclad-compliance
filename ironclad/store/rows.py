"""A result document, flattened into tenant-scoped records.

The engine's model is already relational in shape, so this is a projection
rather than a redesign. Everything here is pure: a document in, lists of dicts
out, no storage and no I/O. That is what lets one set of tests cover every
backend, and what lets the transport decision change without the shape of the
data changing with it.

Three rules the projection enforces, because they are the ones a backend would
otherwise each have to remember:

**Every row carries `tenant_id`.** Not because a table needs it, but because a
row without one cannot be filtered and a filter is the whole of the tenant
partition.

**Evidence bytes never appear.** Only a reference and a checksum. The artifacts
stay in the client's own storage; what is stored here is the index that proves
which artifact supported which control at what time.

**The audit chain keeps its order and its digests.** Events are numbered as they
were recorded and carry `prev_hash` unchanged, so a chain read back out of any
store verifies exactly as it did when it was written — or names where it does
not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The width of every bounded column, read from schema.sql at import.
#:
#: Derived rather than declared: the DDL is the storage contract, and a second
#: copy of these numbers in Python is a copy that will disagree with it one day.
#: Columns are per table because the same name means different things in
#: different tables — `method` is a 32-character link method in one and a
#: LONGTEXT block in another.
#: Table names, in the order rows must be written: parents before children, so
#: a foreign key is never dangling mid-write and a partial failure leaves no
#: orphan detail.
TABLES = (
    "tenants",
    "assessments",
    "assessment_controls",
    "control_evidence",
    "remediation_items",
    "findings",
    "audit_events",
)


@dataclass
class RowSet:
    """The rows one assessment document becomes."""

    tenant_id: str
    assessment_id: str
    tenants: list[dict[str, Any]] = field(default_factory=list)
    assessments: list[dict[str, Any]] = field(default_factory=list)
    assessment_controls: list[dict[str, Any]] = field(default_factory=list)
    control_evidence: list[dict[str, Any]] = field(default_factory=list)
    remediation_items: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    audit_events: list[dict[str, Any]] = field(default_factory=list)

    def table(self, name: str) -> list[dict[str, Any]]:
        if name not in TABLES:
            raise KeyError(f"unknown table {name!r}")
        rows: list[dict[str, Any]] = getattr(self, name)
        return rows

    def counts(self) -> dict[str, int]:
        return {name: len(self.table(name)) for name in TABLES}

    def total(self) -> int:
        return sum(self.counts().values())


_COLUMN = re.compile(r"^\s*`?(\w+)`?\s+VARCHAR\((\d+)\)", re.IGNORECASE)
_TABLE = re.compile(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+`?(\w+)`?", re.IGNORECASE)


def _bounds_from_ddl(sql: str) -> dict[str, dict[str, int]]:
    """Every VARCHAR width in the schema, keyed by table then column."""
    bounds: dict[str, dict[str, int]] = {}
    table = ""
    for line in sql.splitlines():
        if line.lstrip().startswith("--"):
            continue
        heading = _TABLE.search(line)
        if heading:
            table = heading.group(1)
            bounds.setdefault(table, {})
            continue
        column = _COLUMN.match(line)
        if column and table:
            bounds[table][column.group(1)] = int(column.group(2))
    return bounds


SCHEMA_PATH = Path(__file__).with_name("schema.sql")
BOUNDS: dict[str, dict[str, int]] = _bounds_from_ddl(SCHEMA_PATH.read_text(encoding="utf-8"))


def _text(value: Any) -> str:
    """Coerce to text. Bounds are checked once, at the end, against BOUNDS."""
    return "" if value is None else str(value)


def _json(value: Any) -> str:
    """A nested structure, stored as JSON text.

    Used only where the shape is genuinely open — a capability's own output, an
    audit event's metadata — never for anything that has to be queried or
    filtered. Anything a query needs is a column.
    """
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def _check_bounds(rows: RowSet) -> None:
    """Refuse anything the store could not hold without shortening it.

    A value that will not fit is refused, never truncated. Truncating an id
    silently changes which record is written; truncating a control name silently
    alters what a client is told. Both look like a successful store, and both
    are found only when somebody notices a name ending mid-word.

    Checked here so every backend refuses identically, rather than each one
    depending on whether its database happens to run in a strict mode.
    """
    for table in TABLES:
        limits = BOUNDS.get(table, {})
        for row in rows.table(table):
            for column, value in row.items():
                limit = limits.get(column)
                if limit is not None and isinstance(value, str) and len(value) > limit:
                    raise ValueError(
                        f"{table}.{column} is {len(value)} characters, longer than the "
                        f"{limit} the store holds: {value[:40]!r}…"
                    )


def rows_from_document(document: dict[str, Any]) -> RowSet:
    """Project one `assessment.json` document onto the storage schema.

    Refuses a document with no tenant or no assessment id: both are the record's
    identity, and a store that invented either would file a client's result
    somewhere nobody would look for it.
    """
    tenant_id = _text(document.get("tenant_id") or document.get("client_id")).strip()
    assessment_id = _text(document.get("assessment_id")).strip()
    if not tenant_id:
        raise ValueError("the result document names no tenant_id")
    if not assessment_id:
        raise ValueError("the result document names no assessment_id")

    rows = RowSet(tenant_id=tenant_id, assessment_id=assessment_id)
    framework = document.get("framework") or {}
    summary = document.get("summary") or {}

    rows.tenants.append(
        {
            "tenant_id": tenant_id,
            "name": _text(document.get("client_name") or document.get("client_id") or tenant_id),
        }
    )

    rows.assessments.append(
        {
            "assessment_id": assessment_id,
            "tenant_id": tenant_id,
            "framework_id": _text(framework.get("id")),
            "framework_name": _text(framework.get("name")),
            "framework_version": _text(framework.get("version")),
            "assessment_type": _text(document.get("assessment_type") or "full"),
            "status": _text(document.get("status") or "completed"),
            "engine_version": _text(document.get("engine_version")),
            "contract_version": _text(document.get("contract_version")),
            "started_at": _text(document.get("started_at")),
            "completed_at": _text(document.get("completed_at")),
            "readiness_score": float(summary.get("readiness_score") or 0.0),
            "total_controls": int(summary.get("total_controls") or 0),
            "compliant": int(summary.get("compliant") or 0),
            "partial": int(summary.get("partial") or 0),
            "gap": int(summary.get("gap") or 0),
            "accepted_risk": int(summary.get("accepted_risk") or 0),
            "not_applicable": int(summary.get("not_applicable") or 0),
            "pending": int(summary.get("pending") or 0),
            "evidence_artifacts": int(summary.get("evidence_artifacts") or 0),
            "stale_artifacts": int(summary.get("stale_artifacts") or 0),
            "modules_run": _json(document.get("modules_run") or []),
            "warnings": _json(document.get("warnings") or []),
            "failed_modules": _json(document.get("failed_modules") or {}),
            "consensus": _json(document.get("consensus")),
            "method": _json(document.get("method") or {}),
            "module_output": _json(document.get("module_output") or {}),
            "audit_chain_head": _text((document.get("audit") or {}).get("head")),
            "report_url": _text(document.get("report_url")),
        }
    )

    for control in document.get("controls") or []:
        control_id = _text(control.get("control_id"))
        rows.assessment_controls.append(
            {
                "assessment_id": assessment_id,
                "tenant_id": tenant_id,
                "control_id": control_id,
                "control_name": _text(control.get("control_name")),
                "status": _text(control.get("status")),
                "rationale": _text(control.get("rationale")),
                "points_covered": int(control.get("points_covered") or 0),
                "points_total": int(control.get("points_total") or 0),
                "coverage": float(control.get("coverage") or 0.0),
                "confidence": float(control.get("confidence") or 0.0),
                "weight": float(control.get("weight") or 1.0),
                "evidence_count": int(control.get("evidence_count") or 0),
                "exception_id": _text(control.get("exception_id")),
                "assessed_at": _text(control.get("assessed_at")),
                "assessed_by": _text(control.get("assessed_by")),
                "notes": _json(control.get("notes") or []),
            }
        )

        for link in control.get("evidence_links") or []:
            # A reference and a checksum. Never the evidence itself.
            rows.control_evidence.append(
                {
                    "assessment_id": assessment_id,
                    "tenant_id": tenant_id,
                    "control_id": control_id,
                    "artifact_id": _text(link.get("artifact_id")),
                    "method": _text(link.get("method")),
                    "relevance": float(link.get("relevance") or 0.0),
                    "linked_by": _text(link.get("linked_by")),
                    "linked_at": _text(link.get("linked_at")),
                    "matched_terms": _json(link.get("matched_terms") or []),
                    "note": _text(link.get("note")),
                }
            )

    remediation = document.get("remediation") or {}
    for item in remediation.get("items") or []:
        rows.remediation_items.append(
            {
                "item_id": _text(item.get("item_id")),
                "assessment_id": assessment_id,
                "tenant_id": tenant_id,
                "control_id": _text(item.get("control_id")),
                "control_name": _text(item.get("control_name")),
                "title": _text(item.get("title")),
                "severity": _text(item.get("severity")),
                "priority": int(item.get("priority") or 0),
                "status": _text(item.get("status")),
                "owner": _text(item.get("owner")),
                "due_date": _text(item.get("due_date")),
                "guidance": _text(item.get("guidance")),
                "evidence_gap": _json(item.get("evidence_gap") or []),
                "exception_id": _text(item.get("exception_id")),
                "source": _text(item.get("source")),
                "created_at": _text(item.get("created_at")),
            }
        )

    for index, finding in enumerate(document.get("findings") or []):
        rows.findings.append(
            {
                "assessment_id": assessment_id,
                "tenant_id": tenant_id,
                "ordinal": index,
                "module": _text(finding.get("module")),
                "severity": _text(finding.get("severity")),
                "title": _text(finding.get("title")),
                "target": _text(finding.get("target")),
                "detail": _text(finding.get("detail")),
                "evidence": _json(finding.get("evidence") or []),
            }
        )

    audit = document.get("audit") or {}
    for ordinal, event in enumerate(audit.get("events") or []):
        # event_id, prev_hash and hash are carried through untouched: the chain
        # has to verify out of the store exactly as it verified going in.
        rows.audit_events.append(
            {
                "tenant_id": tenant_id,
                "assessment_id": assessment_id,
                "event_id": _text(event.get("event_id")),
                "ordinal": ordinal,
                "actor": _text(event.get("actor")),
                "action": _text(event.get("action")),
                "object_type": _text(event.get("object_type")),
                "object_id": _text(event.get("object_id")),
                "at": _text(event.get("at")),
                "metadata": _json(event.get("metadata") or {}),
                "prev_hash": _text(event.get("prev_hash")),
                "hash": _text(event.get("hash")),
            }
        )

    _check_bounds(rows)
    return rows
