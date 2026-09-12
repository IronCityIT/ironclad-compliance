"""Map evidence onto controls and set the first verdict on each.

Re-houses the matching logic from the original scripts/assess_controls.py. What
carried over: keyword matching against the control's expected evidence types, a
three-way outcome, and the deliberate refusal to call a control satisfied on the
strength of one document. What changed:

  * the original scored a match by counting keyword hits against a fixed
    threshold of two, so a control with three expected evidence types and a
    control with twelve were held to the same bar. Scoring is now relative to
    how many terms the control actually offers.
  * the original could only ever produce "potential" statuses because it had no
    concept of points of focus. Coverage of the points of focus now separates a
    compliant verdict from a partial one.
  * operator-asserted links from the ingestion manifest are honoured, and are
    recorded as asserted rather than derived.
"""

from __future__ import annotations

import re

from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult
from ironclad.model.assessment import ControlStatus, blank_control_assessment
from ironclad.model.evidence import EvidenceArtifact, EvidenceLink, LinkMethod

# An artifact must hit this share of a control's terms before it counts as
# relevant. Relative rather than absolute so a richly-described control is not
# easier to satisfy than a sparse one.
RELEVANCE_THRESHOLD = 0.18

# Two independent supporting artifacts before a control can read as compliant.
# A single document is a claim; two is corroboration, and it is the bar an
# auditor applies.
CORROBORATION_MIN = 2


_WORD = re.compile(r"[a-z0-9]+")

# Suffixes stripped so a control term matches its inflected forms. Applied to
# both sides, so exact linguistic accuracy matters less than consistency.
_SUFFIXES = ("ies", "ing", "ed", "es", "s")


