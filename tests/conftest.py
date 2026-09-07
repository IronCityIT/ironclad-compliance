"""Shared fixtures.

Every test runs against a fixed `NOW`. Freshness, expiry and SLA dates are all
relative to the moment of assessment, so a suite that used the wall clock would
pass in September and fail in December.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ironclad.frameworks.crosswalk import Crosswalk, CrosswalkEdge, Relationship
from ironclad.ids import artifact_id
from ironclad.model.assessment import ControlAssessment
from ironclad.model.control import Control, Framework, PointOfFocus
from ironclad.model.evidence import EvidenceArtifact, EvidenceSet

NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def framework_dir() -> Path:
    return REPO_ROOT / "frameworks"


@pytest.fixture
def tiny_framework() -> Framework:
    """Three controls: one heavily weighted, one light, one with no points."""
    return Framework(
        id="test-fw",
        name="Test Framework",
        version="1.0",
        source="tests",
        controls=(
            Control(
                id="CC6.1",
                name="Logical Access",
                description="Access to protected assets is restricted.",
                points_of_focus=(
                    PointOfFocus(id="CC6.1.1", description="Restricts logical access"),
                    PointOfFocus(id="CC6.1.2", description="Registers authorized users"),
                ),
                common_evidence=("Access control policy", "User access review"),
            ),
            Control(
                id="CC1.1",
                name="Ethical Values",
                description="The entity commits to integrity and ethical values.",
                points_of_focus=(
                    PointOfFocus(id="CC1.1.1", description="Sets the tone at the top"),
                ),
                common_evidence=("Code of conduct", "Ethics policy"),
            ),
            Control(
                id="CC9.9",
                name="Zeppelin Mooring",
                description="Nothing in the evidence set will match this.",
                common_evidence=("Zeppelin mooring schedule",),
            ),
        ),
    )


def make_artifact(
    name: str,
    text: str,
    tenant: str = "acme",
    evidence_type: str = "",
    collected_at: datetime | None = None,
    valid_until: datetime | None = None,
    hints: list[str] | None = None,
) -> EvidenceArtifact:
    uri = f"/evidence/{name}"
    return EvidenceArtifact(
        artifact_id=artifact_id(tenant, uri),
        tenant_id=tenant,
        name=name,
        uri=uri,
        evidence_type=evidence_type or name,
        collected_at=collected_at or NOW,
        valid_until=valid_until,
        control_hints=list(hints or []),
        text=text,
    )


@pytest.fixture
def evidence() -> EvidenceSet:
    """Two current items that between them corroborate CC6.1 and CC1.1."""
    evidence_set = EvidenceSet(tenant_id="acme")
    evidence_set.add(
        make_artifact(
            "Access Control Policy",
            "Access control policy. Restricts logical access, registers authorized users, "
            "least privilege, role definitions. Code of conduct and ethics policy referenced.",
            evidence_type="Access control policy",
        )
    )
    evidence_set.add(
        make_artifact(
            "User Access Review Q3",
            "User access review. Registers authorized users, restricts logical access, "
            "reviewer sign-off. Code of conduct acknowledged, ethics policy, tone at the top.",
            evidence_type="User access review",
        )
    )
    return evidence_set


@pytest.fixture
def stale_evidence() -> EvidenceSet:
    """The same two items, both well past their currency window."""
    old = NOW - timedelta(days=400)
    evidence_set = EvidenceSet(tenant_id="acme")
    evidence_set.add(
        make_artifact(
            "Access Control Policy",
            "Access control policy. Restricts logical access, registers authorized users.",
            evidence_type="Access control policy",
            collected_at=old,
            valid_until=NOW - timedelta(days=30),
        )
    )
    evidence_set.add(
        make_artifact(
            "User Access Review Q1 2025",
            "User access review. Registers authorized users, restricts logical access.",
            evidence_type="User access review",
            collected_at=old,
            valid_until=NOW - timedelta(days=30),
        )
    )
    return evidence_set


@pytest.fixture
def crosswalk() -> Crosswalk:
    return Crosswalk(
        [
            CrosswalkEdge("test-fw", "CC6.1", "other-fw", "AC-1", Relationship.EQUIVALENT),
            CrosswalkEdge("test-fw", "CC6.1", "other-fw", "AC-2", Relationship.SUBSET),
            CrosswalkEdge("test-fw", "CC1.1", "other-fw", "GV-1", Relationship.RELATED),
        ]
    )


def verdict_for(result, control_id: str) -> ControlAssessment:
    """The verdict on one control, failing loudly if the run did not produce it.

    Assessment.get returns None for an unknown control, which in a test reads as
    an AttributeError several lines from the real problem.
    """
    verdict = result.assessment.get(control_id)
    assert verdict is not None, f"the run produced no verdict for {control_id}"
    return verdict
