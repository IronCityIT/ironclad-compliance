"""Exports.

Three audiences, three shapes:

  json     the machine record — everything, for storage and for the dashboard
  csv      the control register and the remediation plan, for the spreadsheet
           that a compliance team actually works from
  package  the auditor evidence package: the register, the plan, the evidence
           index and the audit trail, laid out as files an auditor can be handed

The evidence package deliberately exports references and checksums, never the
evidence bytes. The artifacts stay in the tenant's own storage; the package is
the index that proves which artifact supported which control at what time.

The report inside the package is the deliverable as issued, so an assessment run
as a gap analysis carries a gap analysis. The CSVs are always complete: the
package is an audit artifact, and an auditor asking why a control was judged met
must not be handed a file that omitted it.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from ironclad.ids import iso, utc_now
from ironclad.report.views import view_for
from ironclad.version import __version__

EXPORT_FORMATS = ("json", "csv", "package")


def export_json(result: Any, indent: int = 2) -> str:
    """The full result document as JSON text, newline-terminated."""
    return json.dumps(result.to_dict(), indent=indent, sort_keys=False) + "\n"


def export_control_register_csv(result: Any, evidence: Any = None) -> str:
    """One row per control: the register a compliance team works from.

    `evidence` is optional. Supplied, the last column names the supporting
    documents; omitted, it carries their ids, which still resolve against
    evidence-index.csv.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "control_id",
            "control_name",
            "status",
            "points_evidenced",
            "points_total",
            "coverage",
            "evidence_items",
            "confidence",
            "weight",
            "exception_id",
            "rationale",
            "evidence_names",
        ]
    )
    evidence_names = {a.artifact_id: a.name for a in evidence} if evidence is not None else {}

    for item in result.assessment.controls:
        names = [
            evidence_names.get(link.artifact_id, link.artifact_id) for link in item.evidence_links
        ]
        writer.writerow(
            [
                item.control_id,
                item.control_name,
                str(item.status),
                item.points_covered,
                item.points_total,
                round(item.coverage, 3),
                len(item.evidence_links),
                round(item.confidence, 3),
                item.weight,
                item.exception_id,
                item.rationale,
                "; ".join(names),
            ]
        )
    return buffer.getvalue()


def export_remediation_csv(result: Any) -> str:
    """One row per remediation item, in priority order."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "item_id",
            "control_id",
            "control_name",
            "severity",
            "priority",
            "status",
            "owner",
            "due_date",
            "evidence_required",
            "guidance",
        ]
    )
    for item in result.plan.ordered():
        writer.writerow(
            [
                item.item_id,
                item.control_id,
                item.control_name,
                str(item.severity),
                item.priority,
                str(item.status),
                item.owner,
                item.due_date.date().isoformat() if item.due_date else "",
                "; ".join(item.evidence_gap),
                item.guidance,
            ]
        )
    return buffer.getvalue()


def export_evidence_index_csv(result: Any, evidence: Any) -> str:
    """Which artifact supported which control, and how the link was made."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "control_id",
            "artifact_id",
            "artifact_name",
            "evidence_type",
            "uri",
            "sha256",
            "collected_at",
            "valid_until",
            "stale",
            "link_method",
            "relevance",
            "linked_by",
        ]
    )
    for item in result.assessment.controls:
        for link in item.evidence_links:
            artifact = evidence.get(link.artifact_id)
            writer.writerow(
                [
                    item.control_id,
                    link.artifact_id,
                    artifact.name if artifact else "",
                    artifact.evidence_type if artifact else "",
                    artifact.uri if artifact else "",
                    artifact.sha256 if artifact else "",
                    iso(artifact.collected_at) if artifact else "",
                    iso(artifact.effective_valid_until) if artifact else "",
                    "yes" if artifact and artifact.is_stale() else "no",
                    str(link.method),
                    round(link.relevance, 3),
                    link.linked_by,
                ]
            )
    return buffer.getvalue()


def export_audit_trail_csv(result: Any) -> str:
    """The hash-chained audit log, flattened."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["event_id", "at", "actor", "action", "object_type", "object_id", "hash"])
    for event in result.audit.events:
        writer.writerow(
            [
                event.event_id,
                iso(event.at),
                event.actor,
                event.action,
                event.object_type,
                event.object_id,
                event.hash,
            ]
        )
    return buffer.getvalue()


def export_audit_package(result: Any, evidence: Any, destination: Path) -> list[Path]:
    """Write the full auditor package to a directory. Returns the files written.

    The package is self-describing: README.txt states what each file is and,
    just as importantly, what the package does not contain, so nobody assumes
    the evidence itself travelled with it.
    """
    destination.mkdir(parents=True, exist_ok=True)
    assessment = result.assessment

    written: list[Path] = []

    def write(name: str, content: str) -> None:
        path = destination / name
        path.write_text(content, encoding="utf-8")
        written.append(path)

    write("assessment.json", export_json(result))
    write("control-register.csv", export_control_register_csv(result, evidence))
    write("remediation-plan.csv", export_remediation_csv(result))
    write("evidence-index.csv", export_evidence_index_csv(result, evidence))
    write("audit-trail.csv", export_audit_trail_csv(result))
    write("report.html", _render(result))

    manifest = {
        "package_version": "1.0",
        "engine_version": __version__,
        "generated_at": iso(utc_now()),
        "assessment_id": assessment.assessment_id,
        "tenant_id": assessment.tenant_id,
        "framework": assessment.framework.to_dict(),
        "readiness_score": assessment.summary.readiness_score,
        "assessment_type": assessment.assessment_type,
        "report_view": view_for(assessment.assessment_type).to_dict(),
        "audit_chain_head": result.audit.head,
        "audit_chain_verified": result.audit.is_valid(),
        "files": sorted(p.name for p in written) + ["package.json"],
    }
    write("package.json", json.dumps(manifest, indent=2) + "\n")

    view_name = view_for(assessment.assessment_type).name
    write(
        "README.txt",
        f"""Compliance evidence package
{assessment.framework.name} ({assessment.framework.version})
Assessment {assessment.assessment_id} — generated {iso(utc_now())}

  report.html           the deliverable as issued ({view_name})
  assessment.json       the complete machine-readable result
  control-register.csv  one row per control, with its position and rationale
  remediation-plan.csv  outstanding work, in priority order, with target dates
  evidence-index.csv    which evidence item supported which control, and how
  audit-trail.csv       the hash-chained record of this assessment
  package.json          package manifest, including the audit chain head

THE CSV FILES ARE COMPLETE
report.html is the deliverable as issued and may be abridged — a gap analysis
lists only the controls with outstanding work. The CSV files below are never
abridged: control-register.csv carries every control that was assessed, whatever
the report shows.

WHAT THIS PACKAGE DOES NOT CONTAIN
The evidence files themselves. evidence-index.csv references each item by its
storage location and SHA-256 checksum; the items remain in the client's own
storage. Verify an item by checksum against the reference in the index.

The audit trail is hash-chained: each entry carries the digest of the one before
it. package.json records the chain head at the time of export. Altering or
removing an entry breaks every digest that follows it.

Prepared by Iron City IT Advisors. Confidential.
""",
    )
    return written


def _render(result: Any) -> str:
    # Imported here rather than at module scope: export.py is imported by the
    # storage path, which has no reason to pull in the renderer.
    from ironclad.report.render import render_html  # noqa: PLC0415

    return render_html(result)
