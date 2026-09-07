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
import os
import sys
from pathlib import Path
from typing import Any

from ironclad import registry
from ironclad.api.policy_store import PolicyStore
from ironclad.api.schemas import ExceptionRequest
from ironclad.api.service import ComplianceService
from ironclad.compare import compare as compare_assessments
from ironclad.engine import merge_consensus, run_assessment
from ironclad.errors import IroncladError, SelectionError, ValidationError
from ironclad.evidence_root import stage_evidence
from ironclad.frameworks.crosswalk import load_crosswalks
from ironclad.frameworks.loader import (
    FRAMEWORK_ALIASES,
    available_frameworks,
    load_framework,
    validate_framework_document,
)
from ironclad.ids import slugify
from ironclad.ingest import collect_from_directory, validate_manifest
from ironclad.model.tenant import Principal, Role
from ironclad.policy import find_policy, load_policy, validate_policy
from ironclad.report.export import (
    export_audit_package,
    export_control_register_csv,
    export_json,
    export_remediation_csv,
)
from ironclad.report.render import render_html
from ironclad.report.views import ASSESSMENT_TYPES, DEFAULT_VIEW, view_for
from ironclad.store import ArtifactStore, store_from_target, target_summary
from ironclad.version import __version__

#: Where results are published, when --to is not given. An environment variable
#: because the value is a DSN and a DSN carries a password: a command line ends
#: up in a process list, a shell history and a CI log.
STORE_ENV = "IRONCLAD_STORE"

#: The evidence volume. One prefix per tenant beneath it.
EVIDENCE_ROOT_ENV = "IRONCLAD_EVIDENCE_ROOT"

