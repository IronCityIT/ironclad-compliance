"""Cross-framework crosswalks.

The commercial point of a crosswalk is "assess once, report many": a tenant that
has evidenced SOC 2 CC6.1 has substantially evidenced NIST CSF PR.AA-01 and HIPAA
164.312(a)(1) too, and should not be asked for the same access-control policy
three times.

Two rules keep that honest rather than optimistic:

  * The relationship type is recorded, not assumed. `equivalent` carries a
    verdict at full confidence; `subset` means the source is narrower than the
    target and can only ever support a partial; `related` is a pointer for a
    human, never an automatic verdict.
  * An inherited verdict is always marked inherited, with the control it came
    from. No inherited result is ever presented as directly evidenced.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ironclad.errors import ValidationError
from ironclad.model.assessment import ControlStatus

DEFAULT_CROSSWALK_DIR = Path(__file__).resolve().parents[2] / "frameworks" / "crosswalks"


class Relationship(str, Enum):
    """How the source control relates to the target control."""

    EQUIVALENT = "equivalent"  # same requirement, different wording
    SUBSET = "subset"  # source is narrower: satisfying it is not enough
    SUPERSET = "superset"  # source is broader: satisfying it covers the target
    RELATED = "related"  # informational only

    def __str__(self) -> str:
        return self.value


# How much confidence survives the hop, and the best verdict it can produce.
INHERITANCE: dict[Relationship, tuple[float, ControlStatus | None]] = {
    Relationship.EQUIVALENT: (0.9, ControlStatus.COMPLIANT),
    Relationship.SUPERSET: (0.8, ControlStatus.COMPLIANT),
    Relationship.SUBSET: (0.5, ControlStatus.PARTIAL),
    Relationship.RELATED: (0.0, None),  # never inherits a verdict
}


@dataclass(frozen=True)
class CrosswalkEdge:
    """One mapping between a control in one framework and one in another."""

    source_framework: str
    source_control: str
    target_framework: str
    target_control: str
    relationship: Relationship = Relationship.RELATED
    note: str = ""

    def inverted(self) -> CrosswalkEdge:
        """The same mapping seen from the target side.

        Direction matters: the inverse of a subset is a superset. Getting this
        backwards would let a narrow control claim to cover a broad one.
        """
        flip = {
            Relationship.SUBSET: Relationship.SUPERSET,
            Relationship.SUPERSET: Relationship.SUBSET,
        }
        return CrosswalkEdge(
            source_framework=self.target_framework,
            source_control=self.target_control,
            target_framework=self.source_framework,
            target_control=self.source_control,
            relationship=flip.get(self.relationship, self.relationship),
            note=self.note,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_framework": self.source_framework,
            "source_control": self.source_control,
            "target_framework": self.target_framework,
            "target_control": self.target_control,
            "relationship": str(self.relationship),
            "note": self.note,
        }


@dataclass
class InheritedVerdict:
    """A verdict carried to another framework's control by a crosswalk."""

    control_id: str
    status: ControlStatus
    confidence: float
    from_framework: str
    from_control: str
    relationship: Relationship

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "status": str(self.status),
            "confidence": round(self.confidence, 3),
            "inherited_from": f"{self.from_framework}:{self.from_control}",
            "relationship": str(self.relationship),
        }


