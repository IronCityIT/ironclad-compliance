"""What changed between two assessments.

A compliance programme is a trend, not a snapshot. The question a client asks at
the second assessment is not "what is our readiness" but "what moved, and did
the work we did in between show up". Everything needed to answer that has been
stored since the first release — the complete register, every verdict, the whole
remediation plan — and nothing read it back.

Pure: two documents in, a comparison out. No storage, no I/O, so the CLI, the
store and any future surface all get the same answer.

Three honesty rules, because a trend is the easiest thing in this product to
make flattering by accident:

**A control scoped out is not a control fixed.** Moving to `not_applicable`
removes it from the denominator and lifts the score, which looks exactly like
progress. It is reported as a scope change, in its own list, never as an
improvement.

**A framework version change invalidates the comparison** as a like-for-like
trend, because the control set moved underneath it. Said plainly rather than
quietly producing a number.

**Controls present in only one assessment are named**, not dropped. A control
that disappears between two runs is either a scope change or a defect, and
silently omitting it from both lists hides which.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ironclad.model.assessment import ControlStatus

#: Where a status sits when asking "did this get better or worse".
#:
#: Deliberately not STATUS_ORDER, which ranks severity for reporting and puts
#: `not_applicable` at the top — correct there, and here it would read a control
#: scoped out of the assessment as the best possible outcome.
#:
#: An accepted risk ranks with partial: the control is still not met, and the
#: organisation has decided about it, which is materially better than an unknown
#: gap and is not a working control. Same 0.5 the score gives it.
MOVEMENT_RANK: dict[ControlStatus, int] = {
    ControlStatus.GAP: 0,
    ControlStatus.PENDING: 0,
    ControlStatus.PARTIAL: 1,
    ControlStatus.ACCEPTED_RISK: 1,
    ControlStatus.COMPLIANT: 2,
}

IMPROVED = "improved"
REGRESSED = "regressed"
UNCHANGED = "unchanged"
SCOPED_OUT = "scoped_out"
SCOPED_IN = "scoped_in"
# A risk acceptance is a decision about a control, not a change to it. Into
# acceptance from a gap read as "improved" and closed the item as if it had
# been fixed: accepting every gap in the sample read as "11 improved, 27
# remediation items closed" (PRODUCTIZE_NOTES §16.36). Out of acceptance —
# lapsed, revoked — reopens a gap that was never fixed, and is not a
# regression either. Both are reported under their own names. The exception
# is a met control going into acceptance: it stopped working, so it regressed.
RISK_ACCEPTED = "risk_accepted"
ACCEPTANCE_LAPSED = "acceptance_lapsed"


def _rank(status: str) -> int | None:
    """The movement rank of a status, or None if it does not have one."""
    try:
        return MOVEMENT_RANK.get(ControlStatus(status))
    except ValueError:
        return None


@dataclass
class ControlChange:
    """One control, before and after."""

    control_id: str
    control_name: str
    was: str
    now: str
    movement: str
    points_before: int = 0
    points_after: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "control_name": self.control_name,
            "was": self.was,
            "now": self.now,
            "movement": self.movement,
            "points_before": self.points_before,
            "points_after": self.points_after,
        }


@dataclass
class Comparison:
    """Two assessments of one tenant, and what moved between them."""

    tenant_id: str
    framework_id: str
    earlier_id: str
    later_id: str
    earlier_at: str
    later_at: str
    readiness_before: float
    readiness_after: float
    comparable: bool = True
    # Why it is not comparable, in a few words for the headline. The caveat
    # says it in full.
    not_comparable_because: str = ""
    # False when neither run planned remediation: there were no items to open
    # or close, and "0 closed, 0 opened" would be a count of nothing.
    remediation_tracked: bool = True
    caveats: list[str] = field(default_factory=list)
    improved: list[ControlChange] = field(default_factory=list)
    regressed: list[ControlChange] = field(default_factory=list)
    unchanged: list[ControlChange] = field(default_factory=list)
    scoped_out: list[ControlChange] = field(default_factory=list)
    scoped_in: list[ControlChange] = field(default_factory=list)
    risk_accepted: list[ControlChange] = field(default_factory=list)
    acceptance_lapsed: list[ControlChange] = field(default_factory=list)
    only_earlier: list[str] = field(default_factory=list)
    only_later: list[str] = field(default_factory=list)
    remediation_closed: list[dict[str, Any]] = field(default_factory=list)
    remediation_opened: list[dict[str, Any]] = field(default_factory=list)
    remediation_carried: list[dict[str, Any]] = field(default_factory=list)
    # Items that left the plan without the control being fixed: the control
    # was accepted, or scoped out. Not "closed".
    remediation_set_aside: list[dict[str, Any]] = field(default_factory=list)
    # Items whose control is not in the later assessment at all. The item went
    # with the control; nothing says it was fixed. Not "closed" either.
    remediation_control_gone: list[dict[str, Any]] = field(default_factory=list)
    # Items the later run could not have kept, because it did not plan
    # remediation at all. Whether they were fixed is unknown. Not "closed".
    remediation_unplanned: list[dict[str, Any]] = field(default_factory=list)
    # Items in the later plan that the earlier run could not have held, because
    # it did not plan remediation at all. Whether the gap is new is unknown.
    # Not "opened".
    remediation_first_planned: list[dict[str, Any]] = field(default_factory=list)
    # Items whose control is not in the earlier assessment at all. The item
    # came with the control; nothing says the gap is new. Not "opened" either.
    remediation_control_new: list[dict[str, Any]] = field(default_factory=list)
    # Items whose control was accepted as risk, or out of scope, in the earlier
    # assessment. The decision ended and the gap came back into the plan; it
    # was there all along. The mirror of set-aside. Not "opened".
    remediation_resumed: list[dict[str, Any]] = field(default_factory=list)

    @property
    def readiness_change(self) -> float:
        return round(self.readiness_after - self.readiness_before, 1)

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "framework_id": self.framework_id,
            "earlier": {"assessment_id": self.earlier_id, "at": self.earlier_at},
            "later": {"assessment_id": self.later_id, "at": self.later_at},
            "comparable": self.comparable,
            "not_comparable_because": self.not_comparable_because,
            "caveats": list(self.caveats),
            "readiness": {
                "before": self.readiness_before,
                "after": self.readiness_after,
                "change": self.readiness_change if self.comparable else None,
            },
        }
        if not self.comparable:
            # The headline beside this record says no movement is reported, and
            # the record reported it: "change": 25.9 and an improved control for
            # a pair across framework versions. Null rather than empty, because
            # an empty list would claim that nothing moved.
            record["controls"] = None
            record["remediation"] = None
            return record
        record.update(self._movement())
        if not self.remediation_tracked:
            # Two quick runs with a control fixed between them gave empty lists,
            # which claim nothing was closed. Nothing was planned to close.
            record["remediation"] = None
        return record

    def _movement(self) -> dict[str, Any]:
        return {
            "controls": {
                "improved": [c.to_dict() for c in self.improved],
                "regressed": [c.to_dict() for c in self.regressed],
                "unchanged": len(self.unchanged),
                "scoped_out": [c.to_dict() for c in self.scoped_out],
                "scoped_in": [c.to_dict() for c in self.scoped_in],
                "risk_accepted": [c.to_dict() for c in self.risk_accepted],
                "acceptance_lapsed": [c.to_dict() for c in self.acceptance_lapsed],
                "only_in_earlier": list(self.only_earlier),
                "only_in_later": list(self.only_later),
            },
            "remediation": {
                "closed": self.remediation_closed,
                "opened": self.remediation_opened,
                "set_aside": self.remediation_set_aside,
                "control_gone": self.remediation_control_gone,
                "unplanned": self.remediation_unplanned,
                "first_planned": self.remediation_first_planned,
                "control_new": self.remediation_control_new,
                "resumed": self.remediation_resumed,
                "still_open": len(self.remediation_carried),
            },
        }

    def headline(self) -> str:
        """One line a human can read off the end of a pipeline."""
        if not self.comparable:
            # The report section states the reason and shows no numbers. The
            # line printed beside it showed the movement anyway (§16.7).
            return (
                f"not comparable with {self.earlier_id} ({self.not_comparable_because}); "
                f"no readiness change, control movement or remediation counts are reported"
            )
        direction = (
            "up"
            if self.readiness_change > 0
            else ("down" if self.readiness_change < 0 else "level")
        )
        decided = ""
        # Scoped back in belongs here as much as scoped out: the control rejoins
        # the denominator and pulls the score down. Without it, a withdrawn
        # exclusion read "down 25.9, 0 regressed, 0 opened" and nothing else.
        if self.risk_accepted or self.acceptance_lapsed or self.scoped_out or self.scoped_in:
            decided = (
                f"; {len(self.risk_accepted)} accepted as risk, "
                f"{len(self.acceptance_lapsed)} acceptance(s) lapsed, "
                f"{len(self.scoped_out)} scoped out, "
                f"{len(self.scoped_in)} scoped back in"
            )
        remediation = (
            f"{len(self.remediation_closed)} remediation item(s) closed, "
            f"{len(self.remediation_opened)} opened"
            if self.remediation_tracked
            else "no remediation planned by either run"
        )
        return (
            f"readiness {self.readiness_before}% → {self.readiness_after}% "
            f"({direction} {abs(self.readiness_change)}), "
            f"{len(self.improved)} improved, {len(self.regressed)} regressed, "
            f"{remediation}{decided}"
        )


def _planned_remediation(document: dict[str, Any]) -> bool:
    """Whether the run included the remediation capability at all."""
    modules = document.get("modules_run")
    if isinstance(modules, list):
        return "remediation_plan" in [str(m) for m in modules]
    # A record with no module list: take the plan's presence as the answer.
    return bool((document.get("remediation") or {}).get("items"))


def _ran(document: dict[str, Any], module: str) -> bool | None:
    """Whether the run included a capability, or None if the record does not say."""
    modules = document.get("modules_run")
    if isinstance(modules, list):
        return module in [str(m) for m in modules]
    return None


def _failed(document: dict[str, Any]) -> list[str]:
    """The capabilities that failed during the run, by name.

    The engine records a dict of name to error; a record rebuilt elsewhere may
    hold the names alone.
    """
    failed = document.get("failed_modules")
    if isinstance(failed, (dict, list)):
        return sorted(str(name) for name in failed)
    return []


def _why_not_run(document: dict[str, Any], module: str) -> str:
    """Why a run has no output from a capability: it failed, or was not selected.

    A failed capability is left out of `modules_run` too, so both read alike
    there, and the caveat blamed the capability group for a crash.
    """
    if module in _failed(document):
        return "it failed during that run"
    return "its capability group left it out"


#: The capability that gives each control its verdict. A run where it failed
#: has no verdicts at all, and read against a healthy one as "54.1% → 0.0%
#: (down 54.1)", every control "a scope change or a defect".
ASSESSING_CAPABILITY = "control_mapping"


#: The capabilities that decide a control rather than assess it, with what a run
#: without them cannot show, and the movement lists that absence would fill.
#: A standard run followed by a quick one read every acceptance as lapsed and
#: every exclusion as scoped back in, and the quick run had looked at neither.
DECIDING_CAPABILITIES: tuple[tuple[str, str, str, str], ...] = (
    ("exception_review", "risk acceptances", "risk_accepted", "acceptance_lapsed"),
    ("scope_review", "scope exclusions", "scoped_out", "scoped_in"),
)


def _controls(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c.get("control_id")): c for c in document.get("controls") or []}


def _items(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    remediation = document.get("remediation") or {}
    return {str(i.get("item_id")): i for i in remediation.get("items") or []}


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": item.get("item_id", ""),
        "control_id": item.get("control_id", ""),
        "control_name": item.get("control_name", ""),
        "severity": item.get("severity", ""),
        "owner": item.get("owner", ""),
        "due_date": item.get("due_date", ""),
    }


def _started(document: dict[str, Any]) -> datetime | None:
    """When a stored assessment started, or None if the record does not say."""
    raw = str(document.get("started_at") or "")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _tenant(document: dict[str, Any], which: str) -> str:
    """The tenant a record belongs to, or ValueError if it does not say plainly.

    The engine writes the tenant twice, as `tenant_id` and `client_id`. Two
    records naming neither compared as tenant "" and passed the same-tenant
    check, and a record whose two names disagree was read as the first one
    while the retired ingest path files it under the second.
    """
    names = {
        str(document.get(key) or "")
        for key in ("tenant_id", "client_id")
        if str(document.get(key) or "").strip()
    }
    if not names:
        raise ValueError(
            f"the {which} assessment names no tenant; a record that does not say "
            f"whose it is cannot be compared"
        )
    if len(names) > 1:
        raise ValueError(
            f"the {which} assessment names two tenants "
            f"({' and '.join(repr(n) for n in sorted(names))}); "
            f"a record that contradicts itself cannot be compared"
        )
    return names.pop()


def compare(earlier: dict[str, Any], later: dict[str, Any]) -> Comparison:
    """What changed between two assessments of the same tenant.

    Refuses two tenants outright — a trend across clients is meaningless and
    would be a cross-tenant read besides. A record that names no tenant, or two,
    is refused too: the same-tenant check cannot be made on it. A different
    framework, or a different version of one, produces a comparison marked not
    comparable with the reason stated, rather than a number that looks like a
    trend and is not.
    """
    earlier_tenant = _tenant(earlier, "earlier")
    later_tenant = _tenant(later, "later")
    if earlier_tenant != later_tenant:
        raise ValueError(
            f"cannot compare assessments of different tenants: "
            f"{earlier_tenant!r} and {later_tenant!r}"
        )

    # One record on both sides read "level 0.0, 0 improved, 0 regressed", and
    # the client report gained a "Since the last assessment" section saying
    # nothing had moved since itself. The pipelines pass `store latest
    # --before` for this reason; the commands an operator runs did not check.
    earlier_id = str(earlier.get("assessment_id") or "")
    if earlier_id and earlier_id == str(later.get("assessment_id") or ""):
        raise ValueError(
            f"both sides are assessment {earlier_id}; an assessment compared with "
            f"itself is not a trend"
        )

    # The flags are trusted for which is which, so a swapped pair would read
    # every improvement as a regression. Where both records say when they
    # started, a "later" that started before the "earlier" is refused.
    earlier_started = _started(earlier)
    later_started = _started(later)
    if earlier_started and later_started and earlier_started > later_started:
        raise ValueError(
            f"the earlier assessment ({earlier.get('assessment_id', '')}, {earlier_started}) "
            f"started after the later one ({later.get('assessment_id', '')}, {later_started}); "
            f"swap them, or the trend reads backwards"
        )

    earlier_framework = (earlier.get("framework") or {}).get("id", "")
    later_framework = (later.get("framework") or {}).get("id", "")
    earlier_version = (earlier.get("framework") or {}).get("version", "")
    later_version = (later.get("framework") or {}).get("version", "")

    comparison = Comparison(
        tenant_id=later_tenant,
        framework_id=str(later_framework),
        earlier_id=str(earlier.get("assessment_id", "")),
        later_id=str(later.get("assessment_id", "")),
        earlier_at=str(earlier.get("started_at", "")),
        later_at=str(later.get("started_at", "")),
        readiness_before=float((earlier.get("summary") or {}).get("readiness_score") or 0.0),
        readiness_after=float((later.get("summary") or {}).get("readiness_score") or 0.0),
    )

    if earlier_framework != later_framework:
        comparison.comparable = False
        comparison.not_comparable_because = "different frameworks"
        comparison.caveats.append(
            f"These are assessments against different frameworks "
            f"({earlier_framework} and {later_framework}). The readiness figures are "
            f"not a trend and the controls do not correspond."
        )
    elif earlier_version != later_version:
        comparison.comparable = False
        comparison.not_comparable_because = "the framework version changed"
        comparison.caveats.append(
            f"The framework moved from version {earlier_version} to {later_version} "
            f"between these assessments. Controls that changed with it are not a "
            f"like-for-like comparison, and the readiness figures are not a trend."
        )

    # A capability that failed produced nothing, and its absence reads as a
    # change: no verdicts read as a collapse, no plan as every item gone. The
    # engine names each failure; this is the comparison saying so.
    failed_sides = []
    for which, document in (("earlier", earlier), ("later", later)):
        failed = _failed(document)
        if not failed:
            continue
        comparison.caveats.append(
            f"{len(failed)} of the {which} assessment's capabilities failed during the "
            f"run ({', '.join(failed)}). What they decide is missing from that "
            f"assessment, not changed in it."
        )
        if ASSESSING_CAPABILITY in failed:
            failed_sides.append(which)
    if failed_sides and comparison.comparable:
        comparison.comparable = False
        comparison.not_comparable_because = (
            f"control mapping failed in the {' and '.join(failed_sides)} "
            f"assessment{'s' if len(failed_sides) > 1 else ''}"
        )
        comparison.caveats.append(
            f"Control mapping, which gives each control its verdict, failed in the "
            f"{' and '.join(failed_sides)} assessment{'s' if len(failed_sides) > 1 else ''}. "
            f"Without verdicts the readiness figures are not a trend and the controls "
            f"do not correspond."
        )

    before = _controls(earlier)
    after = _controls(later)

    for control_id in sorted(set(before) & set(after)):
        was, now = before[control_id], after[control_id]
        was_status, now_status = str(was.get("status")), str(now.get("status"))
        change = ControlChange(
            control_id=control_id,
            control_name=str(now.get("control_name", "")),
            was=was_status,
            now=now_status,
            movement=UNCHANGED,
            points_before=int(was.get("points_covered") or 0),
            points_after=int(now.get("points_covered") or 0),
        )

        # A control scoped out is not a control fixed. It leaves the denominator
        # and lifts the score, which looks exactly like progress.
        if now_status == str(ControlStatus.NOT_APPLICABLE) and was_status != now_status:
            change.movement = SCOPED_OUT
            comparison.scoped_out.append(change)
            continue
        if was_status == str(ControlStatus.NOT_APPLICABLE) and was_status != now_status:
            change.movement = SCOPED_IN
            comparison.scoped_in.append(change)
            continue

        accepted = str(ControlStatus.ACCEPTED_RISK)
        if now_status == accepted and was_status == str(ControlStatus.COMPLIANT):
            # Met, and now not: the control stopped working and the acceptance
            # is a decision about that. The mirror of accepted-then-fixed below.
            # As a decision alone it read "0 regressed" over a falling score.
            change.movement = REGRESSED
            comparison.regressed.append(change)
            continue
        if now_status == accepted and was_status != accepted:
            change.movement = RISK_ACCEPTED
            comparison.risk_accepted.append(change)
            continue
        if was_status == accepted and now_status != accepted:
            if now_status == str(ControlStatus.COMPLIANT):
                # Accepted, then actually fixed: that is an improvement.
                change.movement = IMPROVED
                comparison.improved.append(change)
            else:
                change.movement = ACCEPTANCE_LAPSED
                comparison.acceptance_lapsed.append(change)
            continue

        was_rank, now_rank = _rank(was_status), _rank(now_status)
        if was_rank is None or now_rank is None or was_rank == now_rank:
            # Same rank still counts as unchanged movement even when the status
            # differs — partial to accepted_risk is a decision, not progress.
            comparison.unchanged.append(change)
        elif now_rank > was_rank:
            change.movement = IMPROVED
            comparison.improved.append(change)
        else:
            change.movement = REGRESSED
            comparison.regressed.append(change)

    comparison.only_earlier = sorted(set(before) - set(after))
    comparison.only_later = sorted(set(after) - set(before))
    if comparison.only_earlier or comparison.only_later:
        comparison.caveats.append(
            f"{len(comparison.only_earlier)} control(s) appear only in the earlier "
            f"assessment and {len(comparison.only_later)} only in the later one. "
            f"They are named rather than dropped: a control that disappears between "
            f"two runs is either a scope change or a defect."
        )

    for module, decisions, into, out_of in DECIDING_CAPABILITIES:
        ran_before, ran_after = _ran(earlier, module), _ran(later, module)
        if ran_before is None or ran_after is None or ran_before == ran_after:
            continue
        which, listed = ("earlier", into) if not ran_before else ("later", out_of)
        absent = earlier if which == "earlier" else later
        comparison.caveats.append(
            f"The {which} assessment did not run {module.replace('_', ' ')} "
            f"({_why_not_run(absent, module)}), so it applied no {decisions}. "
            f"{len(getattr(comparison, listed))} control(s) listed as "
            f"{listed.replace('_', ' ')} may reflect that rather than a decision made "
            f"between the two runs."
        )

    # A run without the remediation capability planned nothing, so every item
    # in the other run would read as opened (or closed) against it. A quick-group
    # run followed by a deep one read "27 opened", and no gap had appeared. Those
    # items go to first_planned (or unplanned) below; this caveat says why.
    planned_before = _planned_remediation(earlier)
    planned_after = _planned_remediation(later)
    if planned_before != planned_after:
        which = "earlier" if not planned_before else "later"
        absent = earlier if which == "earlier" else later
        comparison.caveats.append(
            f"The {which} assessment did not run remediation planning "
            f"({_why_not_run(absent, 'remediation_plan')}), so the counts of remediation "
            f"items opened and closed are not a trend."
        )
    elif _ran(earlier, "remediation_plan") is False and _ran(later, "remediation_plan") is False:
        # Two quick runs, a gap fixed between them: the line read "1 improved,
        # 0 remediation item(s) closed" with nothing to say no plan existed.
        # Only on the module lists' word: a record without one and an empty
        # plan may have planned and found nothing to fix.
        comparison.remediation_tracked = False
        failed_in = sum("remediation_plan" in _failed(d) for d in (earlier, later))
        why = (
            "their capability groups left it out",
            "it failed during one run and the other's capability group left it out",
            "it failed during both runs",
        )[failed_in]
        comparison.caveats.append(
            f"Neither assessment ran remediation planning ({why}), so no remediation "
            f"items were planned, and none are counted as opened or closed."
        )

    items_before, items_after = _items(earlier), _items(later)
    # An item that left the plan is closed only if its control is not now
    # sitting under a risk acceptance or out of scope — those items were set
    # aside by a decision, and "27 closed" after a mass acceptance is the
    # number that looks like progress and is not.
    set_aside_controls = (
        {c.control_id for c in comparison.risk_accepted}
        | {c.control_id for c in comparison.scoped_out}
        | {
            str(cid)
            for cid, now in after.items()
            if str(now.get("status"))
            in (str(ControlStatus.ACCEPTED_RISK), str(ControlStatus.NOT_APPLICABLE))
        }
    )
    gone = sorted(set(items_before) - set(items_after))
    for item_id in gone:
        control_id = str(items_before[item_id].get("control_id", ""))
        if not planned_after:
            # The later run planned nothing, so every item is missing from it.
            comparison.remediation_unplanned.append(_brief(items_before[item_id]))
        elif control_id not in after:
            # The control left the assessment and took its item with it.
            comparison.remediation_control_gone.append(_brief(items_before[item_id]))
        elif control_id in set_aside_controls:
            comparison.remediation_set_aside.append(_brief(items_before[item_id]))
        else:
            comparison.remediation_closed.append(_brief(items_before[item_id]))
    if comparison.remediation_control_gone:
        comparison.caveats.append(
            f"{len(comparison.remediation_control_gone)} remediation item(s) belong to "
            f"controls that are not in the later assessment. They left the plan with "
            f"their control and are not counted as closed."
        )
    if comparison.remediation_unplanned:
        comparison.caveats.append(
            f"{len(comparison.remediation_unplanned)} remediation item(s) from the earlier "
            f"plan were not re-planned by the later assessment. Whether they were fixed "
            f"is unknown; they are not counted as closed."
        )
    # The mirror of set-aside: a control that sat under an acceptance or out
    # of scope had no item, and when the decision ended its gap came back.
    decided_before = {
        str(cid)
        for cid, was in before.items()
        if str(was.get("status"))
        in (str(ControlStatus.ACCEPTED_RISK), str(ControlStatus.NOT_APPLICABLE))
    }
    for item_id in sorted(set(items_after) - set(items_before)):
        control_id = str(items_after[item_id].get("control_id", ""))
        if not planned_before:
            # The earlier run planned nothing, so every item is new to it.
            comparison.remediation_first_planned.append(_brief(items_after[item_id]))
        elif control_id not in before:
            # The control joined the assessment and brought its item with it.
            comparison.remediation_control_new.append(_brief(items_after[item_id]))
        elif control_id in decided_before:
            comparison.remediation_resumed.append(_brief(items_after[item_id]))
        else:
            comparison.remediation_opened.append(_brief(items_after[item_id]))
    if comparison.remediation_first_planned:
        comparison.caveats.append(
            f"{len(comparison.remediation_first_planned)} remediation item(s) in the later "
            f"plan were first planned by it; the earlier assessment planned none. Whether "
            f"the gaps are new is unknown; they are not counted as opened."
        )
    if comparison.remediation_control_new:
        comparison.caveats.append(
            f"{len(comparison.remediation_control_new)} remediation item(s) belong to "
            f"controls that are not in the earlier assessment. They joined the plan with "
            f"their control and are not counted as opened."
        )
    if comparison.remediation_resumed:
        comparison.caveats.append(
            f"{len(comparison.remediation_resumed)} remediation item(s) returned to the "
            f"plan because a risk acceptance ended or a control came back into scope. "
            f"The gaps were there before; they are not counted as opened."
        )
    comparison.remediation_carried = [
        _brief(items_after[i]) for i in sorted(set(items_after) & set(items_before))
    ]

    return comparison
