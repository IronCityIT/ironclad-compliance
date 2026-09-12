#!/usr/bin/env python3
"""Control assessment — CLI wrapper.

The assessment logic lives in the ironclad package (ingest -> engine -> modules).
This preserves the flags the compliance-assessment workflow already passed, and
writes the same output path it already read.

`ironclad assess` is the richer entry point: it also emits the base64 findings
payload the AI consensus engine expects and the rendered report.

This wrapper used to ignore the tenant policy entirely — it had no --policy flag
and did not look for one beside the evidence, so scope exclusions and risk
acceptances were silently not applied. A control a client had formally accepted
came back as a gap, and nothing said so. It honours a policy the same way
`ironclad assess` does now: an explicit --policy must exist, and one sitting
beside the evidence is picked up.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ironclad.engine import run_assessment  # noqa: E402
from ironclad.errors import IroncladError  # noqa: E402
from ironclad.frameworks.crosswalk import load_crosswalks  # noqa: E402
from ironclad.ids import slugify  # noqa: E402
from ironclad.ingest import collect_from_directory  # noqa: E402
from ironclad.policy import find_policy, load_policy  # noqa: E402
from ironclad.report.export import export_json  # noqa: E402
from ironclad.report.views import ASSESSMENT_TYPES, DEFAULT_VIEW  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess compliance controls against evidence.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--framework", required=True, help="framework alias or path to a JSON file")
    parser.add_argument("--evidence-dir", required=True)
    # Constrained, like the CLI's. Unconstrained it accepted anything and the
    # report quietly fell back to the full view, so a mistyped --assessment-type
    # produced the wrong deliverable without a word.
    parser.add_argument("--assessment-type", default=DEFAULT_VIEW, choices=ASSESSMENT_TYPES)
    parser.add_argument("--policy", default="", help="tenant policy file")
    parser.add_argument("--group", default="deep", help="quick | standard | deep")
    parser.add_argument("--assessment-id", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    tenant = slugify(args.client_id)
    evidence_dir = Path(args.evidence_dir)
    if not evidence_dir.is_dir():
        print(f"evidence directory not found: {evidence_dir}", file=sys.stderr)
        return 2

    evidence, warnings = collect_from_directory(tenant, evidence_dir, args.framework)

    # Same rule as `ironclad assess`: an explicit --policy must exist, and one
    # found beside the evidence is a convenience whose absence is not an error.
    policy_path: Path | None = None
    if args.policy:
        policy_path = Path(args.policy)
        if not policy_path.exists():
            print(f"tenant policy not found: {policy_path}", file=sys.stderr)
            return 2
    else:
        policy_path = find_policy(evidence_dir)

    try:
        policy = load_policy(policy_path, expected_tenant=tenant) if policy_path else None
        result = run_assessment(
            tenant_id=tenant,
            framework=args.framework,
            evidence=evidence,
            policy=policy,
            group=args.group,
            crosswalk=load_crosswalks(),
            assessment_type=args.assessment_type,
            assessment_id=args.assessment_id,
        )
    except IroncladError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result.warnings.extend(warnings)
    Path(args.output).write_text(export_json(result), encoding="utf-8")

    summary = result.assessment.summary
    print(f"assessment {result.assessment.assessment_id}")
    print(f"  readiness      {summary.readiness_score}%")
    print(f"  met            {summary.compliant}")
    print(f"  partially met  {summary.partial}")
    print(f"  not met        {summary.gap}")
    print(f"  risk accepted  {summary.accepted_risk}")
    print(f"  evidence       {summary.evidence_artifacts} ({summary.stale_artifacts} out of date)")
    print(f"  remediation    {len(result.plan)} item(s)")
    print(f"  output         {args.output}")
    if policy_path is not None:
        print(f"  policy         {policy_path}")
    for warning in result.warnings:
        print(f"  warning: {warning}", file=sys.stderr)

    return 0 if result.ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
