#!/usr/bin/env python3
"""Run the whole product against a real store, and check what came back.

Not a unit test. This drives the same path the pipeline drives — ingest a
directory of evidence, assess it, render the deliverables, publish, read the
record back out of the store — and fails if any of it disagrees with itself.

It exists because every part of that path is covered by tests and the path as a
whole was not. A projection that is correct, a store that is correct and a
report that is correct still leave the question of whether the number a client
reads is the number that was stored, and that question is only answered by
storing it and reading it back.

    python scripts/end_to_end.py --store /srv/ironclad
    python scripts/end_to_end.py --store mysql://user:pw@host/db

Run it against a NAS volume or a database to validate that deployment before
anything real is published to it. Exit 0 means the round trip agreed at every
step; anything else names the step that did not.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ironclad.engine import run_assessment  # noqa: E402
from ironclad.frameworks.crosswalk import load_crosswalks  # noqa: E402
from ironclad.ingest import collect_from_directory  # noqa: E402
from ironclad.report.export import export_audit_package, export_json  # noqa: E402
from ironclad.report.render import render_html  # noqa: E402
from ironclad.store import ArtifactStore, store_from_target, target_summary  # noqa: E402

TENANT = "icit-internal"
EVIDENCE = REPO_ROOT / "examples" / "evidence"


class CheckError(Exception):
    """A step disagreed with an earlier one."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


def require(value: T | None, message: str) -> T:
    """The value, or a failure naming what was missing.

    `check` narrows nothing for a typechecker, and an `assert` to do the
    narrowing is removed under -O — which is exactly the objection bandit
    raises, and it is right: a check that vanishes under an optimisation flag is
    not a check.
    """
    if value is None:
        raise CheckError(message)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, help="store target, or $IRONCLAD_STORE")
    parser.add_argument("--framework", default="soc2")
    parser.add_argument("--group", default="deep")
    parser.add_argument(
        "--artifacts", default="", help="artifact volume; defaults to the store's own root"
    )
    parser.add_argument("--keep", action="store_true", help="keep the working directory")
    args = parser.parse_args(argv)

    store = store_from_target(args.store)
    where = target_summary(args.store)
    workspace = Path(tempfile.mkdtemp(prefix="ironclad-e2e-"))

    try:
        print(f"store        {where}")

        health = store.health()
        check(health.get("writable"), f"the store is not writable: {health.get('detail')}")
        print(f"health       writable ({health.get('store')})")

        # ---- assess ---------------------------------------------------------
        evidence, warnings = collect_from_directory(TENANT, EVIDENCE, args.framework)
        check(len(evidence) > 0, f"no evidence was collected from {EVIDENCE}")
        result = run_assessment(
            tenant_id=TENANT,
            framework=args.framework,
            evidence=evidence,
            group=args.group,
            crosswalk=load_crosswalks(),
        )
        result.warnings.extend(warnings)
        summary = result.assessment.summary
        assessment_id = result.assessment.assessment_id
        print(
            f"assess       {assessment_id}: {summary.readiness_score}% "
            f"over {summary.total_controls} controls, {len(result.plan)} remediation item(s)"
        )
        check(not result.failed_modules, f"a capability failed: {result.failed_modules}")
        check(summary.total_controls > 0, "the assessment judged no controls")

        # ---- deliverables ---------------------------------------------------
        (workspace / "assessment.json").write_text(export_json(result), encoding="utf-8")
        (workspace / "report.html").write_text(render_html(result, TENANT), encoding="utf-8")
        written = export_audit_package(result, evidence, workspace / "package")
        check(len(written) >= 7, f"the auditor package is short: {len(written)} file(s)")
        manifest = json.loads((workspace / "package" / "package.json").read_text(encoding="utf-8"))
        check(manifest["audit_chain_verified"], "the audit chain did not verify before storing")
        print(f"deliverables report.html + {len(written)} package file(s), chain verified")

        # ---- publish --------------------------------------------------------
        document = json.loads((workspace / "assessment.json").read_text(encoding="utf-8"))
        stored_id = store.put_assessment(document)
        check(stored_id == assessment_id, f"stored as {stored_id}, not {assessment_id}")
        print(f"publish      {stored_id}")

        # ---- read it back ---------------------------------------------------
        # The question none of the unit tests answer: is the number a client
        # reads the number that was stored?
        record = require(
            store.get_assessment(TENANT, assessment_id),
            "the assessment could not be read back",
        )
        check(
            abs(float(record["readiness_score"]) - summary.readiness_score) < 0.01,
            f"readiness came back as {record['readiness_score']}, not {summary.readiness_score}",
        )
        check(
            int(record["total_controls"]) == summary.total_controls,
            f"control count came back as {record['total_controls']}",
        )
        check(
            record["audit_chain_head"] == result.audit.head,
            "the stored chain head does not match the assessment's",
        )
        print(
            f"read back    {record['readiness_score']}% over "
            f"{record['total_controls']} controls, chain head matches"
        )

        # ---- the trail ------------------------------------------------------
        events = store.list_audit(TENANT)
        check(
            len(events) >= len(result.audit.events),
            f"the trail came back short: {len(events)} of {len(result.audit.events)}",
        )
        previous = ""
        for index, event in enumerate(events):
            if index and event["prev_hash"] != previous:
                raise CheckError(f"the stored chain breaks at event {event['event_id']}")
            previous = str(event["hash"])
        print(f"audit        {len(events)} event(s), chain verifies out of the store")

        # ---- the queue ------------------------------------------------------
        queue = store.list_remediation(TENANT)
        check(
            len(queue) == len(result.plan),
            f"the queue came back as {len(queue)} item(s), not {len(result.plan)}",
        )
        check(
            all(row["tenant_id"] == TENANT for row in queue),
            "the queue carries another tenant's rows",
        )
        print(f"remediation  {len(queue)} item(s), all this tenant's")

        # ---- publishing twice -----------------------------------------------
        # A pipeline re-run is normal and must not accumulate a second record.
        store.put_assessment(document)
        listed = [a["assessment_id"] for a in store.list_assessments(TENANT, limit=100)]
        check(
            listed.count(assessment_id) == 1,
            f"re-publishing left {listed.count(assessment_id)} records",
        )
        check(
            len(store.list_audit(TENANT)) == len(events),
            "re-publishing duplicated the audit trail",
        )
        print("idempotent   re-published, one record, trail unchanged")

        # ---- the deliverables ------------------------------------------------
        # A deliverable that cannot be shown to be the one that was issued is
        # not evidence of anything.
        artifact_root = args.artifacts or getattr(store, "root", None)
        if artifact_root is not None:
            artifacts = ArtifactStore(artifact_root)
            stored = artifacts.put(TENANT, assessment_id, workspace)
            verdict = artifacts.verify(TENANT, assessment_id)
            check(verdict["verified"], f"the deliverables did not verify: {verdict['detail']}")
            check(
                verdict["checked"] == len(stored),
                f"verified {verdict['checked']} of {len(stored)} deliverable(s)",
            )
            print(f"deliverables {len(stored)} stored and checksummed, all verify")
        else:
            print("deliverables skipped — this store has no volume; pass --artifacts")

        print(f"\nOK — the round trip agreed at every step against {where}")
        return 0

    except CheckError as failure:
        print(f"\nFAILED — {failure}", file=sys.stderr)
        return 1
    finally:
        if args.keep:
            print(f"working directory kept: {workspace}", file=sys.stderr)
        else:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
