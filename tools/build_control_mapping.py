#!/usr/bin/env python3
"""Generate docs/control-mapping.md from the crosswalk data.

The mapping table is documentation of data that lives in
frameworks/crosswalks/*.json. Writing it by hand guarantees it drifts from what
the engine actually does, and a crosswalk document that disagrees with the
engine is worse than none: it is the thing a client would be shown.

Run after editing a crosswalk. CI re-runs it with --check.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ironclad.frameworks.crosswalk import INHERITANCE, Crosswalk, load_crosswalks  # noqa: E402
from ironclad.frameworks.loader import load_framework  # noqa: E402

OUTPUT = REPO_ROOT / "docs" / "control-mapping.md"
HUB = "soc2"
TARGETS = (
    ("nist-csf", "NIST CSF 2.0"),
    ("pci-dss", "PCI DSS 4.0"),
    ("hipaa", "HIPAA Security Rule"),
)


def _relationship_table() -> list[str]:
    meaning = {
        "equivalent": "the same requirement in different words",
        "superset": "the source is broader; satisfying it covers the target",
        "subset": "the source is narrower; satisfying it is not enough",
        "related": "a pointer for a human",
    }
    rows = ["| Relationship | Meaning | Carries a verdict |", "|---|---|---|"]
    for relationship, (confidence, ceiling) in INHERITANCE.items():
        name = str(relationship)
        if ceiling is None:
            carries = "**never**"
        elif str(ceiling) == "partial":
            carries = f"only ever a partial, at {confidence}"
        else:
            carries = f"yes, at {confidence} confidence"
        rows.append(f"| `{name}` | {meaning[name]} | {carries} |")
    return rows


def build(crosswalk: Crosswalk) -> str:
    hub = load_framework(HUB)

    lines = [
        "# Cross-framework control mapping",
        "",
        "**Generated from `frameworks/crosswalks/*.json` — do not edit by hand.**",
        "Regenerate with `python tools/build_control_mapping.py`.",
        "",
        f"{hub.name} is the hub. A client evidences a control once against it and the",
        "engine projects that verdict onto the other frameworks, so the same",
        "access-control policy is not requested three times over.",
        "",
        "## What a relationship means",
        "",
        "The direction is recorded, not assumed, because getting it backwards would let",
        "a narrow control claim to cover a broad one.",
        "",
        *_relationship_table(),
        "",
        "A projected verdict can never be better than the verdict it came from, and is",
        "always labelled as inherited, naming the control it came from. Nothing",
        "projected is presented as directly evidenced.",
        "",
        "An accepted risk never travels: a risk one board signed for under one framework",
        "is not an answer to a different framework's auditor.",
        "",
        "## Coverage",
        "",
        "| Target framework | Controls | Addressed by a SOC 2 assessment | Needs direct review |",
        "|---|---|---|---|",
    ]

    for alias, label in TARGETS:
        framework = load_framework(alias)
        control_ids = [c.id for c in framework.controls]
        coverage = crosswalk.coverage(hub.id, framework.id, control_ids)
        mapped = round(coverage * len(control_ids))
        lines.append(
            f"| {label} | {len(control_ids)} | {coverage:.0%} | {len(control_ids) - mapped} |"
        )

    for alias, label in TARGETS:
        framework = load_framework(alias)
        lines += [
            "",
            f"## SOC 2 → {label}",
            "",
            "| SOC 2 | Criterion | Maps to | Relationship | Note |",
            "|---|---|---|---|---|",
        ]
        rows = [
            (control.id, control.name, edge.target_control, str(edge.relationship), edge.note)
            for control in hub.controls
            for edge in crosswalk.map_control(hub.id, control.id, framework.id)
        ]
        for control_id, name, target, relationship, note in sorted(
            rows, key=lambda row: (row[0], row[2])
        ):
            lines.append(f"| `{control_id}` | {name} | `{target}` | {relationship} | {note} |")

        unmapped = sorted({c.id for c in framework.controls} - {row[2] for row in rows})
        if unmapped:
            lines += [
                "",
                f"**No SOC 2 mapping ({len(unmapped)}):** "
                + ", ".join(f"`{control_id}`" for control_id in unmapped)
                + f". These require a direct assessment against {label}.",
            ]

    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    document = build(load_crosswalks())

    if "--check" in args:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != document:
            print(
                f"{OUTPUT.relative_to(REPO_ROOT)} is out of date — "
                f"run: python tools/build_control_mapping.py",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT.relative_to(REPO_ROOT)} is current")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(document, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
