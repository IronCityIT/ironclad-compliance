"""Load and validate framework documents.

Validation is strict and reports every problem at once rather than dying on the
first. A framework file is the definition of what the product measures against;
a half-valid one that loads anyway would produce a report that is wrong in a way
nobody notices.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ironclad.errors import FrameworkError, ValidationError
from ironclad.ids import is_safe_document_id
from ironclad.model.control import Control, Framework, PointOfFocus

# The short names the workflow inputs and the CLI accept, mapped to the file that
# backs them. The workflow's `framework` choice list must stay in step with this.
FRAMEWORK_ALIASES: dict[str, str] = {
    "soc2": "soc2-2017.json",
    "nist-csf": "nist-csf-2.0.json",
    "pci-dss": "pci-dss-4.0.json",
    "hipaa": "hipaa-security-rule.json",
}

DEFAULT_FRAMEWORK_DIR = Path(__file__).resolve().parents[2] / "frameworks"


def resolve_framework_path(name: str, framework_dir: Path | None = None) -> Path:
    """Turn an alias, a file name or a path into the file to load."""
    directory = framework_dir or DEFAULT_FRAMEWORK_DIR

    candidate = Path(name)
    if candidate.suffix == ".json" and candidate.exists():
        return candidate

    filename = FRAMEWORK_ALIASES.get(name, name if name.endswith(".json") else f"{name}.json")
    path = directory / filename
    if not path.exists():
        known = ", ".join(sorted(FRAMEWORK_ALIASES))
        raise FrameworkError(f"no framework file for {name!r} at {path} (known aliases: {known})")
    return path


def validate_framework_document(document: Any) -> list[str]:
    """Return every structural problem with a framework document.

    Empty list means the document is loadable.
    """
    errors: list[str] = []

    if not isinstance(document, dict):
        return ["framework document must be a JSON object"]

    meta = document.get("framework")
    if not isinstance(meta, dict):
        errors.append("missing 'framework' object")
    else:
        for key in ("id", "name", "version"):
            if not str(meta.get(key, "")).strip():
                errors.append(f"framework.{key} is required")

    controls = document.get("controls")
    if not isinstance(controls, list) or not controls:
        errors.append("'controls' must be a non-empty array")
        return errors

    seen: set[str] = set()
    for index, control in enumerate(controls):
        where = f"controls[{index}]"
        if not isinstance(control, dict):
            errors.append(f"{where} must be an object")
            continue
        control_id = str(control.get("id", "")).strip()
        if not control_id:
            errors.append(f"{where}.id is required")
        elif control_id in seen:
            errors.append(f"{where}.id {control_id!r} is a duplicate")
        elif not is_safe_document_id(control_id):
            # The id is stored as a document id downstream. A control whose id
            # cannot be stored disappears from the client's record without an
            # error anywhere, so it is refused here, where it can be named.
            errors.append(f"{where}.id {control_id!r} cannot be used as a stored identifier")
        else:
            seen.add(control_id)
        for key in ("name", "description"):
            if not str(control.get(key, "")).strip():
                errors.append(f"{where}({control_id}).{key} is required")

        focus = control.get("points_of_focus", [])
        if not isinstance(focus, list):
            errors.append(f"{where}({control_id}).points_of_focus must be an array")
        else:
            for f_index, point in enumerate(focus):
                if not isinstance(point, dict) or not str(point.get("description", "")).strip():
                    errors.append(
                        f"{where}({control_id}).points_of_focus[{f_index}] needs a description"
                    )

        evidence = control.get("common_evidence", [])
        if not isinstance(evidence, list):
            errors.append(f"{where}({control_id}).common_evidence must be an array")

    return errors


def framework_from_document(document: dict[str, Any]) -> Framework:
    """Build the Framework object. Assumes the document already validated."""
    meta = document["framework"]
    controls = tuple(
        Control(
            id=str(raw["id"]).strip(),
            name=str(raw["name"]).strip(),
            description=str(raw["description"]).strip(),
            points_of_focus=tuple(
                PointOfFocus(
                    id=str(point.get("id") or f"{raw['id']}.{n + 1}"),
                    description=str(point["description"]).strip(),
                )
                for n, point in enumerate(raw.get("points_of_focus", []))
            ),
            common_evidence=tuple(str(e).strip() for e in raw.get("common_evidence", [])),
            domain=str(raw.get("domain", "")).strip(),
        )
        for raw in document["controls"]
    )
    return Framework(
        id=str(meta["id"]).strip(),
        name=str(meta["name"]).strip(),
        version=str(meta["version"]).strip(),
        source=str(meta.get("source", "")).strip(),
        controls=controls,
    )


def load_framework(name: str, framework_dir: Path | None = None) -> Framework:
    """Resolve, parse, validate and build a framework in one call."""
    path = resolve_framework_path(name, framework_dir)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FrameworkError(f"{path} is not valid JSON: {exc}") from exc

    errors = validate_framework_document(document)
    if errors:
        raise ValidationError(f"{path.name} is not a valid framework document", errors)

    return framework_from_document(document)


def available_frameworks(framework_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every framework on disk, for the CLI listing and the dashboard picker."""
    directory = framework_dir or DEFAULT_FRAMEWORK_DIR
    entries: list[dict[str, Any]] = []
    for alias, filename in sorted(FRAMEWORK_ALIASES.items()):
        path = directory / filename
        if not path.exists():
            continue
        try:
            framework = load_framework(alias, directory)
        except (FrameworkError, ValidationError):
            continue
        entries.append({"alias": alias, **framework.to_dict()})
    return entries