class Crosswalk:
    """An index over crosswalk edges, queryable in both directions."""

    def __init__(self, edges: list[CrosswalkEdge] | None = None) -> None:
        self._edges: list[CrosswalkEdge] = []
        self._by_source: dict[tuple[str, str], list[CrosswalkEdge]] = defaultdict(list)
        for edge in edges or []:
            self.add(edge)

    def __len__(self) -> int:
        return len(self._edges)

    @property
    def edges(self) -> list[CrosswalkEdge]:
        return list(self._edges)

    def add(self, edge: CrosswalkEdge) -> None:
        """Index an edge and its inverse, so lookups work from either side."""
        self._edges.append(edge)
        self._by_source[(edge.source_framework, edge.source_control)].append(edge)
        inverse = edge.inverted()
        self._by_source[(inverse.source_framework, inverse.source_control)].append(inverse)

    def frameworks(self) -> list[str]:
        names = {e.source_framework for e in self._edges} | {
            e.target_framework for e in self._edges
        }
        return sorted(names)

    def map_control(
        self, framework_id: str, control_id: str, to_framework: str | None = None
    ) -> list[CrosswalkEdge]:
        """Every control that maps to this one, optionally in one target framework."""
        found = self._by_source.get((framework_id, control_id), [])
        if to_framework:
            found = [e for e in found if e.target_framework == to_framework]
        return list(found)

    def coverage(self, framework_id: str, target_framework: str, control_ids: list[str]) -> float:
        """Fraction of `control_ids` in the target that any source control maps to.

        This is what tells a tenant "your SOC 2 programme already addresses 68%
        of NIST CSF" before they commission a second assessment.
        """
        if not control_ids:
            return 0.0
        # _by_source already holds both directions, so a mapping authored as
        # NIST -> SOC 2 still counts when asking what SOC 2 covers in NIST.
        mapped = {
            edge.target_control
            for (source_fw, _control), edges in self._by_source.items()
            if source_fw == framework_id
            for edge in edges
            if edge.target_framework == target_framework
        }
        return round(len(mapped & set(control_ids)) / len(control_ids), 3)

    def inherit(
        self,
        source_framework: str,
        verdicts: Mapping[str, ControlStatus],
        target_framework: str,
    ) -> dict[str, InheritedVerdict]:
        """Project assessed verdicts onto another framework's controls.

        When several source controls map to the same target, the weakest verdict
        wins: a target control is only as evidenced as its least-evidenced input.
        """
        projected: dict[str, InheritedVerdict] = {}

        for source_control, status in verdicts.items():
            for edge in self.map_control(source_framework, source_control, target_framework):
                confidence, ceiling = INHERITANCE[edge.relationship]
                if ceiling is None:
                    continue

                # A source verdict can never be improved by travelling. Cap it at
                # what the relationship allows and at what was actually assessed.
                carried = _weaker(status, ceiling)
                if carried is ControlStatus.PENDING:
                    continue

                candidate = InheritedVerdict(
                    control_id=edge.target_control,
                    status=carried,
                    confidence=confidence,
                    from_framework=source_framework,
                    from_control=source_control,
                    relationship=edge.relationship,
                )
                existing = projected.get(edge.target_control)
                if existing is None or _is_weaker(candidate.status, existing.status):
                    projected[edge.target_control] = candidate

        return projected

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_count": len(self._edges),
            "frameworks": self.frameworks(),
            "edges": [e.to_dict() for e in self._edges],
        }


# Ranked weakest-first for inheritance decisions. Statuses not listed (accepted
# risk, not applicable) never travel: a risk one organisation's board accepted
# under one framework is not an answer to another framework's auditor.
_INHERIT_RANK: tuple[ControlStatus, ...] = (
    ControlStatus.GAP,
    ControlStatus.PARTIAL,
    ControlStatus.COMPLIANT,
)


def _rank(status: ControlStatus) -> int:
    return _INHERIT_RANK.index(status) if status in _INHERIT_RANK else -1


def _weaker(left: ControlStatus, right: ControlStatus) -> ControlStatus:
    if _rank(left) < 0 or _rank(right) < 0:
        return ControlStatus.PENDING
    return left if _rank(left) <= _rank(right) else right


def _is_weaker(left: ControlStatus, right: ControlStatus) -> bool:
    return _rank(left) < _rank(right)


def validate_crosswalk_document(document: Any) -> list[str]:
    """Every structural problem with a crosswalk document."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["crosswalk document must be a JSON object"]

    mappings = document.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        return ["'mappings' must be a non-empty array"]

    valid = {r.value for r in Relationship}
    for index, mapping in enumerate(mappings):
        where = f"mappings[{index}]"
        if not isinstance(mapping, dict):
            errors.append(f"{where} must be an object")
            continue
        for key in ("source_framework", "source_control", "target_framework", "target_control"):
            if not str(mapping.get(key, "")).strip():
                errors.append(f"{where}.{key} is required")
        relationship = str(mapping.get("relationship", "related"))
        if relationship not in valid:
            errors.append(f"{where}.relationship {relationship!r} is not one of {sorted(valid)}")
        if mapping.get("source_framework") == mapping.get("target_framework"):
            errors.append(f"{where} maps a framework onto itself")
    return errors


def load_crosswalks(crosswalk_dir: Path | None = None) -> Crosswalk:
    """Load every crosswalk file in the directory into one index."""
    directory = crosswalk_dir or DEFAULT_CROSSWALK_DIR
    crosswalk = Crosswalk()
    if not directory.exists():
        return crosswalk

    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_crosswalk_document(document)
        if errors:
            raise ValidationError(f"{path.name} is not a valid crosswalk document", errors)
        for mapping in document["mappings"]:
            crosswalk.add(
                CrosswalkEdge(
                    source_framework=str(mapping["source_framework"]),
                    source_control=str(mapping["source_control"]),
                    target_framework=str(mapping["target_framework"]),
                    target_control=str(mapping["target_control"]),
                    relationship=Relationship(str(mapping.get("relationship", "related"))),
                    note=str(mapping.get("note", "")),
                )
            )
    return crosswalk