def _stem(word: str) -> str:
    """Light inflection stripping: registers -> register, monitoring -> monitor."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 3:
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    return {_stem(word) for word in _WORD.findall(text.lower())}


def _relevance(control_terms: set[str], text: str) -> tuple[float, list[str]]:
    """Share of the control's terms present in the text, and which ones.

    Matching is on whole words, not substrings. Substring matching made an
    unrelated control look evidenced whenever one of its terms happened to sit
    inside a longer word elsewhere in the document -- "act" inside "contract",
    "audit" inside "auditorium" -- which quietly turned a gap into a pass.
    """
    if not control_terms:
        return 0.0, []
    stems = {_stem(term) for term in control_terms}
    present = _words(text)
    matched = sorted(stems & present)
    return len(matched) / len(stems), matched


class ControlMapping(AssessmentModule):
    name = "control_mapping"
    description = "Match submitted evidence to each framework control and set an initial verdict."
    groups = ("quick", "standard", "deep")
    requires = ("evidence_inventory",)

    def run(self, ctx: AssessmentContext) -> ModuleResult:
        findings: list[Finding] = []
        ctx.assessment.controls = []

        for control in ctx.framework.controls:
            verdict = blank_control_assessment(control)
            terms = control.keywords()

            for artifact in ctx.evidence:
                link = self._link_for(control.id, artifact, terms)
                if link is not None:
                    verdict.evidence_links.append(link)

            fresh_links = [
                link
                for link in verdict.evidence_links
                if not self._artifact_stale(ctx, link.artifact_id)
            ]

            verdict.points_covered = self._points_covered(control, verdict, ctx)
            verdict.confidence = self._confidence(verdict)
            verdict.status, verdict.rationale = self._verdict(
                len(fresh_links), len(verdict.evidence_links), verdict.coverage
            )

            ctx.assessment.controls.append(verdict)

            if verdict.status in (ControlStatus.GAP, ControlStatus.PARTIAL):
                findings.append(
                    Finding(
                        module=self.name,
                        target=control.id,
                        severity="high" if verdict.status is ControlStatus.GAP else "medium",
                        title=f"{control.id} {verdict.status}: {control.name}",
                        detail=verdict.rationale,
                        evidence={
                            "control_id": control.id,
                            "status": str(verdict.status),
                            "evidence_count": len(verdict.evidence_links),
                            "expected_evidence": list(control.common_evidence),
                            "coverage": round(verdict.coverage, 3),
                        },
                    )
                )

        ctx.module_output[self.name] = {
            "controls_assessed": len(ctx.assessment.controls),
            "links_created": sum(len(c.evidence_links) for c in ctx.assessment.controls),
        }
        return self.result(findings, controls_assessed=len(ctx.assessment.controls))

    def _link_for(
        self, control_id: str, artifact: EvidenceArtifact, terms: set[str]
    ) -> EvidenceLink | None:
        """An asserted link if the operator declared one, else a derived match."""
        if control_id in artifact.control_hints:
            return EvidenceLink(
                control_id=control_id,
                artifact_id=artifact.artifact_id,
                method=LinkMethod.MANUAL,
                relevance=1.0,
                linked_by="operator",
                note="asserted in the evidence manifest",
            )

        if not artifact.text:
            return None

        score, matched = _relevance(terms, artifact.text)
        if score < RELEVANCE_THRESHOLD:
            return None

        return EvidenceLink(
            control_id=control_id,
            artifact_id=artifact.artifact_id,
            method=LinkMethod.AUTOMATED,
            relevance=score,
            matched_terms=tuple(matched[:12]),
        )

    @staticmethod
    def _artifact_stale(ctx: AssessmentContext, artifact_id: str) -> bool:
        artifact = ctx.evidence.get(artifact_id)
        return artifact.is_stale(ctx.as_of) if artifact else True

    @staticmethod
    def _points_covered(control, verdict, ctx: AssessmentContext) -> int:  # type: ignore[no-untyped-def]
        """How many points of focus have an artifact that mentions them.

        A point of focus is covered when some linked artifact contains a
        distinctive word from its description. Crude, and deliberately so: this
        is a readiness signal for a human reviewer, not an audit opinion.
        """
        if not control.points_of_focus:
            # A control with no enumerated points is covered as a whole or not at
            # all; treat one linked artifact as full coverage of its single point.
            return 1 if verdict.evidence_links else 0

        texts: list[str] = []
        for link in verdict.evidence_links:
            artifact = ctx.evidence.get(link.artifact_id)
            if artifact is not None:
                texts.append(artifact.text.lower())
        manual = any(link.method is LinkMethod.MANUAL for link in verdict.evidence_links)
        if manual and not any(texts):
            # An operator asserted the link for evidence the engine cannot read.
            # Take the assertion at face value rather than scoring it at zero.
            return len(control.points_of_focus)

        covered = 0
        for point in control.points_of_focus:
            words = [
                word.strip(".,()").lower()
                for word in point.description.split()
                if len(word.strip(".,()")) > 4
            ]
            if words and any(any(word in text for word in words) for text in texts):
                covered += 1
        return covered

    @staticmethod
    def _confidence(verdict) -> float:  # type: ignore[no-untyped-def]
        """How strongly the linked evidence supports the verdict, 0.0-1.0."""
        if not verdict.evidence_links:
            return 0.0
        strongest = max(link.relevance for link in verdict.evidence_links)
        corroboration = min(len(verdict.evidence_links) / CORROBORATION_MIN, 1.0)
        return round(min(1.0, 0.5 * strongest + 0.5 * corroboration), 3)

    @staticmethod
    def _verdict(fresh: int, total: int, coverage: float) -> tuple[ControlStatus, str]:
        if total == 0:
            return (
                ControlStatus.GAP,
                "No submitted evidence matches this control. Supply the expected evidence "
                "types, or record a risk acceptance if the control is not being met.",
            )
        if fresh == 0:
            return (
                ControlStatus.PARTIAL,
                f"{total} matching item(s) were found, but all of them are outside their "
                "currency window. Refresh the evidence to support this control at audit.",
            )
        if fresh >= CORROBORATION_MIN and coverage >= 0.75:
            return (
                ControlStatus.COMPLIANT,
                f"{fresh} current item(s) support this control and cover "
                f"{int(coverage * 100)}% of its points of focus.",
            )
        if fresh >= CORROBORATION_MIN:
            return (
                ControlStatus.PARTIAL,
                f"{fresh} current item(s) support this control, but only "
                f"{int(coverage * 100)}% of its points of focus are evidenced. Supply evidence "
                "for the remaining points.",
            )
        return (
            ControlStatus.PARTIAL,
            "A single current item supports this control. One document is a claim rather than "
            "corroboration; supply a second, independent item.",
        )
