"""The command line: one entry point for every surface that drives the engine.

    ironclad list-modules
    ironclad list-frameworks
    ironclad validate --framework soc2 --manifest evidence/manifest.json
    ironclad assess --client acme --framework soc2 --evidence-dir evidence/ \\
        --group deep --out out/
    ironclad report --input out/assessment.json --out out/report.html
    ironclad export --input out/assessment.json --format package --out out/package/
    ironclad crosswalk --from soc2 --to hipaa

`assess` writes three files into --out: assessment.json (the full result),
findings.b64 (the base64 findings the AI consensus engine's workflow_call input
expects) and report.html. The workflow reads all three; nothing has to
re-serialize the result in shell.

Exit codes: 0 success, 2 bad input or selection, 3 a capability failed mid-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ironclad import registry
from ironclad.engine import merge_consensus, run_assessment
from ironclad.errors import IroncladError, SelectionError, ValidationError
from ironclad.frameworks.crosswalk import load_crosswalks
from ironclad.frameworks.loader import (
    FRAMEWORK_ALIASES,
    available_frameworks,
    load_framework,
    validate_framework_document,
)
from ironclad.ids import slugify
from ironclad.ingest import collect_from_directory, validate_manifest
from ironclad.report.export import (
    export_audit_package,
    export_control_register_csv,
    export_json,
    export_remediation_csv,
)
from ironclad.report.render import render_html
from ironclad.version import __version__

EXIT_OK = 0
EXIT_BAD_INPUT = 2
EXIT_PARTIAL = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ironclad",
        description="Iron City compliance evidence engine.",
    )
    parser.add_argument("--version", action="version", version=f"ironclad {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-modules", help="print the capability catalog as JSON")
    sub.add_parser("list-frameworks", help="print the available frameworks as JSON")

    validate = sub.add_parser("validate", help="validate a framework and/or an evidence manifest")
    validate.add_argument("--framework", help="framework alias or path to validate")
    validate.add_argument("--manifest", help="path to an evidence manifest to validate")

    assess = sub.add_parser("assess", help="run an assessment")
    assess.add_argument("--client", required=True, help="client identifier (multi-tenant)")
    assess.add_argument("--framework", required=True, help=f"one of {sorted(FRAMEWORK_ALIASES)}")
    assess.add_argument("--evidence-dir", required=True, help="directory of collected evidence")
    selection = assess.add_mutually_exclusive_group()
    selection.add_argument("--modules", help="comma list of capabilities to run")
    selection.add_argument("--group", help="named group: quick | standard | deep")
    assess.add_argument("--assessment-type", default="full",
                        choices=("full", "gap-only", "readiness"))
    assess.add_argument("--assessment-id", default="", help="override the generated id")
    assess.add_argument("--consensus-b64", default="",
                        help="base64 consensus output to fold into the result")
    assess.add_argument("--out", default="out", help="output directory")

    report = sub.add_parser("report", help="render an HTML report from a stored result")
    report.add_argument("--input", required=True, help="assessment.json from a previous run")
    report.add_argument("--out", required=True, help="path to write the report to")
    report.add_argument("--client-name", default="", help="display name for the client")

    export = sub.add_parser("export", help="export a stored result")
    export.add_argument("--input", required=True)
    export.add_argument("--format", default="json", choices=("json", "csv", "package"))
    export.add_argument("--out", required=True)

    crosswalk = sub.add_parser("crosswalk", help="show the mapping between two frameworks")
    crosswalk.add_argument("--from", dest="source", required=True)
    crosswalk.add_argument("--to", dest="target", required=True)

    return parser


def _emit(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def cmd_list_modules() -> int:
    reg = registry.discover()
    _emit({"modules": registry.catalog(reg), "groups": sorted(registry.all_groups(reg))})
    return EXIT_OK


def cmd_list_frameworks() -> int:
    _emit({"frameworks": available_frameworks()})
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    problems: dict[str, list[str]] = {}

    if args.framework:
        path = Path(args.framework)
        if path.suffix == ".json" and path.exists():
            document = json.loads(path.read_text(encoding="utf-8"))
            problems["framework"] = validate_framework_document(document)
        else:
            try:
                load_framework(args.framework)
                problems["framework"] = []
            except ValidationError as exc:
                problems["framework"] = exc.errors or [str(exc)]
            except IroncladError as exc:
                problems["framework"] = [str(exc)]

    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            problems["manifest"] = [f"{manifest_path} does not exist"]
        else:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            problems["manifest"] = validate_manifest(document)

    if not problems:
        print("nothing to validate: pass --framework and/or --manifest", file=sys.stderr)
        return EXIT_BAD_INPUT

    ok = all(not errors for errors in problems.values())
    _emit({"valid": ok, "problems": problems})
    return EXIT_OK if ok else EXIT_BAD_INPUT


def cmd_assess(args: argparse.Namespace) -> int:
    tenant = slugify(args.client)
    evidence_dir = Path(args.evidence_dir)
    if not evidence_dir.is_dir():
        print(f"evidence directory not found: {evidence_dir}", file=sys.stderr)
        return EXIT_BAD_INPUT

    evidence, ingest_warnings = collect_from_directory(tenant, evidence_dir, args.framework)

    result = run_assessment(
        tenant_id=tenant,
        framework=args.framework,
        evidence=evidence,
        modules=[m.strip() for m in args.modules.split(",")] if args.modules else None,
        group=args.group,
        crosswalk=load_crosswalks(),
        assessment_type=args.assessment_type,
        assessment_id=args.assessment_id,
    )
    result.warnings.extend(ingest_warnings)

    if args.consensus_b64:
        merge_consensus(result, args.consensus_b64)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "assessment.json").write_text(export_json(result), encoding="utf-8")
    (out / "findings.b64").write_text(result.consensus_payload(), encoding="utf-8")
    (out / "report.html").write_text(render_html(result, args.client), encoding="utf-8")

    summary = result.assessment.summary
    print(
        f"assessment {result.assessment.assessment_id}: "
        f"readiness {summary.readiness_score}% "
        f"({summary.compliant} met, {summary.partial} partial, {summary.gap} not met, "
        f"{summary.accepted_risk} accepted) "
        f"from {summary.evidence_artifacts} evidence item(s), "
        f"{len(result.plan)} remediation item(s)",
        file=sys.stderr,
    )
    for warning in result.warnings:
        print(f"  warning: {warning}", file=sys.stderr)
    for name, detail in result.failed_modules.items():
        print(f"  capability {name} failed: {detail}", file=sys.stderr)

    return EXIT_OK if result.ok else EXIT_PARTIAL


def cmd_report(args: argparse.Namespace) -> int:
    result = _StoredResult(json.loads(Path(args.input).read_text(encoding="utf-8")))
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(result, args.client_name), encoding="utf-8")
    print(f"report written: {output}", file=sys.stderr)
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    result = _StoredResult(json.loads(Path(args.input).read_text(encoding="utf-8")))
    output = Path(args.out)

    if args.format == "json":
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(export_json(result), encoding="utf-8")
    elif args.format == "csv":
        output.mkdir(parents=True, exist_ok=True)
        (output / "control-register.csv").write_text(
            export_control_register_csv(result), encoding="utf-8"
        )
        (output / "remediation-plan.csv").write_text(
            export_remediation_csv(result), encoding="utf-8"
        )
    else:
        export_audit_package(result, result.evidence, output)

    print(f"exported {args.format}: {output}", file=sys.stderr)
    return EXIT_OK


def cmd_crosswalk(args: argparse.Namespace) -> int:
    crosswalk = load_crosswalks()
    source = load_framework(args.source)
    target = load_framework(args.target)

    mappings = []
    for control in source.controls:
        edges = crosswalk.map_control(source.id, control.id, target.id)
        for edge in edges:
            mappings.append(
                {
                    "source_control": control.id,
                    "source_name": control.name,
                    "target_control": edge.target_control,
                    "relationship": str(edge.relationship),
                    "note": edge.note,
                }
            )

    target_ids = [c.id for c in target.controls]
    _emit(
        {
            "source": source.to_dict(),
            "target": target.to_dict(),
            "coverage": crosswalk.coverage(source.id, target.id, target_ids),
            "unmapped_target_controls": sorted(
                set(target_ids) - {m["target_control"] for m in mappings}
            ),
            "mappings": mappings,
        }
    )
    return EXIT_OK


class _StoredResult:
    """Rehydrate just enough of a RunResult to render and export a stored one.

    The report and export commands run in a separate job from the assessment, so
    they read the stored JSON rather than a live object. Only the fields the
    renderer and exporters touch are rebuilt.
    """

    def __init__(self, document: dict) -> None:
        from ironclad.frameworks.loader import load_framework as _load  # noqa: PLC0415
        from ironclad.model.assessment import (  # noqa: PLC0415
            Assessment,
            AssessmentSummary,
            ControlAssessment,
            ControlStatus,
        )
        from ironclad.model.audit import AuditLog  # noqa: PLC0415
        from ironclad.model.evidence import EvidenceArtifact, EvidenceSet  # noqa: PLC0415
        from ironclad.model.remediation import (  # noqa: PLC0415
            RemediationItem,
            RemediationPlan,
            RemediationStatus,
            Severity,
        )

        self.raw = document
        tenant = document.get("tenant_id") or document.get("client_id", "")
        framework_meta = document.get("framework", {})

        try:
            framework = _load(framework_meta.get("id", ""))
        except IroncladError:
            # A stored result must stay renderable even if the framework file
            # has since moved or been renamed; the report only needs its label.
            from ironclad.model.control import Framework  # noqa: PLC0415

            framework = Framework(
                id=framework_meta.get("id", ""),
                name=framework_meta.get("name", "Compliance framework"),
                version=framework_meta.get("version", ""),
                source=framework_meta.get("source", ""),
            )

        assessment = Assessment(
            assessment_id=document.get("assessment_id", ""),
            tenant_id=tenant,
            framework=framework,
            assessment_type=document.get("assessment_type", "full"),
            modules_run=list(document.get("modules_run", [])),
            consensus=document.get("consensus") or {},
        )
        summary_raw = document.get("summary", {})
        summary = AssessmentSummary(**{
            key: summary_raw[key] for key in AssessmentSummary().__dict__ if key in summary_raw
        })
        assessment.summary = summary

        for raw in document.get("controls", []):
            item = ControlAssessment(
                control_id=raw.get("control_id", ""),
                control_name=raw.get("control_name", ""),
                status=ControlStatus(raw.get("status", "pending")),
                rationale=raw.get("rationale", ""),
                points_covered=raw.get("points_covered", 0),
                points_total=raw.get("points_total", 0),
                weight=raw.get("weight", 1.0),
                confidence=raw.get("confidence", 0.0),
                exception_id=raw.get("exception_id", ""),
                notes=list(raw.get("notes", [])),
            )
            for link_raw in raw.get("evidence_links", []):
                from ironclad.model.evidence import EvidenceLink, LinkMethod  # noqa: PLC0415

                item.evidence_links.append(
                    EvidenceLink(
                        control_id=link_raw.get("control_id", ""),
                        artifact_id=link_raw.get("artifact_id", ""),
                        method=LinkMethod(link_raw.get("method", "automated")),
                        relevance=link_raw.get("relevance", 0.0),
                        linked_by=link_raw.get("linked_by", ""),
                    )
                )
            assessment.controls.append(item)

        self.assessment = assessment

        remediation_raw = document.get("remediation", {})
        plan = RemediationPlan(
            tenant_id=tenant, assessment_id=assessment.assessment_id
        )
        for raw in remediation_raw.get("items", []):
            plan.add(
                RemediationItem(
                    item_id=raw.get("item_id", ""),
                    tenant_id=tenant,
                    control_id=raw.get("control_id", ""),
                    control_name=raw.get("control_name", ""),
                    title=raw.get("title", ""),
                    guidance=raw.get("guidance", ""),
                    severity=Severity(raw.get("severity", "medium")),
                    status=RemediationStatus(raw.get("status", "open")),
                    priority=raw.get("priority", 0.0),
                    owner=raw.get("owner", ""),
                    due_date=_parse(raw.get("due_date")),
                    evidence_gap=list(raw.get("evidence_gap", [])),
                )
            )
        self.plan = plan

        evidence = EvidenceSet(tenant_id=tenant)
        inventory = (document.get("module_output", {}).get("evidence_inventory") or {})
        for raw in inventory.get("artifacts", []):
            evidence.add(
                EvidenceArtifact(
                    artifact_id=raw.get("artifact_id", ""),
                    tenant_id=tenant,
                    name=raw.get("name", ""),
                    uri=raw.get("uri", ""),
                    evidence_type=raw.get("evidence_type", ""),
                    sha256=raw.get("sha256", ""),
                    size_bytes=raw.get("size_bytes", 0),
                    collected_at=_parse(raw.get("collected_at")) or assessment.started_at,
                    valid_until=_parse(raw.get("valid_until")),
                )
            )
        self.evidence = evidence

        self.audit = AuditLog(tenant_id=tenant)
        self.module_output = document.get("module_output", {})
        self.warnings = list(document.get("warnings", []))
        self.failed_modules = dict(document.get("failed_modules", {}))

    def to_dict(self) -> dict:
        return self.raw


def _parse(value: object):  # type: ignore[no-untyped-def]
    from datetime import datetime  # noqa: PLC0415

    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    handlers = {
        "list-modules": lambda: cmd_list_modules(),
        "list-frameworks": lambda: cmd_list_frameworks(),
        "validate": lambda: cmd_validate(args),
        "assess": lambda: cmd_assess(args),
        "report": lambda: cmd_report(args),
        "export": lambda: cmd_export(args),
        "crosswalk": lambda: cmd_crosswalk(args),
    }

    try:
        return handlers[args.command]()
    except SelectionError as exc:
        print(f"selection error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except ValidationError as exc:
        print(f"validation error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except IroncladError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
