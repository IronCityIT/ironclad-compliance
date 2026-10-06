"""The command line: one entry point for every surface that drives the engine.

    ironclad list-modules
    ironclad list-frameworks
    ironclad validate --framework soc2 --manifest evidence/manifest.json
    ironclad assess --client acme --framework soc2 --evidence-dir evidence/ \\
        --group deep --out out/
    ironclad report --input out/assessment.json --out out/report.html
    ironclad export --input out/assessment.json --format package --out out/package/
    ironclad crosswalk --from soc2 --to hipaa
    ironclad oversight attention --tenant sage-spine --actor a --role auditor --fail-on high
    ironclad oversight export --tenant sage-spine --actor a --role auditor --out out/
    ironclad oversight access --tenant sage-spine --actor a --role auditor \
        --tokens tokens.json --fail-on high

`assess` writes three files into --out: assessment.json (the full result),
findings.b64 (the base64 findings the AI consensus engine's workflow_call input
expects) and report.html. The workflow reads all three; nothing has to
re-serialize the result in shell.

Exit codes: 0 success, 2 bad input or selection, 3 a capability failed mid-run,
4 a register check found something (`oversight verify`, `attention --fail-on`,
`access --fail-on`, `compare-seals`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from ironclad import oversight, registry
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
from ironclad.ids import client_slug, is_safe_document_id, slugify
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
#: A register check ran and found something: a broken history, or a review
#: queue holding what `--fail-on` names. Distinct from bad input, so a
#: scheduled sweep can tell "look at the register" from "fix the job".
EXIT_FINDINGS = 4


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
    assess.add_argument(
        "--previous",
        default="",
        help=(
            "the tenant's previous stored assessment (from `ironclad store latest`): a "
            "remediation item it still carries keeps its first-raised and target dates "
            "instead of starting its clock again today"
        ),
    )
    assess.add_argument("--out", default="out", help="output directory")

    report = sub.add_parser("report", help="render an HTML report from a stored result")
    report.add_argument("--input", required=True, help="assessment.json from a previous run")
    report.add_argument("--out", required=True, help="path to write the report to")
    report.add_argument("--client-name", default="", help="display name for the client")
    report.add_argument(
        "--compare-to",
        dest="compare_to",
        default="",
        help="a previous assessment.json; adds a 'since the last assessment' section",
    )
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
    export.add_argument(
        "--report",
        default="",
        help=(
            "the report as issued (package format only): carried into the package byte "
            "for byte instead of re-rendered, so the package holds the deliverable the "
            "client received — including a trend section rendered against a previous "
            "assessment, which a re-render from the stored result cannot reproduce"
        ),
    )

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

    store_latest = with_target(
        store_sub.add_parser(
            "latest",
            help="write a tenant's most recent stored assessment to a file, for --compare-to",
            description=(
                "The previous assessment, so the next report can say what moved since. "
                "Filtered to one framework: a SOC 2 report compared against last quarter's "
                "HIPAA assessment is not a trend, and the comparison would say so rather than "
                "show one. Exit 0 and the file when there is one; exit 3 and no file when the "
                "tenant has none yet, which a pipeline treats as 'first assessment', not as "
                "an error."
            ),
        )
    )
    store_latest.add_argument("--client", required=True)
    store_latest.add_argument("--framework", required=True, help="framework alias, e.g. soc2")
    store_latest.add_argument("--out", required=True, help="where to write the document")
    store_latest.add_argument(
        "--before",
        default="",
        help="skip this assessment id — the one being produced now, if already stored",
    )

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

    register = sub.add_parser(
        "oversight",
        help="the partner/integration register: review queue, integrity sweep, seeding",
        description=(
            "The tenant's register of partners and integrations, on the result "
            "store, for whatever does not hold a browser session: a scheduled BAA "
            "sweep, an auditor's integrity check, loading a tenant's seed. Every "
            "command runs as a named actor with roles, through the same policy "
            "`ironclad serve` enforces; the tenant comes from --tenant (or the "
            "seed), and the actor may act only in that tenant."
        ),
    )
    register_sub = register.add_subparsers(dest="oversight_command", required=True)

    def with_register_actor(parser_: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser_.add_argument("--to", default="", help=f"result store; defaults to ${STORE_ENV}")
        parser_.add_argument("--actor", required=True, help="user id taking this action")
        parser_.add_argument(
            "--role",
            action="append",
            default=[],
            choices=[str(r) for r in Role],
            help="the actor's role; repeat for more than one",
        )
        return parser_

    attention = with_register_actor(
        register_sub.add_parser("attention", help="print the review queue as JSON")
    )
    attention.add_argument("--tenant", required=True)
    attention.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today in UTC")
    attention.add_argument(
        "--fail-on",
        choices=("never", "high", "any"),
        default="never",
        help=f"exit {EXIT_FINDINGS} when the queue holds a high finding, or any finding",
    )

    register_access = with_register_actor(
        register_sub.add_parser(
            "access",
            help="hold every live service token to the register record it acts for",
            description=(
                "Reads a token file (never a token) and, for each entry in --tenant "
                "that works as of --as-of and names a record with `on_behalf_of`, "
                "looks the record up. High: the record is missing or retired, or still "
                "at Pending information, or it "
                "handles PHI without an executed BAA, claims a BAA without its "
                "evidence or dated after --as-of, or has a lapsed review or "
                "assurance: a partner holding "
                "access the register says it should not. High too: the token has no "
                "expires_at. Notice: the relationship is offboarding, or the token "
                "runs past its next review or its assurance expiry. Entries "
                "without a link are listed under `unlinked`, not judged. "
                f"Exit {EXIT_FINDINGS} under --fail-on, {EXIT_BAD_INPUT} for an "
                "unreadable token file."
            ),
        )
    )
    register_access.add_argument("--tenant", required=True)
    register_access.add_argument("--tokens", required=True, help="the token file `serve` reads")
    register_access.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today in UTC")
    register_access.add_argument(
        "--fail-on",
        choices=("never", "high", "any"),
        default="never",
        help=f"exit {EXIT_FINDINGS} when a holder has a high finding, or any finding",
    )

    register_export = with_register_actor(
        register_sub.add_parser(
            "export",
            help="write the whole register as CSV, with its review-queue findings",
            description=(
                "The inventory an auditor asks for when listing business associates: "
                "every record of both kinds, retired ones included, one row each with "
                "the review queue's findings as of --as-of. The same file the "
                "dashboard's download writes. Prints the file name, row counts and "
                "the SHA-256 of what was written."
            ),
        )
    )
    register_export.add_argument("--tenant", required=True)
    register_export.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today in UTC")
    register_export.add_argument(
        "--out",
        required=True,
        help="the CSV file to write (a directory: named for tenant and date)",
    )

    register_packet = with_register_actor(
        register_sub.add_parser(
            "review-packet",
            help="file the tenant's access review as one hashed packet",
            description=(
                "Takes every part of the access review as of one date and files it as a "
                "new directory under --out: the register export, the review queue, "
                "partner tokens held to their records, the register's history check and "
                "seal, and the token review cut down to this tenant (with its use from "
                "--access-log and its grants from --ledger). With --ledger it also lists "
                "the tenant's grants and revocations in the period (since --previous's "
                "date, or up to this one); a grant to its own issuer is a notice. "
                "manifest.json names each "
                "file's SHA-256, and its summary lists each high finding and notice with "
                "the file it is in; its `digest` is the line to record elsewhere, which "
                f"`verify-packet --digest` checks later. With --previous, the last "
                "packet is re-verified and continuity.json holds its seal and anchors "
                "against today's register and chains; anything since rewritten or cut "
                f"is a high finding. Exit {EXIT_FINDINGS} under "
                "--fail-on, or with nothing written when a log or ledger is not a whole "
                f"chain; {EXIT_BAD_INPUT} for unreadable input, an existing packet, or a "
                "previous packet that does not verify, is another tenant's or is not earlier."
            ),
        )
    )
    register_packet.add_argument("--tenant", required=True)
    register_packet.add_argument("--tokens", required=True, help="the token file `serve` reads")
    register_packet.add_argument(
        "--access-log",
        action="append",
        default=[],
        help=(
            "the server's access log, for each entry's use; repeat it for rotated "
            "archives, oldest first, ending with the current log"
        ),
    )
    register_packet.add_argument(
        "--ledger", default="", help="the grant ledger, to hold each entry to its grant"
    )
    register_packet.add_argument(
        "--dormant-days",
        type=int,
        default=90,
        help="with --access-log: an active entry unused this long is a notice",
    )
    register_packet.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today in UTC")
    register_packet.add_argument(
        "--out", required=True, help="an existing directory; the packet is a new one inside it"
    )
    register_packet.add_argument(
        "--previous",
        default="",
        help="the tenant's last filed packet: file continuity.json against it",
    )
    register_packet.add_argument(
        "--previous-digest",
        default="",
        help="with --previous: the digest recorded when it was filed",
    )
    register_packet.add_argument(
        "--fail-on",
        choices=("never", "high", "any"),
        default="never",
        help=f"exit {EXIT_FINDINGS} (after filing) on a high finding, or on any finding",
    )

    verify_packet = register_sub.add_parser(
        "verify-packet",
        help="re-hash a filed access-review packet against its manifest",
        description=(
            "For whoever holds a filed packet and no store: every file listed with its "
            "hash and size, nothing unlisted, the manifest matching its own digest and, "
            "with --digest, the digest recorded when it was filed. Exit "
            f"{EXIT_FINDINGS} if anything differs, {EXIT_BAD_INPUT} if it is not a packet."
        ),
    )
    verify_packet.add_argument("packet", help="the packet directory")
    verify_packet.add_argument(
        "--digest", default="", help="the manifest digest recorded when the packet was filed"
    )
    verify_packet.add_argument(
        "--previous", default="", help="the packet this one must have been built against"
    )

    register_verify = with_register_actor(
        register_sub.add_parser(
            "verify",
            help="re-check every record's change history",
            description=(
                "Walks every record with a record or any history in both registers "
                "and re-checks it: revisions 1..n without a gap, one tenant, one "
                f"creation stamp, the record equal to its last entry. Exit {EXIT_FINDINGS} "
                "if any record fails, and the JSON says which and why."
            ),
        )
    )
    register_verify.add_argument("--tenant", required=True)
    register_verify.add_argument(
        "--seal",
        default="",
        help=(
            "a seal taken earlier with `oversight seal`; the store must still hold every "
            f"sealed entry unchanged, or exit {EXIT_FINDINGS}"
        ),
    )

    register_seal = with_register_actor(
        register_sub.add_parser(
            "seal",
            help="print a digest of every history entry, to keep outside the store",
            description=(
                "`verify` checks a history against itself, so an entry rewritten in "
                "place, or on a volume a latest revision deleted, passes it. A seal "
                "taken now and kept elsewhere is the anchor: `verify --seal` or "
                "`compare-seals` later says whether anything sealed has changed."
            ),
        )
    )
    register_seal.add_argument("--tenant", required=True)

    compare = register_sub.add_parser(
        "compare-seals",
        help="check that a later seal extends an earlier one, without a store",
        description=(
            "For an auditor who takes seals over `ironclad serve` and holds no "
            "store access. Every record sealed earlier must still be there with "
            "the same entries; new revisions and records are expected. Exit "
            f"{EXIT_FINDINGS} if anything sealed changed, {EXIT_BAD_INPUT} if either "
            "seal is malformed or does not match its own digest."
        ),
    )
    compare.add_argument("--earlier", required=True, help="the seal taken first")
    compare.add_argument("--later", required=True, help="the seal taken since")

    load_seed = with_register_actor(
        register_sub.add_parser(
            "load-seed",
            help="create each seeded record not already in the register",
            description=(
                "A seed carries ratings, so loading one is an approver's act and "
                "each revision-1 entry is attributed to --actor. A record already "
                "present is skipped, never overwritten; loading twice changes nothing."
            ),
        )
    )
    load_seed.add_argument("--seed", required=True, help="e.g. tenants/sage-spine/seed.json")

    serve = sub.add_parser(
        "serve",
        help="serve the dashboard API over HTTP",
        description=(
            "The HTTP surface over the same service the CLI drives: stored "
            "assessments and remediation from the result store, and the "
            "risk-acceptance workflow against each tenant's policy file under "
            "--policy-root/<tenant>/policy.json. Refuses every request until a "
            "token file is given; binds to loopback unless told otherwise, and "
            "expects a reverse proxy to terminate TLS."
        ),
    )
    serve.add_argument("--to", default="", help=f"result store; defaults to ${STORE_ENV}")
    serve.add_argument(
        "--policy-root",
        required=True,
        help="directory holding <tenant>/policy.json for each tenant",
    )
    serve.add_argument(
        "--tokens",
        default="",
        help="JSON file of hashed service tokens; without it the server serves nothing",
    )
    serve.add_argument("--static", default="", help="directory to serve as the dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--quiet", action="store_true", help="no per-request log lines")
    serve.add_argument(
        "--access-log",
        default="",
        help=(
            "append a hash-chained line per API request (who, what, the status) to this "
            "file; refused at start if the file is not a whole chain"
        ),
    )

    access = sub.add_parser(
        "access-log",
        help="check an access log written by `serve --access-log`",
    )
    access_sub = access.add_subparsers(dest="access_command", required=True)
    access_verify = access_sub.add_parser(
        "verify",
        help="re-check every line's digest and print the verdict",
        description=(
            "Prints the number of entries, the verdict, the first broken line if any, "
            "the head digest, and the anchor (N:DIGEST) to record somewhere else. With "
            "--anchor, the file must still hold the line that anchor was taken at. Exit "
            f"{EXIT_FINDINGS} if a line was edited, removed or reordered, or the file no "
            f"longer extends --anchor; {EXIT_BAD_INPUT} if the file cannot be read or "
            "--anchor is not N:DIGEST."
        ),
    )
    access_verify.add_argument(
        "log",
        nargs="+",
        help="the access-log file; after a rotation, its archives first, oldest first",
    )
    access_verify.add_argument(
        "--anchor",
        default="",
        help="N:DIGEST from an earlier verify, kept where the server's operators cannot write",
    )
    access_rotate = access_sub.add_parser(
        "rotate",
        help="archive the log and start it again, chained from the archive's last line",
        description=(
            "Run with the server stopped. Archives the log as --to, a hard link that must "
            "not exist yet, and replaces the log with one rotation line naming the archive "
            "and --actor, "
            "carrying the next line number and the archive's last digest, so the chain "
            "runs on across the two files. Give both to `verify`, `tokens review "
            "--access-log` and `oversight review-packet --access-log`, archive first. "
            "Prints the archive's anchor and the new log's. "
            f"Exit {EXIT_FINDINGS} if the log is not a whole chain (it is evidence; "
            f"nothing is moved); {EXIT_BAD_INPUT} if it cannot be read, is empty, the "
            "archive exists, or no --actor is given."
        ),
    )
    access_refusals = access_sub.add_parser(
        "refusals",
        help="who was refused a tenant's workspace, by caller",
        description=(
            "Verifies the log, then groups every 401 and 403 on a path under "
            "--tenant's workspace, on or before --as-of, by the user and tenant the "
            "log names. High: a token issued for another tenant, refused here (a "
            "possible security incident to investigate). Notice: no recognised token, "
            "or the tenant's own member without the role. Names every caller, so it is "
            "the operator's view; the tenant's review packet carries the same refusals "
            f"with other tenants unnamed. Exit {EXIT_FINDINGS} under --fail-on when "
            f"tripped or if the log is not a whole chain, {EXIT_BAD_INPUT} if a file "
            "cannot be read."
        ),
    )
    access_refusals.add_argument(
        "log",
        nargs="+",
        help="the access-log file; after a rotation, its archives first, oldest first",
    )
    access_refusals.add_argument("--tenant", required=True, help="the tenant id")
    access_refusals.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today in UTC")
    access_refusals.add_argument(
        "--fail-on",
        choices=("never", "high", "any"),
        default="never",
        help=f"exit {EXIT_FINDINGS} on a refusal from another tenant, or on any refusal",
    )
    access_rotate.add_argument("log", help="the access-log file `serve` writes")
    access_rotate.add_argument("--to", required=True, help="the archive file to create")
    access_rotate.add_argument("--actor", required=True, help="who is rotating the log")

    tokens = sub.add_parser(
        "tokens",
        help="review a token file written for `serve --tokens`",
    )
    tokens_sub = tokens.add_subparsers(dest="tokens_command", required=True)
    tokens_review = tokens_sub.add_parser(
        "review",
        help="list who holds access, to which tenant, until when, and what is wrong",
        description=(
            "The access review for `ironclad serve`: one item per token-file entry "
            "with its user, tenant, roles, expiry and state (active, expiring, expired, "
            "refused). High: an expired entry still in the file, an expiry that is not "
            "a date, a digest listed twice, no tenant, no recognised role. Notice: no "
            "expiry, or expiring within 30 days. Reads digests only; never needs a token. "
            "With --access-log, each entry also gets its request count, 403 count and "
            "last use, and notices for an active entry unused in --dormant-days and for "
            "any 403. With --ledger, an entry with no grant on record, one that differs "
            "from its grant, or one revoked and back in the file is high. "
            f"Exit {EXIT_FINDINGS} under --fail-on when tripped or if the access log or "
            f"ledger is not a whole chain, {EXIT_BAD_INPUT} if a file cannot be read."
        ),
    )
    tokens_review.add_argument("file", help="the token file")
    tokens_review.add_argument(
        "--access-log",
        action="append",
        default=[],
        help=(
            "the `serve --access-log` file; verified before any of it is used. Repeat "
            "it for rotated archives, oldest first, ending with the current log"
        ),
    )
    tokens_review.add_argument(
        "--ledger",
        default="",
        help=(
            "the grant ledger `issue` and `revoke` write; verified, then every entry "
            "is held to its grant"
        ),
    )
    tokens_review.add_argument(
        "--dormant-days",
        type=int,
        default=90,
        help="an active entry with no request in this many days is a notice (default 90)",
    )
    tokens_review.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today in UTC")
    tokens_review.add_argument(
        "--fail-on",
        choices=("never", "high", "any"),
        default="never",
        help=f"exit {EXIT_FINDINGS} when an entry has a high finding, or any finding",
    )
    tokens_ledger = tokens_sub.add_parser(
        "verify-ledger",
        help="re-check the grant ledger's chain, optionally against an earlier anchor",
        description=(
            "Prints the number of entries, the verdict, the first broken line if any, "
            "the head digest, and the anchor (N:DIGEST) to record somewhere else. With "
            "--anchor, the ledger must still hold the line that anchor was taken at, so "
            "a grant cut from the end, or a ledger replaced by a new one, is found. Exit "
            f"{EXIT_FINDINGS} if the chain is broken or does not extend --anchor, "
            f"{EXIT_BAD_INPUT} if the file cannot be read or --anchor is not N:DIGEST."
        ),
    )
    tokens_ledger.add_argument("ledger", help="the grant ledger (by default FILE.ledger)")
    tokens_ledger.add_argument(
        "--anchor",
        default="",
        help="N:DIGEST from an earlier verify, issue or revoke, kept elsewhere",
    )
    tokens_issue = tokens_sub.add_parser(
        "issue",
        help="grant one user access to one tenant until a date; prints the token once",
        description=(
            "Generate a token, add its digest to the file with the user, tenant, roles, "
            "expiry, issuer and date, and print the token once on stdout (it is not "
            "stored). Every grant ends: --expires is required and at most 365 days out. "
            "One entry per user per tenant; a renewal is `revoke` then `issue`, so the "
            "credential changes with the term. The grant is appended to the ledger "
            "before the token file is replaced. "
            f"Exit {EXIT_BAD_INPUT}, writing nothing, if any of that does not hold "
            "or the ledger is not a whole chain."
        ),
    )
    tokens_issue.add_argument("file", help="the token file; created if missing")
    tokens_issue.add_argument("--user", required=True, help="who holds it, as the log names them")
    tokens_issue.add_argument("--tenant", required=True, help="the one tenant it reaches")
    tokens_issue.add_argument(
        "--role",
        action="append",
        required=True,
        choices=[str(r) for r in Role],
        help="repeat for more than one",
    )
    tokens_issue.add_argument("--expires", required=True, help="YYYY-MM-DD, the last day in UTC")
    tokens_issue.add_argument("--actor", required=True, help="who is granting it")
    tokens_issue.add_argument(
        "--on-behalf-of",
        default="",
        help=(
            "partners/<id> or integrations/<id>: the register record this token acts for, "
            "so `oversight access` can hold it to that record's BAA and review. Refused "
            "unless --register holds that record in --tenant and it is not Retired, the "
            "same rule `serve` applies to every request"
        ),
    )
    tokens_issue.add_argument(
        "--register",
        default="",
        help=f"the store holding the tenant's register, for --on-behalf-of; defaults to ${STORE_ENV}",
    )
    tokens_issue.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today in UTC")
    tokens_issue.add_argument(
        "--ledger",
        default="",
        help="the grant ledger to append to; defaults to FILE.ledger beside the token file",
    )
    tokens_revoke = tokens_sub.add_parser(
        "revoke",
        help=(
            "remove entries: one user's in a tenant, every one acting for a register "
            "record, one digest, or every expired one"
        ),
        description=(
            "Remove token-file entries and print what was removed (digest prefixes, "
            "never digests). Give --user with --tenant, or --on-behalf-of with --tenant "
            "to offboard a partner or integration (every entry acting for that record, "
            "whoever holds it, expired ones too; the register is not consulted, so a "
            "record already retired or deleted can still be cut off), or "
            "--digest-prefix as the review prints it, or --expired. The next request "
            "with a removed token is 401. "
            "Each removal is appended to the ledger before the token file is replaced. "
            f"Exit {EXIT_BAD_INPUT}, writing nothing, if nothing matches or the ledger "
            "is not a whole chain."
        ),
    )
    tokens_revoke.add_argument("file", help="the token file")
    tokens_revoke.add_argument("--user", default="")
    tokens_revoke.add_argument("--tenant", default="")
    tokens_revoke.add_argument(
        "--on-behalf-of",
        default="",
        help="partners/<id> or integrations/<id>: every entry in --tenant acting for it",
    )
    tokens_revoke.add_argument("--digest-prefix", default="")
    tokens_revoke.add_argument(
        "--expired", action="store_true", help="every entry past its expiry as of --as-of"
    )
    tokens_revoke.add_argument("--actor", required=True, help="who is revoking")
    tokens_revoke.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today in UTC")
    tokens_revoke.add_argument(
        "--ledger",
        default="",
        help="the grant ledger to append to; defaults to FILE.ledger beside the token file",
    )

    hash_cmd = sub.add_parser(
        "hash-token",
        help="print the digest a token file stores for a token read from stdin",
    )
    hash_cmd.set_defaults(command="hash-token")

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

    def read_json(path: Path) -> tuple[Any, list[str]]:
        """A document to validate, or the reason there is none.

        `validate` exists to be handed dubious files; a file that is not JSON
        is the first thing it should be able to say, not a traceback.
        """
        try:
            return json.loads(path.read_text(encoding="utf-8")), []
        except UnicodeDecodeError as exc:
            return None, [f"{path} is not a text file: {exc}"]
        except json.JSONDecodeError as exc:
            return None, [f"{path} is not valid JSON: {exc}"]

    if args.framework:
        path = Path(args.framework)
        if path.suffix == ".json" and path.exists():
            document, faults = read_json(path)
            problems["framework"] = faults or validate_framework_document(document)
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
            document, faults = read_json(manifest_path)
            problems["manifest"] = faults or validate_manifest(document)

    if args.policy:
        policy_path = Path(args.policy)
        if not policy_path.exists():
            problems["policy"] = [f"{policy_path} does not exist"]
        else:
            document, faults = read_json(policy_path)
            faults = faults or validate_policy(document)
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
    try:
        tenant = client_slug(args.client)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_INPUT
    evidence_dir = Path(args.evidence_dir)
    if not evidence_dir.is_dir():
        print(f"evidence directory not found: {evidence_dir}", file=sys.stderr)
        return EXIT_BAD_INPUT

    # The store refuses an id it cannot use as a directory or document name.
    # Refusing it here, before the assessment and the AI stage have run, costs
    # nothing; refusing it at publish costs the run.
    if args.assessment_id and not is_safe_document_id(args.assessment_id):
        print(
            f"assessment id {args.assessment_id!r} cannot be stored: no '/', not '.' or '..', "
            "at most 1500 characters",
            file=sys.stderr,
        )
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

    previous = None
    if args.previous:
        previous = _stored_document(args.previous, "previous assessment")
        previous_tenant = str(previous.get("tenant_id") or previous.get("client_id") or "")
        if previous_tenant != tenant:
            raise ValidationError(
                f"{args.previous} belongs to tenant {previous_tenant!r}, not {tenant!r}"
            )

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
        previous=previous,
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


def _stored_document(path_text: str, what: str = "assessment") -> dict:
    """Read a stored assessment document, or raise ValidationError naming the file.

    `report --input findings.b64` and `--compare-to README.md` each produced a
    JSONDecodeError traceback. A file that is not JSON, or is JSON that is not
    an assessment, is refused with the path and the reason, exit 2.
    """
    path = Path(path_text)
    if not path.is_file():
        raise ValidationError(f"{what} file not found: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{path} is not a stored {what}: not valid JSON ({exc})") from exc
    if not isinstance(document, dict) or "assessment_id" not in document:
        raise ValidationError(
            f"{path} is not a stored {what}: expected the assessment.json a run writes"
        )
    return document


def cmd_report(args: argparse.Namespace) -> int:
    result = _StoredResult(_stored_document(args.input))
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    # A stored result carries the type it was run as; --view re-issues the same
    # assessment as a different deliverable without re-running anything.
    view = view_for(args.view) if args.view else None

    comparison = None
    if args.compare_to:
        earlier = _stored_document(args.compare_to, "earlier assessment")
        try:
            comparison = compare_assessments(earlier, result.to_dict())
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    output.write_text(
        render_html(result, args.client_name, view=view, comparison=comparison),
        encoding="utf-8",
    )
    print(f"report written: {output}", file=sys.stderr)
    if comparison is not None:
        print(f"  {comparison.headline()}", file=sys.stderr)
        # Both pipelines run this command, so this is the line an operator
        # reads. Without the caveats, "0 closed, 0 opened" after a quick run
        # gave no hint that the later run had planned nothing at all.
        for caveat in comparison.caveats:
            print(f"  caveat: {caveat}", file=sys.stderr)
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    result = _StoredResult(_stored_document(args.input))
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
        issued = Path(args.report) if args.report else None
        if issued is not None and not issued.is_file():
            raise ValidationError(f"issued report not found: {issued}")
        export_audit_package(result, result.evidence, output, issued_report=issued)
        if issued is None:
            print(
                "warning: no --report given, so the package's report.html is re-rendered "
                "and is not the file issued to the client (it names the client by id); "
                "pass --report with the issued report",
                file=sys.stderr,
            )

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
        earlier = _stored_document(args.earlier, "earlier assessment")
        later = _stored_document(args.later, "later assessment")
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

    try:
        comparison = compare_assessments(earlier, later)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
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
        # The deliverables and the trail are the two things a restore has to
        # get right; both are checked here, and the command is red if either
        # is wrong. The chain check is per assessment (§16.27).
        chain = None
        verify_chain = getattr(store, "verify_audit_chain", None)
        if callable(verify_chain):
            chain = verify_chain(args.client)
        _emit(
            {
                "location": artifacts.location(args.client, args.assessment_id),
                **verdict,
                "audit_chain": chain,
            }
        )
        chain_ok = chain is None or bool(chain["verified"])
        return EXIT_OK if verdict["verified"] and chain_ok else EXIT_BAD_INPUT

    if args.store_command == "list":
        _emit(
            {
                "store": where,
                "tenant_id": args.client,
                "assessments": store.list_assessments(args.client, args.limit),
            }
        )
        return EXIT_OK

    if args.store_command == "latest":
        framework = load_framework(args.framework)
        reader = getattr(store, "get_document", None)
        if reader is None:
            print("this store cannot hand back a stored assessment", file=sys.stderr)
            return EXIT_BAD_INPUT
        tenant = client_slug(args.client)
        for row in store.list_assessments(tenant, limit=50):
            if str(row.get("framework_id", "")) != framework.id:
                continue
            if args.before and str(row.get("assessment_id", "")) == args.before:
                continue
            document = reader(tenant, str(row["assessment_id"]))
            if document is None:
                continue
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            print(
                f"previous {framework.id} assessment for {tenant}: {row['assessment_id']} "
                f"({row.get('started_at', '')}) written to {out}",
                file=sys.stderr,
            )
            return EXIT_OK
        print(f"no previous {framework.id} assessment stored for {tenant}", file=sys.stderr)
        return EXIT_PARTIAL

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


def _read_seal(path: str) -> dict[str, Any]:
    """A register seal from a file, whole and matching its own digest."""
    try:
        seal = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{path} is not a readable seal ({exc})") from exc
    return oversight.check_seal(seal)


def cmd_oversight(args: argparse.Namespace) -> int:
    """The register from the command line, through the same policy as the API.

    Nothing here decides who may do what: `ironclad.oversight` refuses a
    stranger, a reader loading a seed and an unrated contributor exactly as
    it does over HTTP, and the refusal comes back as exit 2.
    """
    if args.oversight_command == "compare-seals":
        comparison = oversight.compare_seals(_read_seal(args.earlier), _read_seal(args.later))
        _emit(comparison)
        return EXIT_OK if comparison["verified"] else EXIT_FINDINGS
    if args.oversight_command == "verify-packet":
        from ironclad import access_review  # noqa: PLC0415

        verdict = access_review.verify_packet(
            Path(args.packet), args.digest, Path(args.previous) if args.previous else None
        )
        _emit(verdict)
        return EXIT_OK if verdict["verified"] else EXIT_FINDINGS

    target = args.to or os.environ.get(STORE_ENV, "")
    if not target:
        print(
            f"no store target: pass --to or set {STORE_ENV} "
            "(a path or file:// for a volume, mysql:// for MariaDB)",
            file=sys.stderr,
        )
        return EXIT_BAD_INPUT
    store = store_from_target(target)
    if not hasattr(store, "put_oversight"):
        print(f"{target_summary(target)} does not hold the register", file=sys.stderr)
        return EXIT_BAD_INPUT

    if args.oversight_command == "load-seed":
        try:
            seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"{args.seed} is not a readable seed ({exc})") from exc
        tenant = str(seed.get("tenant_id") or "") if isinstance(seed, dict) else ""
        if not tenant:
            print(f"{args.seed} names no tenant_id", file=sys.stderr)
            return EXIT_BAD_INPUT
    else:
        tenant = args.tenant
    caller = Principal(
        user_id=args.actor, tenant_id=tenant, roles=frozenset(Role(r) for r in args.role)
    )

    if args.oversight_command == "load-seed":
        _emit({"tenant_id": tenant, **oversight.load_seed(store, seed, principal=caller)})
        return EXIT_OK

    if args.oversight_command == "seal":
        _emit(oversight.seal_register(store, tenant_id=tenant, principal=caller))
        return EXIT_OK

    if args.oversight_command == "verify":
        # Read the seal before touching the store, so a bad file is bad input.
        earlier = _read_seal(args.seal) if args.seal else None
        sweep = oversight.verify_register(store, tenant_id=tenant, principal=caller)
        verified = sweep["verified"]
        if earlier is not None:
            now = oversight.seal_register(store, tenant_id=tenant, principal=caller)
            sweep["seal"] = oversight.compare_seals(earlier, now)
            verified = verified and sweep["seal"]["verified"]
        _emit(sweep)
        return EXIT_OK if verified else EXIT_FINDINGS

    if args.oversight_command == "access":
        try:
            document = json.loads(Path(args.tokens).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"token file unreadable: {args.tokens} ({exc})") from exc
        access = oversight.partner_access(
            store,
            document,
            tenant_id=tenant,
            principal=caller,
            today=args.as_of or oversight.today_utc(),
        )
        _emit(access)
        tripped = (args.fail_on == "high" and access["high"]) or (
            args.fail_on == "any" and (access["high"] or access["notices"])
        )
        return EXIT_FINDINGS if tripped else EXIT_OK

    if args.oversight_command == "review-packet":
        return _review_packet(args, store, tenant, caller)

    if args.oversight_command == "export":
        export = oversight.export_register(
            store,
            tenant_id=tenant,
            principal=caller,
            today=args.as_of or oversight.today_utc(),
        )
        out = Path(args.out)
        if out.is_dir():
            out = out / export["filename"]
        try:
            # Bytes, so the CRLF rows are written as they are on every platform.
            out.write_bytes(export.pop("csv").encode("utf-8"))
        except OSError as exc:
            raise ValidationError(f"cannot write {out} ({exc})") from exc
        _emit({"tenant_id": tenant, "path": str(out), **export})
        return EXIT_OK

    queue = oversight.attention_queue(
        store,
        tenant_id=tenant,
        principal=caller,
        today=args.as_of or oversight.today_utc(),
    )
    _emit(queue)
    tripped = (args.fail_on == "high" and queue["high"]) or (
        args.fail_on == "any" and queue["records"]
    )
    return EXIT_FINDINGS if tripped else EXIT_OK


def _review_packet(args: argparse.Namespace, store: Any, tenant: str, caller: Principal) -> int:
    """`oversight review-packet`: read every input once, build, file, then judge."""
    from ironclad import access_review  # noqa: PLC0415
    from ironclad.api import access_log, grant_ledger  # noqa: PLC0415

    tokens_path = Path(args.tokens)
    try:
        raw = tokens_path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"token file unreadable: {tokens_path} ({exc})") from exc
    chains: dict[str, Any] = {}
    for what, given, reader, error in (
        ("access log", args.access_log, access_log.read_files, access_log.AccessLogError),
        (
            "grant ledger",
            [args.ledger] if args.ledger else [],
            lambda paths: grant_ledger.read_file(paths[0]),
            grant_ledger.GrantLedgerError,
        ),
    ):
        if not given:
            chains[what] = None
            continue
        paths = [Path(p) for p in given]
        missing = [p for p in paths if not p.is_file()]
        if missing:
            print(f"{what} not found: {missing[0]}", file=sys.stderr)
            return EXIT_BAD_INPUT
        try:
            chains[what] = reader(paths)
        except error as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_BAD_INPUT
        verdict = chains[what][0]
        if not verdict["verified"]:
            print(
                f"{paths[-1] if len(paths) == 1 else what} is not a whole chain at line "
                f"{verdict['broken_at']} ({verdict['reason']}); no packet is built on it",
                file=sys.stderr,
            )
            return EXIT_FINDINGS
    packet = access_review.build_packet(
        store,
        document,
        tenant_id=tenant,
        principal=caller,
        today=args.as_of or oversight.today_utc(),
        token_file_sha256=hashlib.sha256(raw).hexdigest(),
        access_log=chains["access log"],
        ledger=chains["grant ledger"],
        dormant_days=args.dormant_days,
        previous=Path(args.previous) if args.previous else None,
        previous_digest=args.previous_digest,
    )
    path = access_review.write_packet(packet, Path(args.out))
    manifest = packet["manifest"]
    _emit(
        {
            "path": str(path),
            "tenant_id": tenant,
            "as_of": manifest["as_of"],
            "digest": manifest["digest"],
            "summary": manifest["summary"],
            "files": manifest["files"],
        }
    )
    summary = manifest["summary"]
    tripped = (args.fail_on == "high" and summary["high"]) or (
        args.fail_on == "any" and (summary["high"] or summary["notices"])
    )
    return EXIT_FINDINGS if tripped else EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve the API. Returns only when the server is stopped."""
    from ironclad.api.http import App, TokenFileAuthenticator, serve  # noqa: PLC0415

    target = args.to or os.environ.get(STORE_ENV, "")
    if not target:
        print(
            f"no store target: pass --to or set {STORE_ENV} "
            "(a path or file:// for a volume, mysql:// for MariaDB)",
            file=sys.stderr,
        )
        return EXIT_BAD_INPUT

    policy_root = Path(args.policy_root)
    if not policy_root.is_dir():
        print(f"policy root is not a directory: {policy_root}", file=sys.stderr)
        return EXIT_BAD_INPUT

    tokens = None
    if args.tokens:
        tokens = Path(args.tokens)
        if not tokens.is_file():
            print(f"token file not found: {tokens}", file=sys.stderr)
            return EXIT_BAD_INPUT
    else:
        print(
            "no --tokens given: the server will answer every request with 503 "
            "until it is restarted with one",
            file=sys.stderr,
        )

    static = Path(args.static) if args.static else None
    if static is not None and not static.is_dir():
        print(f"static root is not a directory: {static}", file=sys.stderr)
        return EXIT_BAD_INPUT

    store = store_from_target(target)
    health = store.health()
    if not health.get("writable"):
        print(f"store is not writable: {health.get('detail', '')}", file=sys.stderr)
        return EXIT_BAD_INPUT
    # The store is also the register a partner's token is held to.
    authenticator = TokenFileAuthenticator(tokens, register=store) if tokens else None

    access_log = None
    if args.access_log:
        from ironclad.api.access_log import AccessLog, AccessLogError  # noqa: PLC0415

        try:
            access_log = AccessLog(args.access_log)
        except AccessLogError as exc:
            print(f"access log refused: {exc}", file=sys.stderr)
            return EXIT_BAD_INPUT

    app = App(
        results=store,
        policy_root=policy_root,
        authenticator=authenticator,
        static_root=static,
        quiet=args.quiet,
        access_log=access_log,
    )
    server = serve(app, host=args.host, port=args.port)
    host, port = str(server.server_address[0]), int(server.server_address[1])
    print(
        f"ironclad {__version__} serving {target_summary(target)} on http://{host}:{port}/",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if access_log is not None:
            access_log.close()
    return EXIT_OK


def cmd_access_log(args: argparse.Namespace) -> int:
    """Verify an access log's chain (across its rotated archives), or rotate it."""
    from ironclad.api import access_log  # noqa: PLC0415

    if args.access_command == "rotate":
        path = Path(args.log)
        if not path.is_file():
            print(f"access log not found: {path}", file=sys.stderr)
            return EXIT_BAD_INPUT
        try:
            verdict = access_log.verify_file(path)
            if not verdict["verified"]:
                print(
                    f"{path} is not a whole chain at line {verdict['broken_at']} "
                    f"({verdict['reason']}); it is evidence, not something to rotate",
                    file=sys.stderr,
                )
                return EXIT_FINDINGS
            _emit(access_log.rotate(path, args.to, actor=args.actor))
        except access_log.AccessLogError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_BAD_INPUT
        return EXIT_OK
    if args.access_command == "refusals":
        return _refusals(args)
    return _verify_chain(
        [Path(p) for p in args.log],
        "access log",
        access_log.read_files,
        access_log.AccessLogError,
        args.anchor,
    )


def _refusals(args: argparse.Namespace) -> int:
    """`access-log refusals`: the verified log's refusals on one tenant's workspace."""
    from ironclad.api import access_log  # noqa: PLC0415
    from ironclad.api.tokens import utc_now  # noqa: PLC0415

    tenant = args.tenant.strip()
    if not tenant or slugify(tenant) != tenant:
        print(f"{args.tenant!r} is not a tenant id", file=sys.stderr)
        return EXIT_BAD_INPUT
    try:
        as_of = date.fromisoformat(oversight.check_as_of(args.as_of)) if args.as_of else None
    except oversight.OversightError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_INPUT
    paths = [Path(p) for p in args.log]
    for path in paths:
        if not path.is_file():
            print(f"access log not found: {path}", file=sys.stderr)
            return EXIT_BAD_INPUT
    try:
        verdict, entries = access_log.read_files(paths)
    except access_log.AccessLogError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_INPUT
    if not verdict["verified"]:
        print(
            f"the access log is not a whole chain at line {verdict['broken_at']} "
            f"({verdict['reason']}); no review is built on it",
            file=sys.stderr,
        )
        return EXIT_FINDINGS
    report = access_log.refusals(entries, tenant, as_of or utc_now().date())
    report["anchor"] = access_log.anchor_of(verdict)
    _emit(report)
    tripped = (args.fail_on == "high" and report["high"]) or (
        args.fail_on == "any" and report["refused"]
    )
    return EXIT_FINDINGS if tripped else EXIT_OK


def _verify_chain(
    paths: list[Path],
    what: str,
    reader: Callable[[list[Path]], tuple[dict[str, Any], list[dict[str, Any]]]],
    error: type[Exception],
    anchor: str,
) -> int:
    """Verify one chained log, and with an anchor, that it still extends it."""
    from ironclad.api import access_log  # noqa: PLC0415

    if anchor:
        try:
            access_log.parse_anchor(anchor)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_BAD_INPUT
    for path in paths:
        if not path.is_file():
            print(f"{what} not found: {path}", file=sys.stderr)
            return EXIT_BAD_INPUT
    try:
        verdict, entries = reader(paths)
    except error as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_INPUT
    verdict["anchor"] = access_log.anchor_of(verdict)
    ok = verdict["verified"]
    if anchor and ok:
        verdict["extends"] = access_log.check_anchor(entries, anchor)
        ok = verdict["extends"]["extended"]
    print(json.dumps(verdict, indent=2))
    return EXIT_OK if ok else EXIT_FINDINGS


def cmd_tokens(args: argparse.Namespace) -> int:
    """Review a token file (and its use, given the access log), or issue or revoke an entry."""
    if args.tokens_command in ("issue", "revoke"):
        return _edit_tokens(args)
    if args.tokens_command == "verify-ledger":
        from ironclad.api import grant_ledger  # noqa: PLC0415

        return _verify_chain(
            [Path(args.ledger)],
            "grant ledger",
            lambda paths: grant_ledger.read_file(paths[0]),
            grant_ledger.GrantLedgerError,
            args.anchor,
        )
    from ironclad.api.tokens import review_tokens, utc_now  # noqa: PLC0415

    path = Path(args.file)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"token file unreadable: {path}: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    as_of = utc_now().date()
    if args.as_of:
        as_of = date.fromisoformat(oversight.check_as_of(args.as_of))
    access_log = None
    if args.access_log:
        from ironclad.api.access_log import AccessLogError, read_files  # noqa: PLC0415

        log_paths = [Path(p) for p in args.access_log]
        for log_path in log_paths:
            if not log_path.is_file():
                print(f"access log not found: {log_path}", file=sys.stderr)
                return EXIT_BAD_INPUT
        try:
            verdict, access_log = read_files(log_paths)
        except AccessLogError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_BAD_INPUT
        if not verdict["verified"]:
            named = log_paths[0] if len(log_paths) == 1 else "the access log"
            print(
                f"{named} is not a whole chain at line {verdict['broken_at']} "
                f"({verdict['reason']}); no review is built on it",
                file=sys.stderr,
            )
            return EXIT_FINDINGS
    ledger = None
    ledger_head = ""
    if args.ledger:
        from ironclad.api import grant_ledger  # noqa: PLC0415

        ledger_path = Path(args.ledger)
        if not ledger_path.is_file():
            print(f"grant ledger not found: {ledger_path}", file=sys.stderr)
            return EXIT_BAD_INPUT
        try:
            ledger_verdict, ledger = grant_ledger.read_file(ledger_path)
        except grant_ledger.GrantLedgerError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_BAD_INPUT
        if not ledger_verdict["verified"]:
            print(
                f"{ledger_path} is not a whole chain at line {ledger_verdict['broken_at']} "
                f"({ledger_verdict['reason']}); no review is built on it",
                file=sys.stderr,
            )
            return EXIT_FINDINGS
        ledger_head = ledger_verdict["head"]
    try:
        review = review_tokens(document, as_of, access_log, args.dormant_days, ledger)
    except ValueError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    if ledger is not None:
        review["ledger"]["head"] = ledger_head
    _emit(review)
    tripped = (args.fail_on == "high" and review["high"]) or (
        args.fail_on == "any" and (review["high"] or review["notices"])
    )
    return EXIT_FINDINGS if tripped else EXIT_OK


def _check_link(args: argparse.Namespace) -> None:
    """Refuse a linked grant the register already withholds, before anything is written.

    `serve` would answer such a token 403 on its first request, so issuing it
    would only put a grant nobody can use on the ledger. A malformed link is
    left to `issue_token`, which names it alongside anything else wrong, and
    so is a tenant that is not one.
    """
    from ironclad.api import tokens  # noqa: PLC0415

    link = args.on_behalf_of.strip()
    try:
        parsed = tokens.parse_on_behalf_of(link)
    except ValueError:
        return
    tenant = args.tenant.strip()
    if parsed is None or not tenant or slugify(tenant) != tenant:
        return
    target = args.register or os.environ.get(STORE_ENV, "")
    if not target:
        raise tokens.TokenFileError(
            f"--on-behalf-of {link} needs the register to check it against; "
            f"pass --register or set {STORE_ENV}"
        )
    try:
        store = store_from_target(target)
        if not hasattr(store, "get_oversight"):
            raise tokens.TokenFileError(f"{target_summary(target)} does not hold the register")
        reason = tokens.link_withdrawn(store, tenant, *parsed)
    except IroncladError as exc:
        raise tokens.TokenFileError(f"the register could not be read ({exc})") from None
    if reason is not None:
        raise tokens.TokenFileError(f"{reason}; `serve` would refuse this token")


def _edit_tokens(args: argparse.Namespace) -> int:
    """`tokens issue` and `tokens revoke`: one locked read-modify-write of the file."""
    from ironclad.api import grant_ledger, tokens  # noqa: PLC0415

    path = Path(args.file)
    as_of = date.fromisoformat(oversight.check_as_of(args.as_of)) if args.as_of else None
    as_of = as_of or tokens.utc_now().date()
    ledger_path = Path(args.ledger) if args.ledger else grant_ledger.default_path(path)
    try:
        if args.tokens_command == "issue":
            _check_link(args)
        with tokens.TokenFileLock(path):
            document = tokens.read_token_file(path)
            try:
                ledger = grant_ledger.GrantLedger(ledger_path)
            except grant_ledger.GrantLedgerError as exc:
                raise tokens.TokenFileError(str(exc)) from None
            if args.tokens_command == "issue":
                try:
                    expires = tokens.parse_expiry(args.expires)
                except tokens.InvalidExpiryError as exc:
                    raise tokens.TokenFileError(str(exc)) from None
                if expires is None:
                    raise tokens.TokenFileError("--expires is required; every grant ends")
                token, entry = tokens.issue_token(
                    document,
                    user_id=args.user,
                    tenant_id=args.tenant,
                    roles=args.role,
                    expires_at=expires,
                    issued_by=args.actor,
                    as_of=as_of,
                    on_behalf_of=args.on_behalf_of,
                )
                _record_grant(ledger, "issue", [entry], args.actor, as_of)
                tokens.write_token_file(path, document)
                print(
                    "the token below is shown once and is not stored; hand it to "
                    f"{entry['user_id']} over a channel you would trust with the access",
                    file=sys.stderr,
                )
                _emit(
                    {
                        "token": token,
                        "entry": tokens.summary(entry),
                        "ledger_head": ledger.head,
                        "ledger_anchor": ledger.anchor,
                    }
                )
                return EXIT_OK
            removed = tokens.revoke_tokens(
                document,
                user_id=args.user,
                tenant_id=args.tenant,
                digest_prefix=args.digest_prefix,
                expired_as_of=as_of if args.expired else None,
                on_behalf_of=args.on_behalf_of,
            )
            _record_grant(ledger, "revoke", removed, args.actor, as_of)
            tokens.write_token_file(path, document)
    except tokens.TokenFileError as exc:
        print(f"{path}: {exc}; nothing was written", file=sys.stderr)
        return EXIT_BAD_INPUT
    _emit(
        {
            "revoked_by": args.actor,
            "as_of": as_of.isoformat(),
            "removed": [tokens.summary(e) for e in removed],
            "ledger_head": ledger.head,
            "ledger_anchor": ledger.anchor,
        }
    )
    return EXIT_OK


def _record_grant(
    ledger: Any, action: str, entries: list[dict[str, Any]], actor: str, as_of: date
) -> None:
    """Put an edit on the ledger before the token file changes, or refuse it."""
    from ironclad.api import grant_ledger, tokens  # noqa: PLC0415

    if not actor.strip():
        raise tokens.TokenFileError("no --actor; the ledger must name who made the change")
    try:
        ledger.record(action, entries, actor=actor.strip(), as_of=as_of)
    except grant_ledger.GrantLedgerError as exc:
        raise tokens.TokenFileError(str(exc)) from None


def cmd_hash_token() -> int:
    """Digest one token from stdin, so a token never appears in a command line."""
    from ironclad.api.http import hash_token  # noqa: PLC0415

    token = sys.stdin.readline().rstrip("\r\n")
    if not token:
        print("read no token on stdin", file=sys.stderr)
        return EXIT_BAD_INPUT
    print(hash_token(token))
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
            # A target reached only by a `related` edge still needs direct
            # review: it is listed here, as it is left out of `coverage`.
            "unmapped_target_controls": sorted(
                set(target_ids) - crosswalk.addressed(source.id, target.id)
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

        # The stored trail, not a fresh one. The auditor package exported from
        # a stored result used to carry an empty audit-trail.csv and certify
        # the genesis hash as a verified chain head.
        self.audit = AuditLog.from_dict(document.get("audit") or {}, tenant_id=tenant)
        self.module_output = document.get("module_output", {})
        self.warnings = list(document.get("warnings", []))
        self.failed_modules = dict(document.get("failed_modules", {}))

    def findings_payload(self) -> list[dict]:
        """The stored findings, as `merge_consensus` needs them to match results."""
        return list(self.raw.get("findings", []))

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
        "oversight": lambda: cmd_oversight(args),
        "serve": lambda: cmd_serve(args),
        "access-log": lambda: cmd_access_log(args),
        "tokens": lambda: cmd_tokens(args),
        "hash-token": lambda: cmd_hash_token(),
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
