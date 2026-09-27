/**
 * The partner and integration register's page logic, kept free of Firebase so
 * it runs under `node --test` as well as in the browser.
 *
 * firestore.rules is the authority on what a register write may contain; this
 * module builds writes the rules will accept and renders what they store.
 */

// Every field a register record may hold. Must match oversightFields() in
// firestore.rules; dashboard/test/oversight.test.js holds the two together.
export const RECORD_FIELDS = [
  "tenant_id", "name", "business_owner", "technical_owner", "status",
  "risk", "data_access", "phi_scope", "data_flow_direction",
  "agreement_status", "baa_status", "baa_execution_date", "baa_document_ref",
  "review_due", "integration_method", "port_protocol", "network_exposure",
  "assurance", "cert_expiration_date", "notes", "revision",
  "created_at", "created_by", "updated_at", "updated_by",
];

// Only an owner or compliance manager may set these; a contributor's write
// must leave them as they were (contributorKeepsGovernanceState()).
export const GOVERNANCE_FIELDS = ["status", "risk", "agreement_status", "baa_status"];

// Who wrote which revision, and when. Not content, so not shown as a change.
const BOOKKEEPING = new Set(["tenant_id", "revision", "created_at", "created_by", "updated_at", "updated_by"]);

// The fields the form edits, in the order a change is listed.
export const FORM_FIELDS = RECORD_FIELDS.filter((f) => !BOOKKEEPING.has(f));

export const DEFAULTS = {
  status: "Pending information",
  risk: "Unrated",
  agreement_status: "Pending review",
  baa_status: "Pending review",
  data_access: "Unknown",
  network_exposure: "Unknown",
};

export const FIELD_LABELS = {
  name: "Name", business_owner: "Business owner", technical_owner: "Technical owner",
  status: "Status", risk: "Risk", data_access: "Data access", phi_scope: "PHI scope",
  data_flow_direction: "Data direction", agreement_status: "Agreement status",
  baa_status: "BAA status", baa_execution_date: "BAA execution date",
  baa_document_ref: "BAA / contract reference", review_due: "Review due",
  integration_method: "Integration method", port_protocol: "Port / protocol",
  network_exposure: "Network exposure", assurance: "Assurance",
  cert_expiration_date: "Certificate expiration", notes: "Purpose / notes",
};

