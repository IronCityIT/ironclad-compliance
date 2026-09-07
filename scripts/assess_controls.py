#!/usr/bin/env python3
"""Control assessment — CLI wrapper.

The assessment logic lives in the ironclad package (ingest -> engine -> modules).
This preserves the flags the compliance-assessment workflow already passes, and
writes the same output path it already reads.

`ironclad assess` is the richer entry point: it also emits the base64 findings
payload the AI consensus engine expects and the rendered report.
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
from ironclad.report.export import export_json  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess compliance controls against evidence.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--framework", required=True, help="framework alias or path to a JSON file")
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--assessment-type", default="full")
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

    try:
        result = run_assessment(
            tenant_id=tenant,
            framework=args.framework,
            evidence=evidence,
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
    for warning in result.warnings:
        print(f"  warning: {warning}", file=sys.stderr)

    return 0 if result.ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
