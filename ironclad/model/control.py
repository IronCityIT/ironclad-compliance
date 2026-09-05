"""Controls and frameworks.

A Framework is a versioned set of Controls. A Control carries the criterion text,
its points of focus (the sub-assertions an auditor actually walks), and the
evidence types that typically satisfy it. `common_evidence` is what drives
automated evidence matching, so it is part of the model rather than a doc note.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Weight by control family. Access control and incident response failures carry
# more audit and breach risk than a governance documentation gap, so a gap in
# CC6 outranks a gap in CC1 when remediation work is prioritised. Families not
# listed here take DEFAULT_WEIGHT.
FAMILY_WEIGHT: dict[str, float] = {
    "CC6": 1.5,  # logical and physical access
    "CC7": 1.4,  # system operations, detection and incident response
    "CC8": 1.2,  # change management
    "CC9": 1.2,  # risk mitigation and vendor management
    "PR": 1.5,  # NIST CSF protect
    "DE": 1.4,  # NIST CSF detect
    "RS": 1.4,  # NIST CSF respond
    "164.312": 1.5,  # HIPAA technical safeguards
    "164.308": 1.3,  # HIPAA administrative safeguards
    "7": 1.5,  # PCI DSS restrict access by business need to know
    "8": 1.5,  # PCI DSS identify users and authenticate access
    "3": 1.5,  # PCI DSS protect stored account data
    "4": 1.4,  # PCI DSS protect data in transit
    "10": 1.4,  # PCI DSS log and monitor
    "11": 1.3,  # PCI DSS test security regularly
    "6": 1.2,  # PCI DSS secure systems and software
    "1": 1.2,  # PCI DSS network security controls
}
DEFAULT_WEIGHT = 1.0


@dataclass(frozen=True)
class PointOfFocus:
    """One sub-assertion beneath a control."""

    id: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "description": self.description}


@dataclass(frozen=True)
class Control:
    """A single framework criterion."""

    id: str
    name: str
    description: str
    points_of_focus: tuple[PointOfFocus, ...] = ()
    common_evidence: tuple[str, ...] = ()
    domain: str = ""

    @property
    def family(self) -> str:
        """The control family this control belongs to.

        Three id shapes are in play across the supported frameworks:

            CC6.1                -> CC6      (SOC 2)
            PR.AA-05             -> PR       (NIST CSF function)
            10.2                 -> 10       (PCI DSS requirement)
            164.312(a)(1)        -> 164.312  (HIPAA CFR section)

        HIPAA is the one case where two dotted segments are kept, because the
        section number is what carries the meaning; the parenthesised suffix is
        the implementation specification. The parenthesis is what identifies it,
        not the digits, so a PCI requirement like `10.2` is not mistaken for one.
        """
        head = self.id.split("(", 1)[0].rstrip(".")
        if "(" in self.id and "." in head:
            return ".".join(head.split(".")[:2])
        for sep in (".", "-", "_"):
            if sep in head:
                return head.split(sep, 1)[0]
        return head

    @property
    def weight(self) -> float:
        """Risk weight used to prioritise remediation of a gap in this control."""
        return FAMILY_WEIGHT.get(self.family, DEFAULT_WEIGHT)

    def keywords(self) -> set[str]:
        """Terms that indicate a document is relevant to this control.

        Drawn from the evidence types and the control name rather than the full
        criterion text: criterion prose is boilerplate-heavy ("the entity",
        "policies and procedures") and matching on it produces noise.
        """
        terms: set[str] = set()
        for phrase in (*self.common_evidence, self.name, *(p.description for p in self.points_of_focus)):
            for word in phrase.lower().replace("/", " ").replace("-", " ").split():
                cleaned = word.strip(".,()")
                if len(cleaned) > 3 and cleaned not in STOPWORDS:
                    terms.add(cleaned)
        return terms

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "family": self.family,
            "weight": self.weight,
            "domain": self.domain,
            "points_of_focus": [p.to_dict() for p in self.points_of_focus],
            "common_evidence": list(self.common_evidence),
        }


# Words that appear in nearly every control and every policy document. Matching
# on them would make every artifact look relevant to every control.
STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "their",
        "entity", "entitys", "organization", "organizations", "system", "systems",
        "policy", "policies", "procedure", "procedures", "documentation", "records",
        "management", "process", "processes", "controls", "control", "information",
        "data", "using", "used", "such", "other", "also", "including", "these",
    }
)


@dataclass(frozen=True)
class Framework:
    """A versioned control set."""

    id: str
    name: str
    version: str
    source: str = ""
    controls: tuple[Control, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for control in self.controls:
            if control.id in seen:
                raise ValueError(f"duplicate control id {control.id!r} in framework {self.id!r}")
            seen.add(control.id)

    @property
    def key(self) -> str:
        """`<id>@<version>` — how a crosswalk and an assessment refer to it."""
        return f"{self.id}@{self.version}"

    def get(self, control_id: str) -> Control | None:
        for control in self.controls:
            if control.id == control_id:
                return control
        return None

    def families(self) -> list[str]:
        return sorted({c.family for c in self.controls})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "source": self.source,
            "control_count": len(self.controls),
        }
