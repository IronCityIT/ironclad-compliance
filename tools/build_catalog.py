#!/usr/bin/env python3
"""Generate dashboard/public/catalog.json from the engine's own registry.

The dashboard's capability checkboxes, group presets and framework picker are
rendered from this file. Generating it rather than hand-writing it is what keeps
the promise that a UI selection maps 1:1 onto `--modules` / `--group`: adding a
capability to ironclad/modules/ is the only edit needed for it to appear in
every surface.

Run it after adding or renaming a capability. CI re-runs it and fails if the
committed file is stale, so the two cannot silently drift.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ironclad import registry  # noqa: E402
from ironclad.frameworks.loader import available_frameworks  # noqa: E402
from ironclad.version import __version__  # noqa: E402

OUTPUT = REPO_ROOT / "dashboard" / "public" / "catalog.json"


def build() -> dict:
    reg = registry.discover()
    return {
        "generated_by": f"tools/build_catalog.py (engine {__version__})",
        "engine_version": __version__,
        "modules": registry.catalog(reg),
        "groups": sorted(registry.all_groups(reg)),
        "default_group": registry.DEFAULT_GROUP,
        "frameworks": available_frameworks(),
        "assessment_types": ["full", "gap-only", "readiness"],
    }


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    catalog = json.dumps(build(), indent=2) + "\n"

    if "--check" in args:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != catalog:
            print(
                f"{OUTPUT.relative_to(REPO_ROOT)} is out of date — "
                f"run: python tools/build_catalog.py",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT.relative_to(REPO_ROOT)} is current")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(catalog, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
