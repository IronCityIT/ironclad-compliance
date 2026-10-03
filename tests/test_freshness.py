"""Evidence that is still valid and will not be for long.

`control_mapping` already refuses to count expired evidence. This capability
looks at the evidence still inside its window but near the edge, and at controls
whose whole case rests on a single document. Both are the shape of a programme
that will fail its next audit without anything visibly changing — which is
exactly the thing a client wants to hear before it happens rather than after.

It had no behaviour tests at all. It appeared in the suite only as a target for
failure injection, so the ageing detection itself — the arithmetic, the note it
puts on a control, the finding it raises — had never run.

The rule that matters most: **ageing evidence is flagged, never downgraded.**
Evidence inside its window supports the control. Moving the verdict because a
document is getting old would be the engine deciding a client is out of
compliance on a date, which is not what the standard says and not what the
evidence says.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from ironclad.base import AssessmentContext
from ironclad.model.assessment import Assessment, ControlAssessment, ControlStatus
from ironclad.model.audit import AuditLog
from ironclad.model.control import Control, Framework
from ironclad.model.evidence import EvidenceLink, EvidenceSet, LinkMethod
from ironclad.modules.freshness_check import AGEING_THRESHOLD, FreshnessCheck
from tests.conftest import NOW, make_artifact

FRAMEWORK = Framework(
    id="test-fw",
    name="Test Framework",
    version="1.0",
    source="tests",
    controls=(Control(id="CC6.1", name="Logical Access", description="Access is restricted."),),
)


def artifact_aged(fraction: float, name: str = "Access Review", window_days: int = 100):
    """An artifact `fraction` of the way through a window of known length."""
    collected = NOW - timedelta(days=int(window_days * fraction))
    return make_artifact(
        name,
        "Access review. Restricts logical access.",
        evidence_type="access review",
        collected_at=collected,
        valid_until=collected + timedelta(days=window_days),
    )


def context(
    artifacts: list, status: ControlStatus = ControlStatus.COMPLIANT, links: int | None = None
) -> AssessmentContext:
    evidence = EvidenceSet(tenant_id="acme")
    for artifact in artifacts:
        evidence.add(artifact)

    verdict = ControlAssessment(control_id="CC6.1", control_name="Logical Access", status=status)
    for artifact in artifacts[: links if links is not None else len(artifacts)]:
        verdict.evidence_links.append(
            EvidenceLink(
                control_id="CC6.1",
                artifact_id=artifact.artifact_id,
                method=LinkMethod.AUTOMATED,
                relevance=0.5,
            )
        )

    assessment = Assessment(assessment_id="acme-freshness-1", tenant_id="acme", framework=FRAMEWORK)
    assessment.controls.append(verdict)

    return AssessmentContext(
        tenant_id="acme",
        framework=FRAMEWORK,
        evidence=evidence,
        assessment=assessment,
        audit=AuditLog(tenant_id="acme"),
        as_of=NOW,
    )


def run(ctx: AssessmentContext):
    return FreshnessCheck().run(ctx)


class TestWhatCountsAsAgeing:
    def test_fresh_evidence_raises_nothing(self) -> None:
        ctx = context([artifact_aged(0.1)])
        result = run(ctx)
        assert result.findings == []
        assert ctx.module_output["freshness_check"]["ageing_controls"] == 0

    def test_evidence_near_the_end_of_its_window_is_flagged(self) -> None:
        ctx = context([artifact_aged(0.95)])
        result = run(ctx)
        assert len(result.findings) == 1
        assert ctx.module_output["freshness_check"]["ageing_controls"] == 1

    def test_the_threshold_is_inclusive(self) -> None:
        # At exactly the threshold the evidence is ageing. A boundary that
        # excluded it would mean the last day of the window is the first anyone
        # hears about it.
        ctx = context([artifact_aged(AGEING_THRESHOLD)])
        assert len(run(ctx).findings) == 1

    def test_just_inside_the_threshold_is_not_flagged(self) -> None:
        ctx = context([artifact_aged(AGEING_THRESHOLD - 0.1)])
        assert run(ctx).findings == []

    def test_already_expired_evidence_is_not_reported_as_ageing(self) -> None:
        # It is not ageing, it is gone, and control_mapping has already refused
        # to count it. Reporting it here would tell a client to refresh evidence
        # that is not supporting anything.
        ctx = context([artifact_aged(1.5)])
        assert run(ctx).findings == []
        assert ctx.module_output["freshness_check"]["ageing_controls"] == 0


class TestWhatItLeavesAlone:
    def test_ageing_evidence_does_not_move_the_verdict(self) -> None:
        # The rule this file exists for. Evidence inside its window supports the
        # control; downgrading on a date would be the engine deciding a client
        # is non-compliant for a reason the standard does not give.
        ctx = context([artifact_aged(0.99)])
        run(ctx)
        assert ctx.assessment.controls[0].status is ControlStatus.COMPLIANT

    @pytest.mark.parametrize(
        "status",
        [
            ControlStatus.GAP,
            ControlStatus.PENDING,
            ControlStatus.NOT_APPLICABLE,
            ControlStatus.ACCEPTED_RISK,
        ],
    )
    def test_a_control_that_is_not_met_is_not_examined(self, status: ControlStatus) -> None:
        # There is nothing to warn about: no case rests on this evidence.
        ctx = context([artifact_aged(0.99)], status=status)
        assert run(ctx).findings == []

    def test_a_partial_control_is_examined(
        self,
    ) -> None:
        # A partial control is partly evidenced, and that evidence ageing out
        # makes it worse rather than leaving it where it is.
        ctx = context([artifact_aged(0.99)], status=ControlStatus.PARTIAL)
        assert len(run(ctx).findings) == 1


class TestItSaysWhichEvidence:
    def test_the_finding_names_the_ageing_documents(self) -> None:
        ctx = context([artifact_aged(0.95, name="Access Review Q1")])
        finding = run(ctx).findings[0]
        assert finding.evidence["ageing_evidence"] == ["Access Review Q1"]
        assert finding.target == "CC6.1"
        assert finding.severity == "low"

    def test_the_control_carries_a_note_a_reader_will_see(self) -> None:
        # The finding goes to the AI stage; the note is what reaches the report.
        ctx = context([artifact_aged(0.95, name="Access Review Q1")])
        run(ctx)
        notes = " ".join(ctx.assessment.controls[0].notes)
        assert "Access Review Q1" in notes
        assert "currency window" in notes

    def test_only_the_ageing_items_are_named(self) -> None:
        ctx = context(
            [artifact_aged(0.95, name="Old Review"), artifact_aged(0.1, name="New Policy")]
        )
        finding = run(ctx).findings[0]
        assert finding.evidence["ageing_evidence"] == ["Old Review"]


class TestASingleDocumentIsNotAProgramme:
    def test_a_control_resting_on_one_item_is_reported(self) -> None:
        ctx = context([artifact_aged(0.1)])
        run(ctx)
        assert ctx.module_output["freshness_check"]["single_source_controls"] == ["CC6.1"]

    def test_a_corroborated_control_is_not(self) -> None:
        ctx = context([artifact_aged(0.1, name="One"), artifact_aged(0.2, name="Two")])
        run(ctx)
        assert ctx.module_output["freshness_check"]["single_source_controls"] == []

    def test_only_a_met_control_counts(self) -> None:
        # A partial control resting on one document is not the same warning:
        # it is already reported as partly evidenced.
        ctx = context([artifact_aged(0.1)], status=ControlStatus.PARTIAL)
        run(ctx)
        assert ctx.module_output["freshness_check"]["single_source_controls"] == []


class TestItSurvivesAMalformedEvidenceSet:
    def test_a_link_to_an_artifact_that_is_not_there_is_skipped(self) -> None:
        # A link can outlive its artifact when a manifest is edited between
        # runs. An assessment must not die of it.
        ctx = context([artifact_aged(0.95)])
        ctx.assessment.controls[0].evidence_links.append(
            EvidenceLink(
                control_id="CC6.1",
                artifact_id="ev-does-not-exist",
                method=LinkMethod.AUTOMATED,
                relevance=0.5,
            )
        )
        assert len(run(ctx).findings) == 1

    def test_a_window_that_ends_before_it_starts_is_skipped(self) -> None:
        # A manifest can assert valid_until earlier than collected_at. Dividing
        # by that window is a crash, and guessing at it is worse.
        artifact = make_artifact(
            "Backwards Policy",
            "Access control policy.",
            evidence_type="policy",
            collected_at=NOW,
            valid_until=NOW - timedelta(days=10),
        )
        ctx = context([artifact])
        assert run(ctx).findings == []

    def test_a_zero_length_window_is_skipped(self) -> None:
        artifact = make_artifact(
            "Instant Policy",
            "Access control policy.",
            evidence_type="policy",
            collected_at=NOW,
            valid_until=NOW,
        )
        ctx = context([artifact])
        assert run(ctx).findings == []

    def test_a_control_with_no_evidence_at_all_is_skipped(self) -> None:
        ctx = context([artifact_aged(0.95)], links=0)
        assert run(ctx).findings == []
