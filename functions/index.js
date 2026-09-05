/**
 * Ironclad Compliance — Cloud Functions.
 *
 * storeAssessmentResults: the ingest endpoint for assessment results produced
 * by the GitHub Actions and Jenkins pipelines. Every record is written under
 * its client_id, so tenants are physically partitioned in Firestore:
 *
 *     clients/{client_id}/assessments/{assessment_id}
 *     clients/{client_id}/remediation/{item_id}
 *     clients/{client_id}/audit/{event_id}
 *
 * Region: us-east5 (Columbus) — ICIT standard, no exceptions.
 *
 * The function is the only writer. Dashboard clients read through
 * firestore.rules and have no write access at all, which is what keeps the
 * multi-tenant partitioning decision in exactly one place.
 */

const { onRequest } = require("firebase-functions/v2/https");
const logger = require("firebase-functions/logger");
const { initializeApp, getApps } = require("firebase-admin/app");
const { getFirestore, FieldValue } = require("firebase-admin/firestore");

if (!getApps().length) initializeApp();
const db = getFirestore();

const REGION = "us-east5";

// Firestore rejects a document over 1 MiB. A deep assessment of a large
// framework with full evidence links can approach that, so the control detail
// is stored in chunks under the assessment rather than inline.
const MAX_CONTROLS_INLINE = 60;

/**
 * Normalize a client name into a stable, path-safe client_id slug.
 * Must match ironclad.ids.slugify exactly — the pipeline mints ids with that
 * function and this addresses the documents it produces.
 */
function toClientId(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Constant-time-ish comparison so a wrong key cannot be probed byte by byte. */
function keyMatches(supplied, expected) {
  if (!expected) return true; // no key configured: the endpoint is open by config
  const a = String(supplied || "");
  const b = String(expected);
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

exports.storeAssessmentResults = onRequest(
  { region: REGION, cors: false, memory: "512MiB", timeoutSeconds: 120 },
  async (req, res) => {
    if (req.method !== "POST") {
      res.status(405).json({ error: "method_not_allowed" });
      return;
    }

    if (!keyMatches(req.get("X-Ingest-Key"), process.env.INGEST_API_KEY)) {
      logger.warn("rejected an ingest with a bad key");
      res.status(401).json({ error: "unauthorized" });
      return;
    }

    const body = req.body || {};
    const clientId = toClientId(body.client_id || body.client_name);
    // assessment_id is this product's name for it; scan_id is the shared ingest
    // field name. Accept either so one ingest shape serves every ICIT product.
    const assessmentId = String(body.assessment_id || body.scan_id || "").trim();

    if (!clientId) {
      res.status(400).json({ error: "client_id (or client_name) is required" });
      return;
    }
    if (!assessmentId) {
      res.status(400).json({ error: "assessment_id (or scan_id) is required" });
      return;
    }

    const summary = body.summary || {};
    const controls = Array.isArray(body.controls) ? body.controls : [];
    const findings = Array.isArray(body.findings) ? body.findings : [];
    const remediation = body.remediation || {};
    const remediationItems = Array.isArray(remediation.items) ? remediation.items : [];
    const auditEvents = Array.isArray((body.audit || {}).events) ? body.audit.events : [];

    const clientRef = db.collection("clients").doc(clientId);
    const assessmentRef = clientRef.collection("assessments").doc(assessmentId);

    try {
      // Status is monotonic. A pipeline reports a failure whenever any job in
      // the run failed, which includes the case where the assessment itself
      // succeeded and only a downstream stage broke. That run has already
      // written a real result here, and clobbering it would lose client data.
      if (String(body.status || "") === "failed") {
        const existing = await assessmentRef.get();
        if (existing.exists && existing.get("status") === "completed") {
          await assessmentRef.set(
            { error: body.error || { message: "a stage of this run failed" } },
            { merge: true }
          );
          logger.warn("failure report ignored — assessment already completed", {
            client_id: clientId,
            assessment_id: assessmentId,
          });
          res.status(200).json({
            status: "already_completed",
            client_id: clientId,
            assessment_id: assessmentId,
          });
          return;
        }
      }

      const record = {
        client_id: clientId,
        client_name: body.client_name || null,
        assessment_id: assessmentId,
        scan_id: assessmentId,
        scan_type: body.scan_type || "compliance-assessment",
        product: body.product || "ironclad-compliance",
        engine_version: body.engine_version || null,
        framework: body.framework || {},
        status: body.status || "completed",
        summary,
        readiness_score: summary.readiness_score ?? null,
        findings,
        consensus: body.consensus || null,
        warnings: Array.isArray(body.warnings) ? body.warnings : [],
        failed_modules: body.failed_modules || {},
        report_url: body.report_url || "",
        control_count: controls.length,
        remediation_count: remediationItems.length,
        error: body.error || null,
        created_at: FieldValue.serverTimestamp(),
      };

      // Controls stay inline while the document is comfortably small; past that
      // they move to a subcollection so a large framework cannot push the
      // assessment document over Firestore's 1 MiB limit and lose the whole
      // result.
      if (controls.length <= MAX_CONTROLS_INLINE) {
        record.controls = controls;
      } else {
        record.controls_stored_separately = true;
      }

      const batch = db.batch();
      batch.set(assessmentRef, record, { merge: true });

      if (controls.length > MAX_CONTROLS_INLINE) {
        controls.forEach((control) => {
          const id = String(control.control_id || "").replace(/[^\w.()-]/g, "_");
          if (!id) return;
          batch.set(assessmentRef.collection("controls").doc(id), control, { merge: true });
        });
      }

      remediationItems.forEach((item) => {
        const id = String(item.item_id || "").trim();
        if (!id) return;
        batch.set(
          clientRef.collection("remediation").doc(id),
          { ...item, client_id: clientId, assessment_id: assessmentId, updated_at: FieldValue.serverTimestamp() },
          { merge: true }
        );
      });

      auditEvents.forEach((event) => {
        const id = `${assessmentId}-${String(event.event_id || "")}`;
        batch.set(
          clientRef.collection("audit").doc(id),
          { ...event, client_id: clientId, assessment_id: assessmentId },
          { merge: true }
        );
      });

      batch.set(
        clientRef,
        {
          client_id: clientId,
          name: body.client_name || clientId,
          latest_assessment: assessmentId,
          latest_framework: (body.framework || {}).id || null,
          latest_readiness: summary.readiness_score ?? null,
          latest_assessment_at: FieldValue.serverTimestamp(),
        },
        { merge: true }
      );

      await batch.commit();

      logger.info("stored assessment", {
        client_id: clientId,
        assessment_id: assessmentId,
        controls: controls.length,
        findings: findings.length,
        remediation: remediationItems.length,
      });

      res.status(200).json({
        status: "stored",
        client_id: clientId,
        assessment_id: assessmentId,
        controls: controls.length,
        remediation: remediationItems.length,
      });
    } catch (err) {
      logger.error("failed to store the assessment", err);
      res.status(500).json({ error: "store_failed" });
    }
  }
);

// The Auth0 -> Firebase bridge. Without it firestore.rules can never be
// satisfied, because nothing else mints the client_id claim they gate on.
exports.exchangeAuth0Token = require("./exchange").exchangeAuth0Token;

// Lets the dashboard start an assessment without holding a GitHub token.
exports.triggerAssessment = require("./trigger").triggerAssessment;
