"""Risk acceptance: the formal exception workflow.

An exception is how an organisation says "we know this control is not met, here
is why, here is what we do instead, and here is who signed for it, until when."
Three rules make it worth anything to an auditor, and all three are enforced
here rather than left to the UI:

  1. An exception must be approved by someone other than the requester.
  2. An exception must expire. An open-ended acceptance is just an unfixed gap.
  3. An expired exception stops suppressing the gap the moment it lapses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from ironclad.errors import ExceptionWorkflowError
from ironclad.ids import content_hash, iso, utc_now

# The longest an acceptance may run before it must be re-argued. An auditor will
# not accept a multi-year standing exception, and neither will the engine.
MAX_EXCEPTION_DAYS = 365
DEFAULT_EXCEPTION_DAYS = 90


class ExceptionStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"

    def __str__(self) -> str:
        return self.value


# Which transitions the workflow permits. Anything not listed is rejected.
ALLOWED_TRANSITIONS: dict[ExceptionStatus, frozenset[ExceptionStatus]] = {
    ExceptionStatus.DRAFT: frozenset({ExceptionStatus.PENDING_APPROVAL, ExceptionStatus.REVOKED}),
    ExceptionStatus.PENDING_APPROVAL: frozenset(
        {ExceptionStatus.APPROVED, ExceptionStatus.REJECTED, ExceptionStatus.REVOKED}
    ),
    ExceptionStatus.APPROVED: frozenset({ExceptionStatus.EXPIRED, ExceptionStatus.REVOKED}),
    ExceptionStatus.REJECTED: frozenset({ExceptionStatus.DRAFT}),
    ExceptionStatus.EXPIRED: frozenset({ExceptionStatus.DRAFT}),
    ExceptionStatus.REVOKED: frozenset(),
}


@dataclass
class RiskException:
    """A documented, time-boxed acceptance of one unmet control."""

    exception_id: str
    tenant_id: str
    control_id: str
    justification: str
    requested_by: str
    status: ExceptionStatus = ExceptionStatus.DRAFT
    compensating_controls: list[str] = field(default_factory=list)
    approved_by: str = ""
    approved_at: datetime | None = None
    requested_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    review_notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.justification.strip():
            raise ExceptionWorkflowError("a risk acceptance requires a written justification")
        if self.expires_at is None:
            self.expires_at = self.requested_at + timedelta(days=DEFAULT_EXCEPTION_DAYS)
        horizon = self.requested_at + timedelta(days=MAX_EXCEPTION_DAYS)
        if self.expires_at > horizon:
            raise ExceptionWorkflowError(
                f"a risk acceptance may not run beyond {MAX_EXCEPTION_DAYS} days; "
                f"re-argue it at renewal"
            )
        if self.expires_at <= self.requested_at:
            raise ExceptionWorkflowError("expiry must be after the request date")

    def _transition(self, target: ExceptionStatus) -> None:
        if target not in ALLOWED_TRANSITIONS[self.status]:
            raise ExceptionWorkflowError(
                f"cannot move exception {self.exception_id} from {self.status} to {target}"
            )
        self.status = target

    def submit(self) -> None:
        """Move a draft into the approval queue."""
        self._transition(ExceptionStatus.PENDING_APPROVAL)

    def approve(self, approver: str, at: datetime | None = None) -> None:
        """Approve the acceptance. The approver may not be the requester."""
        approver = approver.strip()
        if not approver:
            raise ExceptionWorkflowError("an approver is required")
        if approver == self.requested_by:
            raise ExceptionWorkflowError(
                f"{approver} requested this exception and may not approve it; "
                f"risk acceptance needs a second person"
            )
        self._transition(ExceptionStatus.APPROVED)
        self.approved_by = approver
        self.approved_at = at or utc_now()

    def reject(self, approver: str, reason: str) -> None:
        self._transition(ExceptionStatus.REJECTED)
        self.approved_by = approver
        self.review_notes.append(reason)

    def revoke(self, actor: str, reason: str) -> None:
        self._transition(ExceptionStatus.REVOKED)
        self.review_notes.append(f"revoked by {actor}: {reason}")

    def expire(self) -> None:
        self._transition(ExceptionStatus.EXPIRED)

    def is_active(self, as_of: datetime | None = None) -> bool:
        """True only while an approved, unexpired acceptance is in force.

        This is the single question the assessment engine asks. Everything else
        about the workflow is bookkeeping around it.
        """
        if self.status is not ExceptionStatus.APPROVED:
            return False
        return (as_of or utc_now()) <= (self.expires_at or utc_now())

    def days_remaining(self, as_of: datetime | None = None) -> int:
        if self.expires_at is None:
            return 0
        return (self.expires_at - (as_of or utc_now())).days

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_id": self.exception_id,
            "tenant_id": self.tenant_id,
            "control_id": self.control_id,
            "justification": self.justification,
            "compensating_controls": list(self.compensating_controls),
            "status": str(self.status),
            "requested_by": self.requested_by,
            "requested_at": iso(self.requested_at),
            "approved_by": self.approved_by,
            "approved_at": iso(self.approved_at) if self.approved_at else None,
            "expires_at": iso(self.expires_at) if self.expires_at else None,
            "active": self.is_active(),
            "days_remaining": self.days_remaining(),
            "review_notes": list(self.review_notes),
        }


def new_exception_id(tenant_id: str, control_id: str, requested_at: datetime) -> str:
    return "ex-" + content_hash(tenant_id, control_id, iso(requested_at))


def sweep_expired(
    exceptions: list[RiskException], as_of: datetime | None = None
) -> list[RiskException]:
    """Move every lapsed approval to EXPIRED and return the ones that moved.

    Run before an assessment. Without it a lapsed acceptance would keep
    suppressing a real gap, which is the exact failure an auditor looks for.
    """
    now = as_of or utc_now()
    lapsed: list[RiskException] = []
    for item in exceptions:
        if item.status is ExceptionStatus.APPROVED and item.expires_at and item.expires_at < now:
            item.expire()
            lapsed.append(item)
    return lapsed
