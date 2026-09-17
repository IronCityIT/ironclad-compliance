"""The persistence port.

One protocol, so the engine's vocabulary does not depend on where a result
lands. Every implementation must hold the four properties the product is built
on, and each is asserted in `tests/test_store.py` against every implementation
rather than trusted per backend:

  tenant-scoped    every row carries a tenant id, and no read crosses one
  idempotent       storing the same assessment twice leaves one record,
                   because a re-run of a pipeline is normal and must not
                   accumulate duplicates
  append-only      audit events are added, never rewritten; the chain is
                   verified on read rather than assumed
  fail-closed      a store that cannot authenticate or cannot reach its
                   backing service refuses, and never reports a write it did
                   not make
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ironclad.errors import IroncladError
from ironclad.model.audit import GENESIS_HASH


class StoreError(IroncladError):
    """A store could not do what was asked. Raised, never swallowed."""


@runtime_checkable
class ResultStore(Protocol):
    """Where a finished assessment is written and read back."""

    def put_assessment(self, document: dict[str, Any]) -> str:
        """Store one complete result document. Returns the assessment id.

        Idempotent on `assessment_id`: storing the same assessment again
        replaces it rather than creating a second record.
        """
        ...

    def get_assessment(self, tenant_id: str, assessment_id: str) -> dict[str, Any] | None:
        """One assessment's summary record, or None. Never crosses a tenant."""
        ...

    def list_assessments(self, tenant_id: str, limit: int = 25) -> list[dict[str, Any]]:
        """Assessment summaries for one tenant, most recent first."""
        ...

    def list_remediation(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Outstanding remediation for one tenant, worst first."""
        ...

    def list_audit(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """The audit trail for one tenant, oldest first, as stored."""
        ...

    def health(self) -> dict[str, Any]:
        """Whether this store can be written to, and what it is.

        Called before a pipeline commits to publishing, so a misconfigured sink
        is a clear failure at the start rather than a lost result at the end.
        """
        ...


def verify_stored_chains(events: list[dict[str, Any]], tenant_id: str = "") -> dict[str, Any]:
    """Re-verify a tenant's stored audit events, one chain per assessment.

    Every assessment's trail starts at the genesis hash and links forward; a
    tenant's store holds every assessment's trail, one after another. The
    first version of this check read the whole tenant as one chain, so it
    verified a tenant with one assessment and reported the second
    assessment's first event as a break — found the first time the Jenkins
    pipeline's end-to-end gate ran twice into the same workspace volume
    (PRODUCTIZE_NOTES §16.27). A restore check that cries tamper on every
    tenant with two assessments is worse than no check.

    The digests are stored verbatim and are not recomputed here: the rows are
    a projection, not the events. What is checked is the shape of each chain
    — starts at genesis, each event follows the last — which is what an edit
    to a stored row breaks.
    """
    chains: dict[str, str] = {}  # assessment_id -> hash of its latest event seen
    for event in events:
        assessment_id = str(event.get("assessment_id") or "")
        expected = chains.get(assessment_id, GENESIS_HASH)
        if str(event.get("prev_hash") or "") != expected:
            return {
                "tenant_id": tenant_id,
                "events": len(events),
                "chains": len(chains),
                "verified": False,
                "broken_at": event.get("event_id"),
                "assessment_id": assessment_id,
                "detail": (
                    "prev_hash does not follow the previous event of this assessment"
                    if assessment_id in chains
                    else "the first event of this assessment does not start at genesis"
                ),
            }
        chains[assessment_id] = str(event.get("hash") or "")
    return {
        "tenant_id": tenant_id,
        "events": len(events),
        "chains": len(chains),
        "verified": True,
        "broken_at": None,
        "assessment_id": None,
        "detail": "",
    }
