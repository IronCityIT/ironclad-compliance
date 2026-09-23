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
import hashlib
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
    """The hash-chained audit log, flattened.

    Every field the digest covers is a column, so the chain can be recomputed
    from this file alone by the rule the package README states. Without
    tenant_id, metadata and prev_hash it could only be checked by reading this
    repository (PRODUCTIZE_NOTES §16.47). The three were added after `hash` so
    no existing column moved.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "event_id",
            "at",
            "actor",
            "action",
            "object_type",
            "object_id",
            "hash",
            "tenant_id",
            "prev_hash",
            "metadata",
        ]
    )
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
                event.tenant_id,
                event.prev_hash,
                json.dumps(event.metadata, sort_keys=True, separators=(",", ":")),
            ]
        )
    return buffer.getvalue()


def export_audit_package(
    result: Any, evidence: Any, destination: Path, issued_report: Path | None = None
) -> list[Path]:
    """Write the full auditor package to a directory. Returns the files written.

    The package is self-describing: README.txt states what each file is and,
    just as importantly, what the package does not contain, so nobody assumes
    the evidence itself travelled with it.

    `issued_report` is the report as it was actually issued. The package's
    `report.html` used to be re-rendered here from the stored result, which
    is the same document until the issued one carries something the result
    does not — the "Since the last assessment" section, rendered against the
    previous assessment. The first pipeline run with a trend produced two
    different reports: one issued, one in the package labelled "the
    deliverable as issued" (PRODUCTIZE_NOTES §16.31). Given the file, the
    package carries it byte for byte, so the checksums agree too.
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
    if issued_report is not None:
        report_bytes = Path(issued_report).read_bytes()
        (destination / "report.html").write_bytes(report_bytes)
        written.append(destination / "report.html")
    else:
        write("report.html", _render(result))

    # Every file the package carries, checksummed, so the auditor who receives
    # it can tell whether it is the package that was issued. The audit chain
    # already protects the trail; it says nothing about control-register.csv,
    # which is the file that carries the verdicts. The first version of this
    # package listed the file names and nothing else.
    checksums = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(written)
    }

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
        # Whether report.html is the file the client received, or a re-render
        # from the result, which cannot reproduce it: the stored result has no
        # display name (PRODUCTIZE_NOTES §16.47).
        "report": "issued" if issued_report is not None else "re-rendered",
        "audit_chain_head": result.audit.head,
        "audit_chain_verified": result.audit.is_valid(),
        "files": sorted(checksums) + ["package.json", "README.txt", "SHA256SUMS"],
        "sha256": checksums,
    }
    write("package.json", json.dumps(manifest, indent=2) + "\n")

    view_name = view_for(assessment.assessment_type).name
    if issued_report is not None:
        report_line = f"the deliverable as issued ({view_name})"
        report_note = "report.html is the deliverable as issued and may be abridged"
    else:
        report_line = f"re-rendered at export ({view_name}); NOT the issued file"
        report_note = (
            "report.html was re-rendered from assessment.json when this package was\n"
            "exported; it is not the file issued to the client, and names the client\n"
            "by its identifier. It may be abridged"
        )
    write(
        "README.txt",
        f"""Compliance evidence package
{assessment.framework.name} ({assessment.framework.version})
Assessment {assessment.assessment_id} — generated {iso(utc_now())}

  report.html           {report_line}
  assessment.json       the complete machine-readable result
  control-register.csv  one row per control, with its position and rationale
  remediation-plan.csv  outstanding work, in priority order, with target dates
  evidence-index.csv    which evidence item supported which control, and how
  audit-trail.csv       the hash-chained record of this assessment
  package.json          package manifest, including the audit chain head
  SHA256SUMS            a checksum for every other file in this package

IS THIS THE PACKAGE THAT WAS ISSUED?
Run `sha256sum -c SHA256SUMS` in this directory (or `shasum -a 256 -c` on
macOS, or `Get-FileHash` on Windows and compare). Every line must read OK. A
file that has been altered since export, or is missing, is named. package.json
carries the same digests under "sha256".

THE CSV FILES ARE COMPLETE
{report_note} — a gap analysis
lists only the controls with outstanding work. The CSV files below are never
abridged: control-register.csv carries every control that was assessed, whatever
the report shows.

WHAT THIS PACKAGE DOES NOT CONTAIN
The evidence files themselves. evidence-index.csv references each item by its
storage location and SHA-256 checksum; the items remain in the client's own
storage. Verify an item by checksum against the reference in the index.

The audit trail is hash-chained: each entry carries the digest of the one before
it (prev_hash). package.json records the chain head at the time of export.
Altering or removing an entry breaks every digest that follows it.

HOW TO VERIFY THE AUDIT TRAIL
Each row's hash is the SHA-256, in lowercase hex, of a JSON object with the
keys event_id, tenant_id, actor, action, object_type, object_id, at, metadata
and prev_hash, taken from that row. metadata is itself JSON, parsed and
embedded as a value. The object is written with its keys sorted, no spaces
("," and ":" as separators), with every character outside ASCII written as a
\\uXXXX escape (as Python's json.dumps does by default; jq and JavaScript
do not, and would compute a different digest), then UTF-8 encoded. The first
row's prev_hash is 64 zeros
(0000000000000000000000000000000000000000000000000000000000000000);
every later row's prev_hash is the hash of the row before it, and the last
row's hash is the audit_chain_head in package.json.

Prepared by Iron City IT Advisors. Confidential.
""",
    )

    # Last, over everything else, in the format `sha256sum -c` reads. The file
    # cannot contain its own digest, which is why package.json carries the
    # others as well: two records of the same facts, each checkable.
    write(
        "SHA256SUMS",
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in sorted(written)
        ),
    )
    return written


def _render(result: Any) -> str:
    # Imported here rather than at module scope: export.py is imported by the
    # storage path, which has no reason to pull in the renderer.
    from ironclad.report.render import render_html  # noqa: PLC0415

    return render_html(result)
