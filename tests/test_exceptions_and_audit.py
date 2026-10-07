"""Risk acceptance workflow and the audit chain.

These are the two places where the product makes a claim an auditor will test:
that an acceptance was signed by a second person and expires, and that the
record of what happened has not been edited since.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ironclad.errors import AuditChainError, ExceptionWorkflowError
from ironclad.model.audit import AuditLog
from ironclad.model.exception import (
    MAX_EXCEPTION_DAYS,
    ExceptionStatus,
    RiskException,
    sweep_expired,
)
from tests.conftest import NOW


def make_exception(
    exception_id: str = "ex-1",
    justification: str = "Remediation is scheduled for the next release train.",
    requested_by: str = "alice",
    expires_at: datetime | None = NOW + timedelta(days=90),
) -> RiskException:
    return RiskException(
        exception_id=exception_id,
        tenant_id="acme",
        control_id="CC6.1",
        justification=justification,
        requested_by=requested_by,
        requested_at=NOW,
        expires_at=expires_at,
    )


class TestExceptionWorkflow:
    def test_an_acceptance_needs_a_written_justification(self) -> None:
        with pytest.raises(ExceptionWorkflowError, match="written justification"):
            make_exception(justification="   ")

    def test_an_acceptance_may_not_outrun_the_maximum(self) -> None:
        with pytest.raises(ExceptionWorkflowError, match="re-argue it at renewal"):
            make_exception(expires_at=NOW + timedelta(days=MAX_EXCEPTION_DAYS + 1))

    def test_expiry_must_be_in_the_future(self) -> None:
        with pytest.raises(ExceptionWorkflowError, match="after the request date"):
            make_exception(expires_at=NOW - timedelta(days=1))

    def test_an_undated_acceptance_gets_a_default_expiry(self) -> None:
        # An open-ended acceptance is just an unfixed gap with paperwork.
        exception = make_exception(expires_at=None)
        assert exception.expires_at is not None
        assert exception.expires_at > NOW

    def test_the_requester_cannot_approve_their_own_acceptance(self) -> None:
        exception = make_exception()
        exception.submit()
        with pytest.raises(ExceptionWorkflowError, match="needs a second person"):
            exception.approve("alice")
        assert exception.status is ExceptionStatus.PENDING_APPROVAL

    def test_a_second_person_can_approve(self) -> None:
        exception = make_exception()
        exception.submit()
        exception.approve("bob", at=NOW)
        assert exception.status is ExceptionStatus.APPROVED
        assert exception.approved_by == "bob"
        assert exception.is_active(NOW)

    def test_an_approval_requires_an_approver(self) -> None:
        exception = make_exception()
        exception.submit()
        with pytest.raises(ExceptionWorkflowError, match="approver is required"):
            exception.approve("  ")

    def test_a_draft_cannot_be_approved_directly(self) -> None:
        exception = make_exception()
        with pytest.raises(ExceptionWorkflowError, match="cannot move exception"):
            exception.approve("bob")

    def test_a_revoked_acceptance_is_terminal(self) -> None:
        exception = make_exception()
        exception.submit()
        exception.approve("bob", at=NOW)
        exception.revoke("carol", "the control was remediated")
        with pytest.raises(ExceptionWorkflowError):
            exception.submit()

    def test_an_expired_acceptance_stops_being_active(self) -> None:
        exception = make_exception()
        exception.submit()
        exception.approve("bob", at=NOW)
        assert exception.is_active(NOW + timedelta(days=89))
        assert not exception.is_active(NOW + timedelta(days=91))

    def test_only_an_approved_acceptance_is_ever_active(self) -> None:
        exception = make_exception()
        assert not exception.is_active(NOW)
        exception.submit()
        assert not exception.is_active(NOW)

    def test_the_sweep_expires_lapsed_acceptances_and_reports_them(self) -> None:
        live = make_exception(exception_id="ex-live")
        lapsed = make_exception(exception_id="ex-lapsed", expires_at=NOW + timedelta(days=10))
        for item in (live, lapsed):
            item.submit()
            item.approve("bob", at=NOW)

        moved = sweep_expired([live, lapsed], NOW + timedelta(days=30))
        assert [e.exception_id for e in moved] == ["ex-lapsed"]
        assert lapsed.status is ExceptionStatus.EXPIRED
        assert live.status is ExceptionStatus.APPROVED


class TestAuditChain:
    def _log(self) -> AuditLog:
        log = AuditLog(tenant_id="acme")
        log.record("alice", "assessment.started", "assessment", "a-1", at=NOW)
        log.record("bob", "exception.approved", "risk_exception", "ex-1", at=NOW)
        log.record("system", "assessment.completed", "assessment", "a-1", at=NOW)
        return log

    def test_a_clean_chain_verifies(self) -> None:
        log = self._log()
        log.verify()
        assert log.is_valid()
        assert len(log) == 3

    def test_editing_an_event_breaks_the_chain(self) -> None:
        log = self._log()
        log.events[1].actor = "mallory"
        with pytest.raises(AuditChainError, match="has been altered"):
            log.verify()
        assert not log.is_valid()

    def test_removing_an_event_breaks_the_chain(self) -> None:
        log = self._log()
        del log.events[1]
        with pytest.raises(AuditChainError, match="audit chain broken"):
            log.verify()

    def test_reordering_events_breaks_the_chain(self) -> None:
        log = self._log()
        log.events[1], log.events[2] = log.events[2], log.events[1]
        with pytest.raises(AuditChainError):
            log.verify()

    def test_the_error_names_where_the_chain_broke(self) -> None:
        log = self._log()
        log.events[2].metadata["injected"] = True
        with pytest.raises(AuditChainError) as caught:
            log.verify()
        assert "event 2" in str(caught.value)

    def test_the_head_advances_with_each_event(self) -> None:
        log = AuditLog(tenant_id="acme")
        first_head = log.head
        log.record("alice", "a", "t", "1", at=NOW)
        assert log.head != first_head

    def test_events_can_be_filtered_by_object(self) -> None:
        log = self._log()
        assert len(log.for_object("assessment", "a-1")) == 2
        assert len(log.for_object("risk_exception", "ex-1")) == 1
