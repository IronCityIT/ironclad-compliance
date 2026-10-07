"""Module discovery, selection and ordering.

The single catalog the CLI (`--list-modules`) and the dashboard (module
checkboxes plus group presets) both render from. Selection in the UI maps 1:1
onto `--modules` / `--group`; there is no second source of truth.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from ironclad.base import AssessmentModule
from ironclad.errors import SelectionError

MODULE_PACKAGE = "ironclad.modules"
DEFAULT_GROUP = "standard"


def discover(package: str = MODULE_PACKAGE) -> dict[str, AssessmentModule]:
    """Import every module file in the package and instantiate each capability."""
    root = importlib.import_module(package)
    found: dict[str, AssessmentModule] = {}

    for _, modname, _ in pkgutil.iter_modules(root.__path__):
        submodule = importlib.import_module(f"{package}.{modname}")
        for _, obj in inspect.getmembers(submodule, inspect.isclass):
            if not issubclass(obj, AssessmentModule) or obj is AssessmentModule:
                continue
            if inspect.isabstract(obj):
                continue
            instance = obj()
            if not instance.name:
                raise SelectionError(f"{obj.__name__} declares no name")
            if instance.name in found and type(found[instance.name]) is not obj:
                raise SelectionError(f"two capabilities both claim the name {instance.name!r}")
            found[instance.name] = instance

    return found


def all_groups(registry: dict[str, AssessmentModule]) -> set[str]:
    return {group for module in registry.values() for group in module.groups}


def order(
    registry: dict[str, AssessmentModule], chosen: list[AssessmentModule]
) -> list[AssessmentModule]:
    """Order the selection so every declared prerequisite runs first.

    Prerequisites are pulled in even when the caller did not select them: asking
    for the remediation plan alone and getting an empty one because nothing had
    assessed the controls yet would be a confusing way to be wrong.
    """
    resolved: list[AssessmentModule] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def visit(module: AssessmentModule) -> None:
        if module.name in placed:
            return
        if module.name in visiting:
            raise SelectionError(f"capability {module.name!r} is part of a dependency cycle")
        visiting.add(module.name)
        for requirement in module.requires:
            dependency = registry.get(requirement)
            if dependency is None:
                raise SelectionError(
                    f"capability {module.name!r} requires {requirement!r}, which is not registered"
                )
            visit(dependency)
        visiting.discard(module.name)
        placed.add(module.name)
        resolved.append(module)

    for module in chosen:
        visit(module)
    return resolved


def select(
    registry: dict[str, AssessmentModule],
    modules: list[str] | None = None,
    group: str | None = None,
) -> list[AssessmentModule]:
    """Resolve a selection. `modules` wins if given; else `group`; else standard."""
    if modules:
        missing = [name for name in modules if name not in registry]
        if missing:
            raise SelectionError(
                f"unknown capabilities: {', '.join(sorted(missing))} "
                f"(available: {', '.join(sorted(registry))})"
            )
        chosen = [registry[name] for name in modules]
    else:
        wanted = group or DEFAULT_GROUP
        chosen = sorted((m for m in registry.values() if wanted in m.groups), key=lambda m: m.name)
        if not chosen:
            raise SelectionError(
                f"no capabilities in group {wanted!r}; "
                f"groups: {', '.join(sorted(all_groups(registry)))}"
            )

    return order(registry, chosen)


def catalog(registry: dict[str, AssessmentModule]) -> list[dict[str, Any]]:
    """Machine-readable capability list for --list-modules and the dashboard."""
    return [
        {
            "name": module.name,
            "description": module.description,
            "groups": list(module.groups),
            "requires": list(module.requires),
        }
        for module in sorted(registry.values(), key=lambda m: m.name)
    ]
