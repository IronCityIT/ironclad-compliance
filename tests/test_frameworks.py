"""Framework loading, validation, and the crosswalk direction rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ironclad.errors import FrameworkError, ValidationError
from ironclad.frameworks.crosswalk import (
    Crosswalk,
    CrosswalkEdge,
    Relationship,
    load_crosswalks,
    validate_crosswalk_document,
)
from ironclad.frameworks.loader import (
    FRAMEWORK_ALIASES,
    available_frameworks,
    load_framework,
    validate_framework_document,
)
from ironclad.model.assessment import ControlStatus


class TestShippedFrameworks:
    @pytest.mark.parametrize("alias", sorted(FRAMEWORK_ALIASES))
    def test_every_shipped_framework_loads(self, alias: str, framework_dir: Path) -> None:
        framework = load_framework(alias, framework_dir)
        assert framework.controls
        assert framework.version

    @pytest.mark.parametrize("alias", sorted(FRAMEWORK_ALIASES))
    def test_every_control_has_evidence_guidance(self, alias: str, framework_dir: Path) -> None:
        # Without expected evidence types a control cannot be matched and cannot
        # produce useful remediation guidance.
        framework = load_framework(alias, framework_dir)
        missing = [c.id for c in framework.controls if not c.common_evidence]
        assert not missing, f"{alias} controls with no expected evidence: {missing}"

    @pytest.mark.parametrize("alias", sorted(FRAMEWORK_ALIASES))
    def test_control_keywords_are_never_empty(self, alias: str, framework_dir: Path) -> None:
        framework = load_framework(alias, framework_dir)
        empty = [c.id for c in framework.controls if not c.keywords()]
        assert not empty, f"{alias} controls that can never match: {empty}"

    def test_all_four_frameworks_are_discoverable(self, framework_dir: Path) -> None:
        aliases = {entry["alias"] for entry in available_frameworks(framework_dir)}
        assert aliases == set(FRAMEWORK_ALIASES)


class TestFrameworkValidation:
    def test_a_valid_document_reports_no_errors(self) -> None:
        document = {
            "framework": {"id": "f", "name": "F", "version": "1"},
            "controls": [{"id": "C1", "name": "n", "description": "d"}],
        }
        assert validate_framework_document(document) == []

    def test_every_fault_is_reported_at_once(self) -> None:
        document = {
            "framework": {"id": "", "name": "F"},
            "controls": [
                {"id": "C1", "name": "", "description": "d"},
                {"id": "C1", "name": "n", "description": ""},
            ],
        }
        errors = validate_framework_document(document)
        # Not just the first: a half-valid framework that loads anyway produces
        # a report that is wrong in a way nobody notices.
        assert len(errors) >= 4
        assert any("version" in e for e in errors)
        assert any("duplicate" in e for e in errors)

    def test_a_non_object_document_is_rejected(self) -> None:
        assert validate_framework_document(["not", "an", "object"])

    def test_an_empty_control_list_is_rejected(self) -> None:
        errors = validate_framework_document(
            {"framework": {"id": "f", "name": "F", "version": "1"}, "controls": []}
        )
        assert any("non-empty" in e for e in errors)

    def test_an_unknown_alias_raises(self, framework_dir: Path) -> None:
        with pytest.raises(FrameworkError, match="no framework file"):
            load_framework("iso-27001", framework_dir)

    def test_a_malformed_file_raises_with_every_fault(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"framework": {}, "controls": [{"id": ""}]}))
        with pytest.raises(ValidationError) as caught:
            load_framework(str(bad), tmp_path)
        assert caught.value.errors


class TestCrosswalkDirection:
    def test_inverting_a_subset_yields_a_superset(self) -> None:
        # Getting this backwards would let a narrow control claim to cover a
        # broad one, which is the whole risk of an automated crosswalk.
        edge = CrosswalkEdge("a", "A1", "b", "B1", Relationship.SUBSET)
        assert edge.inverted().relationship is Relationship.SUPERSET

    def test_inverting_an_equivalence_leaves_it_equivalent(self) -> None:
        edge = CrosswalkEdge("a", "A1", "b", "B1", Relationship.EQUIVALENT)
        assert edge.inverted().relationship is Relationship.EQUIVALENT

    def test_lookups_work_from_either_side(self, crosswalk: Crosswalk) -> None:
        forward = crosswalk.map_control("test-fw", "CC6.1", "other-fw")
        backward = crosswalk.map_control("other-fw", "AC-1", "test-fw")
        assert forward and backward


class TestInheritance:
    def test_an_equivalent_mapping_carries_a_pass(self, crosswalk: Crosswalk) -> None:
        projected = crosswalk.inherit("test-fw", {"CC6.1": ControlStatus.COMPLIANT}, "other-fw")
        assert projected["AC-1"].status is ControlStatus.COMPLIANT

    def test_a_subset_mapping_can_only_carry_a_partial(self, crosswalk: Crosswalk) -> None:
        # The source control is narrower than the target, so satisfying it is
        # not enough to satisfy the target.
        projected = crosswalk.inherit("test-fw", {"CC6.1": ControlStatus.COMPLIANT}, "other-fw")
        assert projected["AC-2"].status is ControlStatus.PARTIAL

    def test_a_related_mapping_never_carries_a_verdict(self, crosswalk: Crosswalk) -> None:
        projected = crosswalk.inherit("test-fw", {"CC1.1": ControlStatus.COMPLIANT}, "other-fw")
        assert "GV-1" not in projected

    def test_travelling_never_improves_a_verdict(self, crosswalk: Crosswalk) -> None:
        projected = crosswalk.inherit("test-fw", {"CC6.1": ControlStatus.GAP}, "other-fw")
        assert projected["AC-1"].status is ControlStatus.GAP

    def test_the_weakest_input_wins_when_several_map_to_one_target(self) -> None:
        crosswalk = Crosswalk(
            [
                CrosswalkEdge("a", "A1", "b", "B1", Relationship.EQUIVALENT),
                CrosswalkEdge("a", "A2", "b", "B1", Relationship.EQUIVALENT),
            ]
        )
        projected = crosswalk.inherit(
            "a", {"A1": ControlStatus.COMPLIANT, "A2": ControlStatus.GAP}, "b"
        )
        assert projected["B1"].status is ControlStatus.GAP

    def test_an_inherited_verdict_names_where_it_came_from(self, crosswalk: Crosswalk) -> None:
        projected = crosswalk.inherit("test-fw", {"CC6.1": ControlStatus.COMPLIANT}, "other-fw")
        assert projected["AC-1"].from_control == "CC6.1"
        assert projected["AC-1"].confidence < 1.0

    def test_accepted_risk_does_not_travel(self) -> None:
        # A risk one board accepted under one framework is not an answer to a
        # different framework's auditor.
        crosswalk = Crosswalk([CrosswalkEdge("a", "A1", "b", "B1", Relationship.EQUIVALENT)])
        assert crosswalk.inherit("a", {"A1": ControlStatus.ACCEPTED_RISK}, "b") == {}


class TestShippedCrosswalks:
    def test_the_shipped_crosswalks_load(self, framework_dir: Path) -> None:
        crosswalk = load_crosswalks(framework_dir / "crosswalks")
        assert len(crosswalk) > 50

    def test_every_mapping_points_at_a_control_that_exists(self, framework_dir: Path) -> None:
        crosswalk = load_crosswalks(framework_dir / "crosswalks")
        known: dict[str, set[str]] = {}
        for alias in FRAMEWORK_ALIASES:
            framework = load_framework(alias, framework_dir)
            known[framework.id] = {c.id for c in framework.controls}

        dangling = [
            f"{edge.source_framework}:{edge.source_control} -> "
            f"{edge.target_framework}:{edge.target_control}"
            for edge in crosswalk.edges
            if edge.source_control not in known.get(edge.source_framework, set())
            or edge.target_control not in known.get(edge.target_framework, set())
        ]
        assert not dangling, f"crosswalk mappings to controls that do not exist: {dangling}"

    def test_soc2_meaningfully_covers_the_other_frameworks(self, framework_dir: Path) -> None:
        crosswalk = load_crosswalks(framework_dir / "crosswalks")
        for alias in ("nist-csf", "pci-dss", "hipaa"):
            target = load_framework(alias, framework_dir)
            coverage = crosswalk.coverage("soc2-tsc", target.id, [c.id for c in target.controls])
            assert coverage > 0.5, f"SOC 2 covers only {coverage:.0%} of {alias}"

    def test_a_self_mapping_is_rejected(self) -> None:
        errors = validate_crosswalk_document(
            {
                "mappings": [
                    {
                        "source_framework": "a",
                        "source_control": "1",
                        "target_framework": "a",
                        "target_control": "2",
                    }
                ]
            }
        )
        assert any("onto itself" in e for e in errors)

    def test_an_unknown_relationship_is_rejected(self) -> None:
        errors = validate_crosswalk_document(
            {
                "mappings": [
                    {
                        "source_framework": "a",
                        "source_control": "1",
                        "target_framework": "b",
                        "target_control": "2",
                        "relationship": "sort-of",
                    }
                ]
            }
        )
        assert any("relationship" in e for e in errors)
