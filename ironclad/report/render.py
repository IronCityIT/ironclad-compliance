"""HTML report rendering.

Stdlib only. The original generator pulled in Jinja2 to interpolate a dozen
values into a fixed template, which put a third-party dependency between the
pipeline and its deliverable for no expressive gain. Everything here escapes
through html.escape, so evidence file names and client-supplied text cannot
inject markup into a report that gets emailed to an auditor.

White-label rule: nothing on this page names an underlying tool or vendor.
"""

from __future__ import annotations

from html import escape
from typing import Any

from ironclad.ids import utc_now
from ironclad.method import ICIT_POLICY, method_rules
from ironclad.model.assessment import ControlStatus
from ironclad.model.remediation import RemediationPlan
from ironclad.report.views import ReportView, view_for
from ironclad.version import __version__

BRAND = "Iron City IT Advisors"
PRODUCT = "Ironclad Compliance"

STATUS_LABEL: dict[str, str] = {
    "compliant": "Met",
    "partial": "Partially met",
    "gap": "Not met",
    "not_applicable": "Not applicable",
    "accepted_risk": "Risk accepted",
    "pending": "Not assessed",
}

STYLES = """
:root {
  --ink: #1a202c; --muted: #5a6373; --line: #e2e8f0; --navy: #1a365d;
  --met: #22543d; --met-bg: #c6f6d5; --part: #744210; --part-bg: #feebc8;
  --gap: #822727; --gap-bg: #fed7d7; --acc: #2a4365; --acc-bg: #bee3f8;
  --na: #4a5568; --na-bg: #edf2f7;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
       font-size: 11pt; color: var(--ink); margin: 0; padding: 40px; line-height: 1.5; }
header { border-bottom: 3px solid var(--navy); padding-bottom: 18px; margin-bottom: 28px; }
header h1 { color: var(--navy); margin: 0 0 4px; font-size: 22pt; }
header .sub { font-size: 12pt; color: var(--muted); }
header .meta { font-size: 9.5pt; color: var(--muted); margin-top: 10px; }
h2 { color: var(--navy); font-size: 14pt; border-bottom: 1px solid var(--line);
     padding-bottom: 6px; margin-top: 34px; }
.scores { display: flex; flex-wrap: wrap; gap: 12px; margin: 22px 0; }
.score { flex: 1 1 130px; text-align: center; padding: 14px 10px; border-radius: 8px;
         border: 1px solid var(--line); }
.score .value { font-size: 24pt; font-weight: 700; line-height: 1.1; }
.score .label { font-size: 8.5pt; text-transform: uppercase; letter-spacing: .06em;
                color: var(--muted); margin-top: 4px; }
.score.headline { background: var(--navy); color: #fff; border-color: var(--navy); }
.score.headline .label { color: #cbd5e0; }
.score.met .value { color: var(--met); } .score.part .value { color: var(--part); }
.score.gap .value { color: var(--gap); } .score.acc .value { color: var(--acc); }
table { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 9.5pt; }
th { text-align: left; background: #f7fafc; color: var(--muted); font-weight: 600;
     text-transform: uppercase; font-size: 8pt; letter-spacing: .05em;
     padding: 8px 10px; border-bottom: 2px solid var(--line); }
td { padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
tr:last-child td { border-bottom: none; }
.pill { display: inline-block; padding: 2px 9px; border-radius: 11px; font-size: 8pt;
        font-weight: 700; white-space: nowrap; }
.pill.compliant { background: var(--met-bg); color: var(--met); }
.pill.partial { background: var(--part-bg); color: var(--part); }
.pill.gap { background: var(--gap-bg); color: var(--gap); }
.pill.accepted_risk { background: var(--acc-bg); color: var(--acc); }
.pill.not_applicable, .pill.pending { background: var(--na-bg); color: var(--na); }
.pill.critical, .pill.high { background: var(--gap-bg); color: var(--gap); }
.pill.medium { background: var(--part-bg); color: var(--part); }
.pill.low, .pill.info { background: var(--na-bg); color: var(--na); }
.cid { font-weight: 700; color: var(--navy); white-space: nowrap; }
.note { font-size: 8.5pt; color: var(--muted); margin-top: 4px; }
.ours { font-weight: 700; color: var(--navy); white-space: nowrap; }
.callout { background: #f7fafc; border-left: 4px solid var(--navy);
           padding: 14px 18px; margin: 18px 0; }
.callout.warn { border-left-color: #dd6b20; background: #fffaf0; }
footer { margin-top: 44px; padding-top: 18px; border-top: 1px solid var(--line);
         font-size: 8.5pt; color: var(--muted); text-align: center; }
@media print { body { padding: 0; } h2 { page-break-after: avoid; }
                tr { page-break-inside: avoid; } }
"""


