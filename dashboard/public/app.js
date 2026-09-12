/**
 * Pure rendering and selection logic.
 *
 * Deliberately free of the Auth0 and Firebase SDKs so it can be reasoned about
 * and tested without a network. auth.js owns everything that talks to a server.
 *
 * The capability list and the group presets are NOT written here. They come from
 * catalog.json, which is generated from registry.catalog() — the same source the
 * CLI's --list-modules reads. A capability added to the engine appears here
 * without this file changing, and a checkbox maps 1:1 onto `--modules`.
 */

const STATUS_LABEL = {
  compliant: "Met",
  partial: "Partially met",
  gap: "Not met",
  accepted_risk: "Risk accepted",
  not_applicable: "Not applicable",
  pending: "Not assessed",
};

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[ch]);

/** Render the capability checkboxes and group presets from the catalog. */
export function renderCatalog(catalog) {
  const modules = (catalog.modules || [])
    .map(
      (m) => `
      <label class="capability">
        <input type="checkbox" name="module" value="${escapeHtml(m.name)}">
        <span class="capability-name">${escapeHtml(m.name.replace(/_/g, " "))}</span>
        <span class="capability-desc">${escapeHtml(m.description)}</span>
      </label>`
    )
    .join("");

  const groups = (catalog.groups || [])
    .map(
      (g) => `
      <label class="preset">
        <input type="radio" name="group" value="${escapeHtml(g)}"${g === "deep" ? " checked" : ""}>
        <span>${escapeHtml(g)}</span>
      </label>`
    )
    .join("");

  const frameworks = (catalog.frameworks || [])
    .map(
      (f) =>
        `<option value="${escapeHtml(f.alias)}">${escapeHtml(f.name)} (${escapeHtml(
          f.version
        )}) — ${escapeHtml(f.control_count)} controls</option>`
    )
    .join("");

  // The assessment type changes what the issued report shows, never what is
  // assessed, so each option carries the engine's own description of its
  // deliverable rather than a label the dashboard invented.
  const assessmentTypes = (catalog.assessment_types || [])
    .map(
      (t) =>
        `<option value="${escapeHtml(t.name)}" title="${escapeHtml(t.description)}">${escapeHtml(
          t.title
        )} — ${escapeHtml(t.description)}</option>`
    )
    .join("");

  return { modules, groups, frameworks, assessmentTypes };
}

/**
 * Turn the form selection into the arguments the trigger function takes.
 * Named capabilities win over a group preset, exactly as the CLI resolves them.
 */
export function selectionToArgs(form) {
  const modules = Array.from(form.querySelectorAll('input[name="module"]:checked')).map(
    (el) => el.value
  );
  const group = form.querySelector('input[name="group"]:checked');
  const args = {
    framework: form.querySelector('[name="framework"]').value,
    evidence_path: form.querySelector('[name="evidence_path"]').value.trim(),
    assessment_type: form.querySelector('[name="assessment_type"]').value,
  };
  if (modules.length) args.modules = modules;
  else if (group) args.group = group.value;
  return args;
}

function scoreClass(score) {
  if (score >= 80) return "good";
  if (score >= 50) return "fair";
  return "poor";
}

/** The assessment history list. */
export function renderAssessments(assessments) {
  if (!assessments.length) {
    return `<p class="empty">No assessments yet. Start one above.</p>`;
  }

  return assessments
    .map((a) => {
      const summary = a.summary || {};
      const score = summary.readiness_score;
      const framework = (a.framework || {}).name || (a.framework || {}).id || "—";
      const when = a.created_at?.toDate
        ? a.created_at.toDate().toLocaleString()
        : "just now";

      if (a.status === "queued" || a.status === "running") {
        return `
        <article class="assessment pending">
          <header><strong>${escapeHtml(framework)}</strong>
          <span class="pill pending">${escapeHtml(a.status)}</span></header>
          <div class="meta">${escapeHtml(when)} · ${escapeHtml(a.assessment_id || "")}</div>
        </article>`;
      }

      if (a.status === "failed") {
        const reason = (a.error || {}).message || "The assessment did not complete.";
        return `
        <article class="assessment failed">
          <header><strong>${escapeHtml(framework)}</strong>
          <span class="pill gap">failed</span></header>
          <div class="meta">${escapeHtml(when)}</div>
          <p class="error">${escapeHtml(reason)}</p>
        </article>`;
      }

      return `
      <article class="assessment">
        <header>
          <strong>${escapeHtml(framework)}</strong>
          <span class="score ${scoreClass(score ?? 0)}">${escapeHtml(score ?? "—")}%</span>
        </header>
        <div class="meta">${escapeHtml(when)} · ${escapeHtml(a.assessment_id || "")}</div>
        <div class="bars">
          ${bar("compliant", summary.compliant, summary.total_controls)}
          ${bar("partial", summary.partial, summary.total_controls)}
          ${bar("accepted_risk", summary.accepted_risk, summary.total_controls)}
          ${bar("gap", summary.gap, summary.total_controls)}
        </div>
        <div class="counts">
          ${count("compliant", summary.compliant)}
          ${count("partial", summary.partial)}
          ${count("accepted_risk", summary.accepted_risk)}
          ${count("gap", summary.gap)}
        </div>
        ${
          summary.stale_artifacts
            ? `<p class="warn">${escapeHtml(summary.stale_artifacts)} of ${escapeHtml(
                summary.evidence_artifacts
              )} evidence items are out of date.</p>`
            : ""
        }
      </article>`;
    })
    .join("");
}

function bar(kind, value, total) {
  const pct = total ? Math.round((100 * (value || 0)) / total) : 0;
  return pct ? `<span class="bar ${kind}" style="width:${pct}%"></span>` : "";
}

// `kind` is always one of the literals at the call sites above, never record
// data, so it is not escaped here. Nothing else may call these two.
function count(kind, value) {
  return `<span class="pill ${kind}">${escapeHtml(value ?? 0)} ${escapeHtml(
    STATUS_LABEL[kind]
  )}</span>`;
}

/** The remediation queue, worst first. */
export function renderRemediation(items) {
  if (!items.length) {
    return `<p class="empty">Nothing outstanding.</p>`;
  }

  const now = Date.now();
  return items
    .map((item) => {
      const due = item.due_date ? new Date(item.due_date) : null;
      const overdue = due && due.getTime() < now && item.status !== "complete";
      return `
      <tr class="${overdue ? "overdue" : ""}">
        <td class="cid">${escapeHtml(item.control_id)}</td>
        <td>${escapeHtml(item.control_name)}
          <div class="note">${escapeHtml(item.guidance || "")}</div></td>
        <td><span class="pill ${escapeHtml(item.severity)}">${escapeHtml(item.severity)}</span></td>
        <td>${due ? escapeHtml(due.toLocaleDateString()) : "—"}${overdue ? " <em>overdue</em>" : ""}</td>
        <td>${escapeHtml((item.evidence_gap || []).slice(0, 3).join(", ") || "—")}</td>
      </tr>`;
    })
    .join("");
}

export { escapeHtml, STATUS_LABEL };