export function escapeHtml(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const text = (v) => String(v ?? "").trim();

// Fields that must hold a value from a closed list; an empty submission is
// "nothing chosen", not a value.
const CHOICE_FIELDS = new Set([...GOVERNANCE_FIELDS, "data_access"]);

/**
 * The record to write, or `{ error }`.
 *
 * `form` holds the submitted values by field name; a field the form did not
 * submit (a disabled select, say) is absent. With no `prior` this is a new
 * record at revision 1. With a `prior` it is the next revision of that record:
 * every stored field carries over unless the form changed it, the creation
 * stamp is kept, and a caller who cannot approve keeps the governance state
 * exactly as it was. `stamp` is the server timestamp sentinel.
 */
export function buildRecord({ form, prior = null, canApprove, uid, clientId, stamp }) {
  const record = {};
  if (prior) {
    for (const f of RECORD_FIELDS) if (f in prior) record[f] = prior[f];
  } else {
    for (const f of FORM_FIELDS) record[f] = DEFAULTS[f] ?? "";
  }
  for (const f of FORM_FIELDS) {
    if (!(f in form)) continue;
    if (GOVERNANCE_FIELDS.includes(f) && !canApprove) continue;
    const v = text(form[f]);
    // A select with nothing chosen keeps what the record already says.
    if (v === "" && CHOICE_FIELDS.has(f)) continue;
    record[f] = v;
  }
  if (!canApprove && !prior) for (const f of GOVERNANCE_FIELDS) record[f] = DEFAULTS[f];
  if (!record.name) return { error: "Name is required." };
  record.tenant_id = clientId;
  record.revision = prior ? (prior.revision ?? 0) + 1 : 1;
  record.created_at = prior ? prior.created_at : stamp;
  record.created_by = prior ? prior.created_by : uid;
  record.updated_at = stamp;
  record.updated_by = uid;
  return { record };
}

// What changed between two stored revisions of a record, in form order.
export function diffRevisions(prev, next) {
  const changes = [];
  for (const field of FORM_FIELDS) {
    const from = text(prev?.[field]);
    const to = text(next?.[field]);
    if (from !== to) changes.push({ field, from, to });
  }
  return changes;
}

export function formatWhen(v) {
  const d = typeof v?.toDate === "function" ? v.toDate() : v instanceof Date ? v : null;
  return d && !Number.isNaN(d.getTime()) ? `${d.toISOString().slice(0, 16).replace("T", " ")} UTC` : "time not recorded";
}

export function renderRecords(records, kind, { canEdit = false } = {}) {
  if (!records.length) return '<div class="meta">No records yet.</div>';
  return records.map((r) => {
    const chip = (v) => `<span class="chip">${escapeHtml(v)}</span>`;
    const actions = `<div class="actions"><button type="button" class="secondary" data-action="history" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(r.id)}">History</button>${canEdit ? `<button type="button" class="secondary" data-action="edit" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(r.id)}">Edit</button>` : ""}</div>`;
    return `<article class="record"><div class="toolbar"><h3>${escapeHtml(r.name)}</h3><span class="chip risk-${escapeHtml(String(r.risk || "").toLowerCase())}">${escapeHtml(r.risk || "Unrated")}</span></div>`
      + `<div class="meta">${escapeHtml(r.status || "")} · Owner: ${escapeHtml(r.business_owner || "Unassigned")}${r.revision ? ` · Revision ${escapeHtml(r.revision)}` : ""}</div>`
      + `<div class="chips">${chip(r.data_access || "Data access unknown")}${chip(r.agreement_status || "Agreement unknown")}${r.integration_method ? chip(r.integration_method) : ""}${r.baa_status ? chip(`BAA: ${r.baa_status}`) : ""}${r.network_exposure ? chip(r.network_exposure) : ""}${r.review_due ? chip(`Review ${r.review_due}`) : ""}</div>`
      + `${r.notes ? `<p>${escapeHtml(r.notes)}</p>` : ""}${actions}</article>`;
  }).join("");
}

/**
 * A record's change history, newest first. Each entry is a full copy of the
 * record as written, so the change at revision n is the difference from n-1.
 * A gap (a record seeded before history existed has none before revision 1)
 * is said, not papered over.
 */
export function renderHistory(entries) {
  const sorted = [...entries].sort((a, b) => (a.revision ?? 0) - (b.revision ?? 0));
  if (!sorted.length) return '<div class="meta">No changes recorded yet. History starts with the first save made through this workspace.</div>';
  const items = sorted.map((entry, i) => {
    const prev = i > 0 && sorted[i - 1].revision === entry.revision - 1 ? sorted[i - 1] : null;
    const head = `<div class="meta">Revision ${escapeHtml(entry.revision)} · ${escapeHtml(formatWhen(entry.updated_at))} · by ${escapeHtml(entry.updated_by || "unknown")}</div>`;
    let body;
    if (!prev && entry.revision === 1 && i === 0) {
      body = "<p>Record created.</p>";
    } else if (!prev) {
      body = "<p>Earlier revisions are not in the history, so the change cannot be shown. The record as saved:</p>"
        + `<ul>${FORM_FIELDS.filter((f) => text(entry[f])).map((f) => `<li>${escapeHtml(FIELD_LABELS[f])}: ${escapeHtml(entry[f])}</li>`).join("")}</ul>`;
    } else {
      const changes = diffRevisions(prev, entry);
      body = changes.length
        ? `<ul>${changes.map((c) => `<li>${escapeHtml(FIELD_LABELS[c.field])}: ${escapeHtml(c.from || "(empty)")} → ${escapeHtml(c.to || "(empty)")}</li>`).join("")}</ul>`
        : "<p>Saved with no field changes.</p>";
    }
    return `<li class="revision">${head}${body}</li>`;
  });
  return `<ol class="history">${items.reverse().join("")}</ol>`;
}

