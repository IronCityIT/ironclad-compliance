"""The audit trail.

Append-only and hash-chained. Each event carries the digest of the one before it,
so removing or editing an event breaks every digest after it and `verify()` says
where. That is what makes the log evidence rather than a list of strings — an
auditor can be shown that the record was not edited after the fact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ironclad.errors import AuditChainError
from ironclad.ids import iso, utc_now

GENESIS_HASH = "0" * 64


@dataclass
class AuditEvent:
    """One recorded action."""

    event_id: str
    tenant_id: str
    actor: str
    action: str  # e.g. "assessment.completed", "exception.approved"
    object_type: str
    object_id: str
    at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = GENESIS_HASH
    hash: str = ""

    def payload(self) -> dict[str, Any]:
        """The bytes that are hashed. Sorted so the digest is reproducible."""
        return {
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "actor": self.actor,
            "action": self.action,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "at": iso(self.at),
            "metadata": self.metadata,
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        encoded = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "hash": self.hash}


@dataclass
class AuditLog:
    """An append-only, hash-chained event log for one tenant."""

    tenant_id: str
    events: list[AuditEvent] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.events)

    @property
    def head(self) -> str:
        return self.events[-1].hash if self.events else GENESIS_HASH

    def record(
        self,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        metadata: dict[str, Any] | None = None,
        at: datetime | None = None,
    ) -> AuditEvent:
        """Append one event, chaining it to the current head."""
        at = at or utc_now()
        event = AuditEvent(
            event_id=f"{len(self.events):06d}",
            tenant_id=self.tenant_id,
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            at=at,
            metadata=metadata or {},
            prev_hash=self.head,
        )
        event.hash = event.compute_hash()
        self.events.append(event)
        return event

    def verify(self) -> None:
        """Raise AuditChainError naming the first event that does not verify."""
        expected_prev = GENESIS_HASH
        for index, event in enumerate(self.events):
            if event.prev_hash != expected_prev:
                raise AuditChainError(
                    f"audit chain broken at event {index} ({event.event_id}): "
                    f"prev_hash {event.prev_hash[:12]}… does not follow {expected_prev[:12]}…"
                )
            if event.hash != event.compute_hash():
                raise AuditChainError(
                    f"audit event {index} ({event.event_id}) has been altered: "
                    f"stored digest does not match its contents"
                )
            expected_prev = event.hash

    def is_valid(self) -> bool:
        try:
            self.verify()
        except AuditChainError:
            return False
        return True

    def for_object(self, object_type: str, object_id: str) -> list[AuditEvent]:
        return [e for e in self.events if e.object_type == object_type and e.object_id == object_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "event_count": len(self.events),
            "head": self.head,
            "verified": self.is_valid(),
            "events": [e.to_dict() for e in self.events],
        }
