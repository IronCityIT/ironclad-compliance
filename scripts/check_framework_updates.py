#!/usr/bin/env python3
"""Framework update checker — CLI wrapper.

The logic lives in ironclad.frameworks.updates so it can be tested without a
network. This keeps the flags the framework-updates workflow already passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ironclad.frameworks.updates import STATE_FILE, check_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check official sources for framework updates.")
    parser.add_argument("--framework", default="", help="one framework, or '' / 'all' for every one")
    parser.add_argument("--output", default="updates.json")
    parser.add_argument(
        "--state",
        default=str(Path("frameworks") / STATE_FILE),
        help="fingerprint state file, used to detect a change between runs",
    )
    args = parser.parse_args(argv)

    try:
        report = check_all(args.framework, state_path=Path(args.state))
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    for check in report["checks"]:
        marker = "!" if check["update_detected"] else ("?" if check["status"] == "unchecked" else "-")
        print(f" {marker} {check['name']}: {check['status']} — {check['detail'] or check['error']}")

    print(f"\nresults written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