// A refused save is most often a stale form: someone else saved this record
// since it was opened, and history/{revision} already exists.
export function saveFailureMessage(err, editing) {
  if (editing && err?.code === "permission-denied") {
    return "Save refused. This record may have been changed since you opened it. Reopen it to see the latest version, then reapply your change.";
  }
  return err?.message || "Record could not be saved.";
}

// How far ahead a review or assurance expiry is called out before it lapses.
export const ATTENTION_WINDOW_DAYS = 30;

// Ratings at which a relationship must carry a dated assurance.
export const ELEVATED_RISK = ["High", "Critical"];

// Agreement states that let a relationship be Active: signed, or ruled unneeded
// by an approver. Anything else is a live relationship with no contract behind it.
export const AGREEMENT_SETTLED = ["Executed", "Not required"];

// Today's date in UTC as YYYY-MM-DD, the form register dates are stored in.
export function isoToday(now = new Date()) {
  return now.toISOString().slice(0, 10);
}

function addDays(iso, days) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * What a reviewer should look at on one record, most serious first: PHI moving
 * without an executed BAA, a BAA claimed without its evidence or dated after
 * today, an Active relationship with no executed agreement, a lapsed review or
 * assurance, and gaps that leave the record
 * unassessable: PHI with no scope or no recorded direction of flow, no
 * business owner, a High or Critical
 * rating with no assurance expiry (so a lapse could never show). Derived only from
 * what is stored, so it says nothing a reviewer cannot check on the card.
 * Retired records need no attention. `today` is YYYY-MM-DD; ISO dates compare
 * correctly as strings.
 */
export function attentionFindings(record, today) {
  if (record.status === "Retired") return [];
  const soon = addDays(today, ATTENTION_WINDOW_DAYS);
  const findings = [];
  const add = (level, code, message) => findings.push({ level, code, message });
  const baa = text(record.baa_status) || "not recorded";
  if (record.data_access === "PHI" && record.baa_status !== "Executed") {
    add("high", "phi-without-baa", `Handles PHI without an executed BAA (BAA: ${baa}).`);
  }
  if (record.baa_status === "Executed") {
    const missing = [!text(record.baa_execution_date) && "execution date", !text(record.baa_document_ref) && "document reference"].filter(Boolean);
    if (missing.length) add("high", "baa-evidence-missing", `BAA marked executed with no ${missing.join(" or ")} recorded.`);
    const executed = text(record.baa_execution_date);
    if (ISO_DATE.test(executed) && executed > today) add("high", "baa-not-yet-effective", `BAA marked executed with an execution date of ${executed}, after today.`);
  }
  if (record.status === "Active" && !AGREEMENT_SETTLED.includes(record.agreement_status)) {
    add("high", "agreement-not-executed", `Active without an executed agreement (Agreement: ${text(record.agreement_status) || "not recorded"}).`);
  }
  if (record.data_access === "PHI" && !text(record.phi_scope)) add("notice", "phi-scope-missing", "Handles PHI with no PHI scope recorded.");
  if (record.data_access === "PHI" && !text(record.data_flow_direction)) add("notice", "phi-flow-unrecorded", "Handles PHI with no data flow direction recorded.");
  const review = text(record.review_due);
  if (!ISO_DATE.test(review)) add("notice", "review-unscheduled", "No review date set.");
  else if (review < today) add("high", "review-overdue", `Review overdue since ${review}.`);
  else if (review <= soon) add("notice", "review-due-soon", `Review due ${review}.`);
  const expiry = text(record.cert_expiration_date);
  if (ISO_DATE.test(expiry)) {
    if (expiry < today) add("high", "assurance-expired", `Certificate / assurance expired ${expiry}.`);
    else if (expiry <= soon) add("notice", "assurance-expiring", `Certificate / assurance expires ${expiry}.`);
  } else if (ELEVATED_RISK.includes(record.risk)) {
    add("notice", "assurance-undated", `Rated ${record.risk} with no certificate / assurance expiry recorded.`);
  }
  if (!record.risk || record.risk === "Unrated") add("notice", "risk-unrated", "Risk not yet rated.");
  if (!record.data_access || record.data_access === "Unknown") add("notice", "data-access-unknown", "Data access not established.");
  if (!text(record.business_owner)) add("notice", "owner-unassigned", "No business owner recorded.");
  return findings.sort((a, b) => (a.level === b.level ? 0 : a.level === "high" ? -1 : 1));
}