#: The artifact volume: reports and auditor packages. Separate from the record
#: store because a database is the wrong place for a 300 KB HTML document, and a
#: volume is the wrong place to query a readiness score from. Defaults to the
#: record store's own root when that store is already a volume.
ARTIFACT_ROOT_ENV = "IRONCLAD_ARTIFACTS"

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
    validate.add_argument("--policy", help="path to a tenant policy to validate")

    assess = sub.add_parser("assess", help="run an assessment")
    assess.add_argument("--client", required=True, help="client identifier (multi-tenant)")
    assess.add_argument("--framework", required=True, help=f"one of {sorted(FRAMEWORK_ALIASES)}")
    assess.add_argument("--evidence-dir", required=True, help="directory of collected evidence")
    selection = assess.add_mutually_exclusive_group()
    selection.add_argument("--modules", help="comma list of capabilities to run")
    selection.add_argument("--group", help="named group: quick | standard | deep")
    assess.add_argument(
        "--assessment-type",
        default=DEFAULT_VIEW,
        choices=ASSESSMENT_TYPES,
        help="which deliverable to issue; the assessment itself is always complete",
    )
    assess.add_argument("--assessment-id", default="", help="override the generated id")
    assess.add_argument(
        "--policy",
        default="",
        help="tenant policy: scope exclusions, risk acceptances, control owners. "
        "Defaults to policy.json inside --evidence-dir when one is present.",
    )
    assess.add_argument(
        "--consensus-b64", default="", help="base64 consensus output to fold into the result"
    )
    assess.add_argument("--out", default="out", help="output directory")

    report = sub.add_parser("report", help="render an HTML report from a stored result")
    report.add_argument("--input", required=True, help="assessment.json from a previous run")
    report.add_argument("--out", required=True, help="path to write the report to")
    report.add_argument("--client-name", default="", help="display name for the client")
    report.add_argument(
        "--view",
        default="",
        choices=("", *ASSESSMENT_TYPES),
        help=(
            "re-issue the stored assessment as a different deliverable; "
            "defaults to the type the assessment was run as"
        ),
    )

    export = sub.add_parser("export", help="export a stored result")
    export.add_argument("--input", required=True)
    export.add_argument("--format", default="json", choices=("json", "csv", "package"))
    export.add_argument("--out", required=True)

    crosswalk = sub.add_parser("crosswalk", help="show the mapping between two frameworks")
    crosswalk.add_argument("--from", dest="source", required=True)
    crosswalk.add_argument("--to", dest="target", required=True)

    evidence_cmd = sub.add_parser(
        "evidence",
        help="stage a tenant's evidence from a NAS-backed volume",
        description=(
            "Evidence lives on a volume, one prefix per tenant: <root>/<client>/. "
            "This stages a tenant's own prefix into a working directory, refusing "
            "anything that resolves outside it — a traversal, or a symlink planted "
            "in one tenant's tree pointing at another's."
        ),
    )
    evidence_sub = evidence_cmd.add_subparsers(dest="evidence_command", required=True)
    evidence_fetch = evidence_sub.add_parser("stage", help="copy a tenant's evidence locally")
    evidence_fetch.add_argument(
        "--root", default="", help="evidence volume root; defaults to $IRONCLAD_EVIDENCE_ROOT"
    )
    evidence_fetch.add_argument("--client", required=True, help="client identifier")
    evidence_fetch.add_argument("--out", required=True, help="directory to stage into")

    compare = sub.add_parser(
        "compare",
        help="what changed between two assessments",
        description=(
            "A compliance programme is a trend, not a snapshot. Give two stored "
            "results, or a client and a store, and this reports what moved: "
            "readiness, which controls improved or regressed, which remediation "
            "items closed and which opened. A control scoped out is reported as a "
            "scope change, never as an improvement."
        ),
    )
    compare.add_argument("--from", dest="earlier", default="", help="the earlier assessment.json")
    compare.add_argument("--to", dest="later", default="", help="the later assessment.json")
    compare.add_argument("--client", default="", help="compare a tenant's two most recent")
    compare.add_argument(
        "--store", default="", help="store to read from; defaults to $IRONCLAD_STORE"
    )

    store = sub.add_parser(
        "store",
        help="publish a stored result, or prepare and check a store",
        description=(
            "Where a finished assessment goes. --to names the store: a path or "
            "file:// for a NAS-backed volume, mysql:// or mariadb:// for MariaDB. "
            "A DSN carries a password, so pass it through the environment "
            "(IRONCLAD_STORE) rather than on a command line that ends up in a "
            "process list and a shell history."
        ),
    )
    store_sub = store.add_subparsers(dest="store_command", required=True)

    def with_target(parser_: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser_.add_argument(
            "--to",
            default="",
            help="store target; defaults to $IRONCLAD_STORE",
        )
        return parser_

    with_target(store_sub.add_parser("health", help="can this store be written to?"))
    with_target(store_sub.add_parser("init", help="apply the schema (MariaDB only)"))

    store_publish = with_target(store_sub.add_parser("publish", help="store one result"))
    store_publish.add_argument("--input", required=True, help="assessment.json from a run")
    store_publish.add_argument(
        "--artifacts",
        default="",
        help=(
            "directory of deliverables to store on the artifact volume "
            f"(${ARTIFACT_ROOT_ENV}); the report and the auditor package"
        ),
    )

    store_verify = with_target(
        store_sub.add_parser("verify", help="re-checksum a stored assessment's deliverables")
    )
    store_verify.add_argument("--client", required=True)
    store_verify.add_argument("--assessment-id", required=True)

    store_list = with_target(store_sub.add_parser("list", help="list stored assessments"))
    store_list.add_argument("--client", required=True, help="tenant to list for")
    store_list.add_argument("--limit", type=int, default=25)

    exception = sub.add_parser(
        "exception",
        help="the risk-acceptance workflow, against a tenant policy file",
        description=(
            "Request, approve and revoke risk acceptances. Every step runs through "
            "the same service the API uses, so the permission checks and the "
            "separation-of-duties rule hold here exactly as they do there, and each "
            "step is written to a hash-chained trail beside the policy file. The "
            "acceptance lands in policy.json, which is what the next assessment reads."
        ),
    )
    exception_sub = exception.add_subparsers(dest="exception_command", required=True)

    def with_actor(parser_: argparse.ArgumentParser) -> argparse.ArgumentParser:
        # Who is doing this is not optional. The audit trail is the point, and an
        # unattributed approval is worth nothing to an auditor.
        parser_.add_argument("--policy", required=True, help="path to the tenant policy file")
        parser_.add_argument("--actor", required=True, help="user id taking this action")
        parser_.add_argument(
            "--role",
            action="append",
            default=[],
            choices=[str(r) for r in Role],
            help="the actor's role; repeat for more than one",
        )
        return parser_

    ex_list = with_actor(exception_sub.add_parser("list", help="list the acceptances on file"))
    ex_list.add_argument("--status", default="", help="filter by workflow status")

    ex_request = with_actor(exception_sub.add_parser("request", help="raise an acceptance"))
    ex_request.add_argument("--control", required=True, help="control id being accepted")
    ex_request.add_argument("--justification", required=True, help="why the risk is accepted")
    ex_request.add_argument(
        "--compensating",
        action="append",
        default=[],
        help="a compensating control; repeat for more than one",
    )
    ex_request.add_argument("--expires-in-days", type=int, default=90)

    ex_approve = with_actor(exception_sub.add_parser("approve", help="approve an acceptance"))
    ex_approve.add_argument("--id", dest="exception_id", required=True)

    ex_revoke = with_actor(exception_sub.add_parser("revoke", help="revoke an acceptance"))
    ex_revoke.add_argument("--id", dest="exception_id", required=True)
    ex_revoke.add_argument("--reason", required=True, help="why it is being revoked")

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

    if args.policy:
        policy_path = Path(args.policy)
        if not policy_path.exists():
            problems["policy"] = [f"{policy_path} does not exist"]
        else:
            document = json.loads(policy_path.read_text(encoding="utf-8"))
            faults = validate_policy(document)
            if not faults:
                # Structural validity is not enough: an acceptance can still be
                # one the approval workflow refuses, such as a self-approval.
                try:
                    load_policy(policy_path)
                except ValidationError as exc:
                    faults = exc.errors or [str(exc)]
            problems["policy"] = faults

    if not problems:
        print(
            "nothing to validate: pass --framework, --manifest and/or --policy",
            file=sys.stderr,
        )
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

    # An explicit --policy must exist; one discovered beside the evidence is a
    # convenience, and its absence is not an error.
    policy = None
    policy_path: Path | None = None
    if args.policy:
        policy_path = Path(args.policy)
        if not policy_path.exists():
            print(f"tenant policy not found: {policy_path}", file=sys.stderr)
            return EXIT_BAD_INPUT
    else:
        policy_path = find_policy(evidence_dir)
    if policy_path is not None:
        policy = load_policy(policy_path, expected_tenant=tenant)

    result = run_assessment(
        tenant_id=tenant,
        framework=args.framework,
        evidence=evidence,
        policy=policy,
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
    if policy is not None:
        print(
            f"  policy: {policy_path} "
            f"({len(policy.exclusions)} scope exclusion(s), "
            f"{len(policy.exceptions)} risk acceptance(s))",
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
    # A stored result carries the type it was run as; --view re-issues the same
    # assessment as a different deliverable without re-running anything.
    view = view_for(args.view) if args.view else None
    output.write_text(render_html(result, args.client_name, view=view), encoding="utf-8")
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


def cmd_evidence(args: argparse.Namespace) -> int:
    """Stage a tenant's evidence from the volume into a working directory."""
    root = args.root or os.environ.get(EVIDENCE_ROOT_ENV, "")
    if not root:
        print(
            f"no evidence root: pass --root or set {EVIDENCE_ROOT_ENV}",
            file=sys.stderr,
        )
        return EXIT_BAD_INPUT

    staged = stage_evidence(root, args.client, Path(args.out))
    print(
        f"staged {staged.file_count} evidence file(s) for {staged.tenant_id} into {args.out}",
        file=sys.stderr,
    )
    _emit(
        {
            "tenant_id": staged.tenant_id,
            "prefix": str(staged.path),
            "files": staged.file_count,
            "staged_to": str(args.out),
        }
    )
    return EXIT_OK


def cmd_compare(args: argparse.Namespace) -> int:
    """Compare two assessments: two files, or a tenant's two most recent."""
    if args.earlier and args.later:
        earlier = json.loads(Path(args.earlier).read_text(encoding="utf-8"))
        later = json.loads(Path(args.later).read_text(encoding="utf-8"))
    elif args.client:
        target = args.store or os.environ.get(STORE_ENV, "")
        if not target:
            print(f"no store target: pass --store or set {STORE_ENV}", file=sys.stderr)
            return EXIT_BAD_INPUT
        store = store_from_target(target)
        reader = getattr(store, "get_document", None)
        if reader is None:
            print(
                "this store keeps the projected rows, not the whole document, so it "
                "cannot be compared from; pass --from and --to instead",
                file=sys.stderr,
            )
            return EXIT_BAD_INPUT
        recent = store.list_assessments(args.client, limit=2)
        if len(recent) < 2:
            print(
                f"{args.client} has {len(recent)} stored assessment(s); two are needed to compare",
                file=sys.stderr,
            )
            return EXIT_BAD_INPUT
        # list_assessments is most recent first.
        later = reader(args.client, str(recent[0]["assessment_id"]))
        earlier = reader(args.client, str(recent[1]["assessment_id"]))
    else:
        print("give --from and --to, or --client", file=sys.stderr)
        return EXIT_BAD_INPUT

    comparison = compare_assessments(earlier, later)
    _emit(comparison.to_dict())
    print(comparison.headline(), file=sys.stderr)
    for caveat in comparison.caveats:
        print(f"  caveat: {caveat}", file=sys.stderr)
    return EXIT_OK


def cmd_store(args: argparse.Namespace) -> int:
    """Publish to, prepare or check a result store.

    This is what replaces POSTing to a Cloud Function. The engine writes its
    result to disk either way; this decides where that result comes to rest.
    """
    target = args.to or os.environ.get(STORE_ENV, "")
    if not target:
        print(
            f"no store target: pass --to or set {STORE_ENV} "
            "(a path or file:// for a volume, mysql:// for MariaDB)",
            file=sys.stderr,
        )
        return EXIT_BAD_INPUT

    store = store_from_target(target)
    where = target_summary(target)

    if args.store_command == "health":
        health = store.health()
        _emit(health)
        # Exit non-zero on an unwritable store so a pipeline stops before it
        # produces a result it cannot publish.
        return EXIT_OK if health.get("writable") else EXIT_BAD_INPUT

    if args.store_command == "init":
        initialiser = getattr(store, "init_schema", None)
        if initialiser is None:
            print(f"{where} needs no schema", file=sys.stderr)
            return EXIT_OK
        statements = initialiser()
        print(f"applied {len(statements)} statement(s) to {where}", file=sys.stderr)
        return EXIT_OK

    if args.store_command == "verify":
        artifacts = _artifact_store(args, store)
        if artifacts is None:
            print(
                f"no artifact volume: pass --to a volume or set {ARTIFACT_ROOT_ENV}",
                file=sys.stderr,
            )
            return EXIT_BAD_INPUT
        verdict = artifacts.verify(args.client, args.assessment_id)
        _emit({"location": artifacts.location(args.client, args.assessment_id), **verdict})
        return EXIT_OK if verdict["verified"] else EXIT_BAD_INPUT

    if args.store_command == "list":
        _emit(
            {
                "store": where,
                "tenant_id": args.client,
                "assessments": store.list_assessments(args.client, args.limit),
            }
        )
        return EXIT_OK

    source = Path(args.input)
    if not source.exists():
        print(f"result not found: {source}", file=sys.stderr)
        return EXIT_BAD_INPUT
    document = json.loads(source.read_text(encoding="utf-8"))
    assessment_id = store.put_assessment(document)
    print(f"stored {assessment_id} in {where}", file=sys.stderr)

    published: dict[str, Any] = {
        "store": where,
        "assessment_id": assessment_id,
        "status": "stored",
    }

    if args.artifacts:
        artifacts = _artifact_store(args, store)
        if artifacts is None:
            print(
                f"--artifacts needs a volume: set {ARTIFACT_ROOT_ENV}, or publish to one",
                file=sys.stderr,
            )
            return EXIT_BAD_INPUT
        tenant = str(document.get("tenant_id") or document.get("client_id") or "")
        stored = artifacts.put(tenant, assessment_id, Path(args.artifacts))
        location = artifacts.location(tenant, assessment_id)
        print(f"stored {len(stored)} deliverable(s) at {location}", file=sys.stderr)
        published["artifacts"] = {
            "location": location,
            "files": [a.to_dict() for a in stored],
        }

    _emit(published)
    return EXIT_OK


def _artifact_store(args: argparse.Namespace, record_store: Any) -> ArtifactStore | None:
    """The artifact volume, explicit or inherited from a volume record store."""
    root = os.environ.get(ARTIFACT_ROOT_ENV, "")
    if root:
        return ArtifactStore(Path(root))
    # A volume-only deployment keeps both on one volume, and the layouts are
    # chosen so that works without a second root.
    own_root = getattr(record_store, "root", None)
    return ArtifactStore(own_root) if own_root is not None else None


def cmd_exception(args: argparse.Namespace) -> int:
    """The risk-acceptance workflow, driven through the service.

    Nothing here reimplements a rule. The permission checks, the state machine
    and the separation-of-duties rule all live below this, so the CLI and a
    future HTTP surface cannot drift apart on who may accept what.
    """
    store = PolicyStore(Path(args.policy))
    tenant = store.tenant_id()
    if not tenant:
        print(
            f"{args.policy} names no tenant_id; "
            "a risk acceptance belongs to a client, not to a file",
            file=sys.stderr,
        )
        return EXIT_BAD_INPUT

    caller = Principal(
        user_id=args.actor,
        tenant_id=tenant,
        roles=frozenset(Role(r) for r in args.role),
    )
    service = ComplianceService(store=store)

    if args.exception_command == "list":
        response = service.list_exceptions(caller, tenant, args.status)
    elif args.exception_command == "request":
        response = service.request_exception(
            caller,
            ExceptionRequest(
                tenant_id=tenant,
                control_id=args.control,
                justification=args.justification,
                requested_by=args.actor,
                compensating_controls=list(args.compensating),
                expires_in_days=args.expires_in_days,
            ),
        )
    elif args.exception_command == "approve":
        response = service.approve_exception(caller, tenant, args.exception_id)
    else:
        response = service.revoke_exception(caller, tenant, args.exception_id, args.reason)

    if not response.ok:
        for error in response.errors:
            print(f"refused: {error}", file=sys.stderr)
        return EXIT_BAD_INPUT

    _emit(response.data)
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
        summary = AssessmentSummary(
            **{key: summary_raw[key] for key in AssessmentSummary().__dict__ if key in summary_raw}
        )
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
        plan = RemediationPlan(tenant_id=tenant, assessment_id=assessment.assessment_id)
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
        inventory = document.get("module_output", {}).get("evidence_inventory") or {}
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
        "evidence": lambda: cmd_evidence(args),
        "compare": lambda: cmd_compare(args),
        "store": lambda: cmd_store(args),
        "exception": lambda: cmd_exception(args),
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
