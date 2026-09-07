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
from dataclasses import dataclass, field
from typing import Any

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


def _text(value: Any, limit: int = 0) -> str:
    text = "" if value is None else str(value)
    return text[:limit] if limit and len(text) > limit else text


def _json(value: Any) -> str:
    """A nested structure, stored as JSON text.

    Used only where the shape is genuinely open — a capability's own output, an
    audit event's metadata — never for anything that has to be queried or
    filtered. Anything a query needs is a column.
    """
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


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
            "name": _text(
                document.get("client_name") or document.get("client_id") or tenant_id, 255
            ),
        }
    )

    rows.assessments.append(
        {
            "assessment_id": assessment_id,
            "tenant_id": tenant_id,
            "framework_id": _text(framework.get("id"), 64),
            "framework_name": _text(framework.get("name"), 255),
            "framework_version": _text(framework.get("version"), 64),
            "assessment_type": _text(document.get("assessment_type") or "full", 32),
            "status": _text(document.get("status") or "completed", 32),
            "engine_version": _text(document.get("engine_version"), 32),
            "contract_version": _text(document.get("contract_version"), 32),
            "started_at": _text(document.get("started_at"), 64),
            "completed_at": _text(document.get("completed_at"), 64),
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
            "audit_chain_head": _text((document.get("audit") or {}).get("head"), 128),
            "report_url": _text(document.get("report_url"), 512),
        }
    )

    for control in document.get("controls") or []:
        control_id = _text(control.get("control_id"), 128)
        rows.assessment_controls.append(
            {
                "assessment_id": assessment_id,
                "tenant_id": tenant_id,
                "control_id": control_id,
                "control_name": _text(control.get("control_name"), 255),
                "status": _text(control.get("status"), 32),
                "rationale": _text(control.get("rationale")),
                "points_covered": int(control.get("points_covered") or 0),
                "points_total": int(control.get("points_total") or 0),
                "coverage": float(control.get("coverage") or 0.0),
                "confidence": float(control.get("confidence") or 0.0),
                "weight": float(control.get("weight") or 1.0),
                "evidence_count": int(control.get("evidence_count") or 0),
                "exception_id": _text(control.get("exception_id"), 64),
                "assessed_at": _text(control.get("assessed_at"), 64),
                "assessed_by": _text(control.get("assessed_by"), 128),
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
                    "artifact_id": _text(link.get("artifact_id"), 128),
                    "method": _text(link.get("method"), 32),
                    "relevance": float(link.get("relevance") or 0.0),
                    "linked_by": _text(link.get("linked_by"), 128),
                    "linked_at": _text(link.get("linked_at"), 64),
                    "matched_terms": _json(link.get("matched_terms") or []),
                    "note": _text(link.get("note")),
                }
            )

    remediation = document.get("remediation") or {}
    for item in remediation.get("items") or []:
        rows.remediation_items.append(
            {
                "item_id": _text(item.get("item_id"), 128),
                "assessment_id": assessment_id,
                "tenant_id": tenant_id,
                "control_id": _text(item.get("control_id"), 128),
                "control_name": _text(item.get("control_name"), 255),
                "title": _text(item.get("title"), 255),
                "severity": _text(item.get("severity"), 32),
                "priority": int(item.get("priority") or 0),
                "status": _text(item.get("status"), 32),
                "owner": _text(item.get("owner"), 128),
                "due_date": _text(item.get("due_date"), 64),
                "guidance": _text(item.get("guidance")),
                "evidence_gap": _json(item.get("evidence_gap") or []),
                "exception_id": _text(item.get("exception_id"), 64),
                "source": _text(item.get("source"), 64),
                "created_at": _text(item.get("created_at"), 64),
            }
        )

    for index, finding in enumerate(document.get("findings") or []):
        rows.findings.append(
            {
                "assessment_id": assessment_id,
                "tenant_id": tenant_id,
                "ordinal": index,
                "module": _text(finding.get("module"), 64),
                "severity": _text(finding.get("severity"), 32),
                "title": _text(finding.get("title"), 255),
                "target": _text(finding.get("target"), 255),
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
                "event_id": _text(event.get("event_id"), 64),
                "ordinal": ordinal,
                "actor": _text(event.get("actor"), 128),
                "action": _text(event.get("action"), 128),
                "object_type": _text(event.get("object_type"), 64),
                "object_id": _text(event.get("object_id"), 255),
                "at": _text(event.get("at"), 64),
                "metadata": _json(event.get("metadata") or {}),
                "prev_hash": _text(event.get("prev_hash"), 128),
                "hash": _text(event.get("hash"), 128),
            }
        )

    return rows