def _pill(value: str, label: str | None = None) -> str:
    return f'<span class="pill {escape(value)}">{escape(label or STATUS_LABEL.get(value, value))}</span>'


def _score_cards(summary: Any) -> str:
    cards = [
        ("headline", f"{summary.readiness_score}%", "Readiness"),
        ("met", summary.compliant, "Met"),
        ("part", summary.partial, "Partially met"),
        ("gap", summary.gap, "Not met"),
    ]
    if summary.accepted_risk:
        cards.append(("acc", summary.accepted_risk, "Risk accepted"))
    return "".join(
        f'<div class="score {cls}"><div class="value">{escape(str(value))}</div>'
        f'<div class="label">{escape(label)}</div></div>'
        for cls, value, label in cards
    )


def _control_rows(assessment: Any, view: ReportView) -> str:
    order = {
        s.value: n
        for n, s in enumerate(
            (
                ControlStatus.GAP,
                ControlStatus.PARTIAL,
                ControlStatus.PENDING,
                ControlStatus.ACCEPTED_RISK,
                ControlStatus.COMPLIANT,
                ControlStatus.NOT_APPLICABLE,
            )
        )
    }
    rows = []
    shown = view.register_for(assessment.controls)
    for item in sorted(shown, key=lambda c: (order[str(c.status)], c.control_id)):
        coverage = f"{item.points_covered}/{item.points_total}" if item.points_total else "—"
        notes = "".join(f'<div class="note">{escape(n)}</div>' for n in item.notes)
        rows.append(
            "<tr>"
            f'<td class="cid">{escape(item.control_id)}</td>'
            f"<td>{escape(item.control_name)}"
            f'<div class="note">{escape(item.rationale)}</div>{notes}</td>'
            f"<td>{_pill(str(item.status))}</td>"
            f"<td>{escape(coverage)}</td>"
            f"<td>{len(item.evidence_links)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _remediation_rows(plan: RemediationPlan) -> str:
    rows = []
    for item in plan.ordered():
        due = item.due_date.date().isoformat() if item.due_date else "—"
        required = ", ".join(item.evidence_gap[:4]) or "—"
        rows.append(
            "<tr>"
            f'<td class="cid">{escape(item.control_id)}</td>'
            f"<td>{escape(item.control_name)}"
            f'<div class="note">{escape(item.guidance)}</div></td>'
            f"<td>{_pill(str(item.severity), str(item.severity).title())}</td>"
            f"<td>{escape(item.owner or '—')}</td>"
            f"<td>{escape(due)}</td>"
            f"<td>{escape(required)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _crosswalk_section(module_output: dict[str, Any]) -> str:
    projections = (module_output.get("crosswalk_coverage") or {}).get("projections") or {}
    if not projections:
        return ""

    rows = "".join(
        "<tr>"
        f'<td class="cid">{escape(data["framework"]["name"])}</td>'
        f"<td>{escape(str(data['framework']['version']))}</td>"
        f"<td>{round(100 * data['mapped_share'])}%</td>"
        f"<td>{data['projected_satisfied']} of {data['framework']['control_count']}</td>"
        f"<td>{len(data['unmapped_controls'])}</td>"
        "</tr>"
        for _, data in sorted(projections.items())
    )
    return f"""
    <h2>Coverage of other frameworks</h2>
    <p>Based on the evidence supplied for this assessment, mapped across frameworks.
       These are projected positions, not direct assessments — each would need its own
       review before being relied on for certification.</p>
    <table>
      <thead><tr><th>Framework</th><th>Version</th><th>Addressed by this assessment</th>
      <th>Projected as met</th><th>Requires direct review</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def _method_rows() -> str:
    rows = []
    for rule in method_rules():
        # The Iron City rows are the ones a client or an auditor may want to
        # argue with, so they are marked rather than left to be spotted.
        mark = ' class="ours"' if rule.source == ICIT_POLICY else ""
        value = f'<div class="note">{escape(rule.value)}</div>' if rule.value else ""
        rows.append(
            f"<tr><td>{escape(rule.name)}</td>"
            f"<td{mark}>{escape(rule.source_label)}</td>"
            f"<td>{escape(rule.statement)}{value}</td></tr>"
        )
    return "".join(rows)


def _method_section() -> str:
    return f"""
    <h2>Basis of assessment</h2>
    <p>Where each rule behind these verdicts comes from. The rules marked
       <strong>Iron City policy</strong> are ours, not the framework's: they are
       deliberate, they are stricter than the standard, and they are open to
       being argued with.</p>
    <table>
      <thead><tr><th>Rule</th><th>Whose rule</th><th>What it is</th></tr></thead>
      <tbody>{_method_rows()}</tbody>
    </table>
    """


def render_html(result: Any, client_name: str = "", view: ReportView | None = None) -> str:
    """Render the assessment as a self-contained HTML document.

    The view comes from the assessment type unless one is passed explicitly. An
    abridged view always states what it left out — a gap analysis that silently
    omits the passing controls is indistinguishable from a catastrophic result.
    """
    assessment = result.assessment
    summary = assessment.summary
    framework = assessment.framework
    client = client_name or assessment.tenant_id
    view = view or view_for(assessment.assessment_type)

    consensus = assessment.consensus or {}
    consensus_block = ""
    if consensus and consensus.get("status") not in (None, "unavailable", "undecodable"):
        severity = escape(str(consensus.get("severity", "—")))
        confidence = escape(str(consensus.get("confidence", "—")))
        summary_text = escape(str(consensus.get("summary", "")))[:1200]
        consensus_block = f"""
        <div class="callout">
          <strong>Analyst commentary</strong> — overall position {severity}
          (confidence {confidence}). {summary_text}
          <div class="note">Commentary is advisory. The readiness figure above is computed
          from the control verdicts and does not move with it.</div>
        </div>"""

    warning_block = ""
    if result.warnings or result.failed_modules:
        items = "".join(
            f"<li>{escape(w)}</li>"
            for w in list(result.warnings)
            + [
                f"the {name} stage did not complete: {detail}"
                for name, detail in result.failed_modules.items()
            ]
        )
        warning_block = f"""
        <div class="callout warn">
          <strong>Assessment caveats</strong>
          <ul>{items}</ul>
        </div>"""

    stale_block = ""
    if summary.stale_artifacts:
        stale_block = f"""
        <div class="callout warn">
          <strong>{summary.stale_artifacts} of {summary.evidence_artifacts} evidence items are
          outside their currency window.</strong> Evidence past its window does not support a
          control at audit, and was not counted toward any control below.
        </div>"""

    omission_block = ""
    if view.omission_note:
        omission_block = f"""
        <div class="callout">
          <strong>What this report covers</strong> — {escape(view.omission_note)}
        </div>"""

    remediation_block = ""
    if view.show_remediation:
        remediation_block = f"""
        <h2>Remediation plan</h2>
        <p>{len(result.plan)} item(s), ordered by risk. Target dates are derived
           from severity.</p>
        <table>
          <thead><tr><th>Control</th><th>Action</th><th>Severity</th><th>Owner</th>
          <th>Target date</th><th>Evidence required</th></tr></thead>
          <tbody>{_remediation_rows(result.plan)}</tbody>
        </table>
        """

    register_block = ""
    if view.show_register:
        shown = len(view.register_for(assessment.controls))
        scope = (
            f"{shown} of {summary.total_controls} controls"
            if shown != summary.total_controls
            else f"All {summary.total_controls} controls"
        )
        register_block = f"""
        <h2>Control register</h2>
        <p>{scope}, most severe first.</p>
        <table>
          <thead><tr><th>Control</th><th>Criterion</th><th>Position</th>
          <th>Points evidenced</th><th>Evidence items</th></tr></thead>
          <tbody>{_control_rows(assessment, view)}</tbody>
        </table>
        """

    crosswalk_block = _crosswalk_section(result.module_output) if view.show_crosswalk else ""

    generated = utc_now().strftime("%d %B %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(framework.name)} Readiness — {escape(client)}</title>
<style>{STYLES}</style>
</head>
<body>
<header>
  <h1>{escape(framework.name)}</h1>
  <div class="sub">{escape(view.title)}</div>
  <div class="meta">
    {escape(client)} &nbsp;·&nbsp; {escape(framework.version)} &nbsp;·&nbsp;
    {escape(generated)} &nbsp;·&nbsp; Reference {escape(assessment.assessment_id)}
  </div>
</header>

<h2>Executive summary</h2>
<p>{summary.total_controls} controls were assessed against {escape(framework.name)}
   ({escape(framework.version)}) using {summary.evidence_artifacts} items of evidence.</p>
<div class="scores">{_score_cards(summary)}</div>
{omission_block}
{stale_block}
{consensus_block}
{warning_block}
{remediation_block}
{crosswalk_block}
{register_block}
{_method_section()}

<footer>
  {escape(PRODUCT)} &nbsp;·&nbsp; {escape(BRAND)} &nbsp;·&nbsp; engine {escape(__version__)}<br>
  This report is confidential and prepared for {escape(client)}.
</footer>
</body>
</html>
"""
