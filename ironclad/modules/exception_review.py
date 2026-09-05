"""Apply risk acceptances to the control verdicts.

Runs after control mapping so it sees the real verdicts, and does three things
in a fixed order:

  1. Expires every acceptance whose window has closed. A lapsed acceptance must
     stop suppressing its gap the moment it lapses, not at the next review.
  2. Converts a gap or partial into `accepted_risk` where an approved, unexpired
     acceptance covers it.
  3. Reports acceptances that are close to expiry, so a programme is not
     surprised by a gap reopening the week before an audit.

Every state change is written to the audit log. Who accepted which risk and when
is precisely what an auditor asks for.
"""

from __future__ import annotations

from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult
from ironclad.model.assessment import ControlStatus
from ironclad.model.exception import ExceptionStatus, sweep_expired

# Warn this far ahead of an acceptance lapsing.
EXPIRY_WARNING_DAYS = 30


class ExceptionReview(AssessmentModule):
    name = "exception_review"
    description = "Apply approved risk acceptances and reopen any that have lapsed."
    groups = ("standard", "deep")
    requires = ("control_mapping",)

    def run(self, ctx: AssessmentContext) -> ModuleResult:
        findings: list[Finding] = []

        lapsed = sweep_expired(ctx.exceptions, ctx.as_of)
        for item in lapsed:
            ctx.audit.record(
                actor=ctx.actor,
                action="exception.expired",
                object_type="risk_exception",
                object_id=item.exception_id,
                metadata={"control_id": item.control_id, "expired_at": item.expires_at.isoformat() if item.expires_at else None},
                at=ctx.as_of,
            )
            findings.append(
                Finding(
                    module=self.name,
                    target=item.control_id,
                    severity="high",
                    title=f"Risk acceptance has lapsed for {item.control_id}",
                    detail=(
                        "The accepted risk covering this control expired and is no longer in "
                        "force. The control is assessed on its evidence again. Renew the "
                        "acceptance with fresh approval, or remediate the control."
                    ),
                    evidence={
                        "exception_id": item.exception_id,
                        "control_id": item.control_id,
                        "approved_by": item.approved_by,
                    },
                )
            )

        applied = 0
        for item in ctx.exceptions:
            verdict = ctx.assessment.get(item.control_id)
            if verdict is None:
                ctx.warn(
                    f"risk acceptance {item.exception_id} names control {item.control_id}, "
                    f"which is not in {ctx.framework.key}"
                )
                continue

            if not item.is_active(ctx.as_of):
                continue

            if verdict.status in (ControlStatus.GAP, ControlStatus.PARTIAL):
                verdict.status = ControlStatus.ACCEPTED_RISK
                verdict.exception_id = item.exception_id
                verdict.add_note(
                    f"Risk formally accepted by {item.approved_by} until "
                    f"{item.expires_at.date().isoformat() if item.expires_at else 'unspecified'}."
                )
                verdict.rationale = (
                    f"The control is not met. The risk was accepted by {item.approved_by} on "
                    f"{item.approved_at.date().isoformat() if item.approved_at else 'an unrecorded date'}"
                    + (
                        f", with compensating measures: {', '.join(item.compensating_controls)}."
                        if item.compensating_controls
                        else ", with no compensating measures recorded."
                    )
                )
                applied += 1
                ctx.audit.record(
                    actor=ctx.actor,
                    action="exception.applied",
                    object_type="control",
                    object_id=item.control_id,
                    metadata={"exception_id": item.exception_id},
                    at=ctx.as_of,
                )

            remaining = item.days_remaining(ctx.as_of)
            if 0 <= remaining <= EXPIRY_WARNING_DAYS:
                findings.append(
                    Finding(
                        module=self.name,
                        target=item.control_id,
                        severity="medium",
                        title=f"Risk acceptance expires in {remaining} day(s): {item.control_id}",
                        detail=(
                            "When it expires this control reverts to an open gap. Renew the "
                            "acceptance or close the underlying gap before then."
                        ),
                        evidence={
                            "exception_id": item.exception_id,
                            "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                            "days_remaining": remaining,
                        },
                    )
                )

            if not item.compensating_controls:
                findings.append(
                    Finding(
                        module=self.name,
                        target=item.control_id,
                        severity="low",
                        title=f"Risk acceptance records no compensating measures: {item.control_id}",
                        detail=(
                            "An acceptance with nothing recorded in mitigation is difficult to "
                            "defend at audit. Record what reduces the risk in the meantime."
                        ),
                        evidence={"exception_id": item.exception_id},
                    )
                )

        pending = [e for e in ctx.exceptions if e.status is ExceptionStatus.PENDING_APPROVAL]
        for item in pending:
            findings.append(
                Finding(
                    module=self.name,
                    target=item.control_id,
                    severity="low",
                    title=f"Risk acceptance is awaiting approval: {item.control_id}",
                    detail=(
                        "The request is not in force and the control is assessed on its "
                        "evidence until it is approved."
                    ),
                    evidence={"exception_id": item.exception_id, "requested_by": item.requested_by},
                )
            )

        ctx.module_output[self.name] = {
            "exceptions_total": len(ctx.exceptions),
            "applied": applied,
            "lapsed": len(lapsed),
            "pending_approval": len(pending),
            "exceptions": [e.to_dict() for e in ctx.exceptions],
        }
        return self.result(findings, applied=applied, lapsed=len(lapsed), pending=len(pending))