const KIND_LABELS = { partners: "Partner", integrations: "Integration" };

/**
 * The register's review queue: every record with findings, those with a
 * high-level finding first, then by name. `byKind` maps a kind to its records.
 */
export function renderAttention(byKind, today) {
  const rows = [];
  for (const [kind, list] of Object.entries(byKind)) {
    for (const r of list) {
      const findings = attentionFindings(r, today);
      if (findings.length) rows.push({ kind, r, findings, high: findings.some((f) => f.level === "high") });
    }
  }
  if (!rows.length) return `<div class="meta">Nothing needs attention as of ${escapeHtml(today)}.</div>`;
  rows.sort((a, b) => (a.high === b.high ? String(a.r.name).localeCompare(String(b.r.name)) : a.high ? -1 : 1));
  const highCount = rows.filter((x) => x.high).length;
  const summary = `<div class="meta">${rows.length} record${rows.length === 1 ? "" : "s"} to review as of ${escapeHtml(today)}; ${highCount} with a high-priority finding.</div>`;
  const items = rows.map(({ kind, r, findings }) => `<li><strong>${escapeHtml(r.name)}</strong> <span class="meta">${escapeHtml(KIND_LABELS[kind] ?? kind)}</span>`
    + `<ul>${findings.map((f) => `<li class="finding-${f.level}">${f.level === "high" ? "High: " : ""}${escapeHtml(f.message)}</li>`).join("")}</ul></li>`);
  return `${summary}<ul class="attention">${items.join("")}</ul>`;
}

// The register as a spreadsheet: the columns an auditor asks for when
// inventorying business associates, one row per record, with the review
// queue's findings alongside. Bookkeeping stamps are written as UTC.
export const EXPORT_COLUMNS = ["record_type", "id", ...RECORD_FIELDS, "attention_level", "attention"];

// A cell a spreadsheet would evaluate (=, +, -, @, or a leading tab or CR) is
// prefixed with an apostrophe so it is shown as text (OWASP CSV injection).
// Register text is typed by contributors, so it is not trusted as a formula.
function csvCell(v) {
  let s = String(v ?? "");
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function exportValue(record, field) {
  const v = record[field];
  if (typeof v?.toDate === "function" || v instanceof Date) {
    const d = typeof v.toDate === "function" ? v.toDate() : v;
    return Number.isNaN(d.getTime()) ? "" : d.toISOString();
  }
  return v ?? "";
}

/**
 * RFC 4180 CSV (CRLF) of every record of every kind, sorted by kind then name,
 * with each record's highest finding level and its findings as of `today`.
 * Retired records are included: the export is the inventory, not the queue.
 */
export function registerCsv(byKind, today) {
  const rows = [EXPORT_COLUMNS];
  for (const [kind, list] of Object.entries(byKind)) {
    const sorted = [...list].sort((a, b) => String(a.name).localeCompare(String(b.name)));
    for (const r of sorted) {
      const findings = attentionFindings(r, today);
      const level = findings.length ? findings[0].level : "";
      rows.push([
        KIND_LABELS[kind] ?? kind, r.id ?? "",
        ...RECORD_FIELDS.map((f) => exportValue(r, f)),
        level, findings.map((f) => f.message).join(" | "),
      ]);
    }
  }
  return `${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}\r\n`;
}

// A download name that carries the tenant and the date and nothing a
// filesystem would object to.
export function exportFileName(clientId, today) {
  const safe = String(clientId ?? "").replace(/[^A-Za-z0-9_-]/g, "") || "tenant";
  return `oversight-register-${safe}-${today}.csv`;
}
