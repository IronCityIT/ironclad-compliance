import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { getAuth, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import { getFirestore, collection, doc, getDocs, writeBatch, onSnapshot, serverTimestamp, query } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";
import { buildRecord, renderRecords, renderHistory, renderAttention, registerCsv, exportFileName, isoToday, saveFailureMessage, escapeHtml, FORM_FIELDS, SETTLED_FIELDS } from "/oversight-core.js";

const $ = (id) => document.getElementById(id);
const config = window.ICIT_CONFIG;
const app = initializeApp(config.firebase);
const auth = getAuth(app);
const db = getFirestore(app);
const EDIT_ROLES = new Set(["owner", "compliance_manager", "contributor"]);
const APPROVE_ROLES = new Set(["owner", "compliance_manager"]);
const KINDS = ["partners", "integrations"];
// Leads a CSV download so spreadsheet software reads it as UTF-8.
const BOM = String.fromCharCode(0xfeff);

// Records as last delivered by each snapshot, by kind then id. Edit opens from
// here, so the revision it writes is the one the user was looking at.
const records = { partners: new Map(), integrations: new Map() };
// The record being edited, or null when the form adds a new one.
let editing = null;
// Set once the roles are read: a contributor proposes the settled fields but
// does not change them on an existing record.
let canApproveRecords = false;

function holdSettled(held) {
  if (canApproveRecords) return;
  const form = $("oversight-form");
  for (const f of SETTLED_FIELDS) if (form.elements[f]) form.elements[f].disabled = held;
}

function fail(message) { $("error").textContent = message; $("error").hidden = false; }
function clearError() { $("error").hidden = true; }

function startEdit(kind, id) {
  const prior = records[kind].get(id);
  if (!prior) return;
  editing = { kind, id, prior };
  const form = $("oversight-form");
  form.reset();
  form.elements.record_type.value = kind === "integrations" ? "integration" : "partner";
  form.elements.record_type.disabled = true;
  holdSettled(true);
  for (const f of FORM_FIELDS) if (form.elements[f]) form.elements[f].value = String(prior[f] ?? "");
  $("form-title").textContent = `Edit ${prior.name} (revision ${prior.revision ?? 0} → ${(prior.revision ?? 0) + 1})`;
  $("save-button").textContent = "Save changes";
  $("cancel-edit").hidden = false;
  $("edit-panel").scrollIntoView({ behavior: "smooth" });
}

function endEdit() {
  editing = null;
  const form = $("oversight-form");
  form.reset();
  form.elements.record_type.disabled = false;
  holdSettled(false);
  $("form-title").textContent = "Add oversight record";
  $("save-button").textContent = "Save record";
  $("cancel-edit").hidden = true;
}

async function showHistory(clientId, kind, id) {
  const record = records[kind].get(id);
  $("history-title").textContent = `Change history: ${record?.name ?? id}`;
  $("history-body").innerHTML = '<div class="meta">Loading&hellip;</div>';
  $("history-panel").hidden = false;
  $("history-panel").scrollIntoView({ behavior: "smooth" });
  try {
    const snap = await getDocs(collection(db, "clients", clientId, kind, id, "history"));
    $("history-body").innerHTML = renderHistory(snap.docs.map((d) => d.data()));
  } catch {
    $("history-body").innerHTML = `<div class="error">Could not load the history for ${escapeHtml(record?.name ?? id)}.</div>`;
  }
}

onAuthStateChanged(auth, async (user) => {
  if (!user) { fail("No tenant session is active. Open the compliance dashboard and sign in first."); return; }
  const token = await user.getIdTokenResult();
  const clientId = String(token.claims.client_id || "");
  const roles = Array.isArray(token.claims.roles) ? token.claims.roles : [];
  if (!clientId) { fail("Your account is not linked to a tenant."); return; }
  $("identity").textContent = `${clientId} · ${roles.join(", ") || "viewer"}`;
  const canEdit = roles.some((r) => EDIT_ROLES.has(r));
  const canApprove = roles.some((r) => APPROVE_ROLES.has(r));
  canApproveRecords = canApprove;
  $("edit-panel").hidden = !canEdit;
  if (canEdit && !canApprove) {
    for (const name of ["risk", "agreement_status", "baa_status", "status"]) {
      const el = document.querySelector(`[name="${name}"]`);
      if (el) el.disabled = true;
    }
    $("governance-note").hidden = false;
  }

  // Export only once both kinds have loaded, so a download is never half the
  // register. It is built from what this member can already read.
  const loaded = new Set();
  $("export-csv").addEventListener("click", () => {
    const today = isoToday();
    const csv = registerCsv(Object.fromEntries(KINDS.map((k) => [k, [...records[k].values()]])), today);
    const url = URL.createObjectURL(new Blob([BOM, csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = exportFileName(clientId, today);
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  });

  for (const kind of KINDS) {
    onSnapshot(query(collection(db, "clients", clientId, kind)), (snap) => {
      records[kind] = new Map(snap.docs.map((d) => [d.id, { id: d.id, ...d.data() }]));
      loaded.add(kind);
      $("export-csv").disabled = loaded.size < KINDS.length;
      const sorted = [...records[kind].values()].sort((a, b) => String(a.name).localeCompare(String(b.name)));
      $(kind).innerHTML = renderRecords(sorted, kind, { canEdit });
      // Recomputed from both kinds on every snapshot, with today's date, so
      // the queue never lags a save or a date rolling over.
      $("attention").innerHTML = renderAttention(Object.fromEntries(KINDS.map((k) => [k, [...records[k].values()]])), isoToday());
    }, () => fail(`Could not load ${kind}.`));
    $(kind).addEventListener("click", (e) => {
      const button = e.target.closest("button[data-action]");
      if (!button) return;
      if (button.dataset.action === "history") showHistory(clientId, button.dataset.kind, button.dataset.id);
      if (button.dataset.action === "edit" && canEdit) startEdit(button.dataset.kind, button.dataset.id);
    });
  }
  $("close-history").addEventListener("click", () => { $("history-panel").hidden = true; });
  if (!canEdit) return;

  $("cancel-edit").addEventListener("click", endEdit);
  $("oversight-form").onsubmit = async (e) => {
    e.preventDefault();
    clearError();
    const form = e.currentTarget;
    const current = editing;
    const kind = current ? current.kind : (form.elements.record_type.value === "integration" ? "integrations" : "partners");
    const built = buildRecord({
      form: Object.fromEntries(new FormData(form)),
      prior: current?.prior ?? null,
      canApprove, uid: user.uid, clientId, stamp: serverTimestamp(),
    });
    if (built.error) { fail(built.error); return; }
    const { record } = built;
    try {
      // The record and history/{revision} land together or not at all;
      // firestore.rules refuses either one alone.
      const ref = current ? doc(db, "clients", clientId, kind, current.id) : doc(collection(db, "clients", clientId, kind));
      const batch = writeBatch(db);
      batch.set(ref, record);
      batch.set(doc(ref, "history", String(record.revision)), record);
      await batch.commit();
      endEdit();
    } catch (err) {
      fail(saveFailureMessage(err, current));
    }
  };
});
