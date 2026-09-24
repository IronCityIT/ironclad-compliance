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
const { authorizeIngest, safeDocId, toClientId } = require("./core");

if (!getApps().length) initializeApp();
const db = getFirestore();

const REGION = "us-east5";

// Firestore rejects a document over 1 MiB. A deep assessment of a large
// framework with full evidence links can approach that, so the control detail
// is stored in chunks under the assessment rather than inline.
const MAX_CONTROLS_INLINE = 60;

exports.storeAssessmentResults = onRequest(
  { region: REGION, cors: false, memory: "512MiB", timeoutSeconds: 120 },
  async (req, res) => {
    if (req.method !== "POST") {
      res.status(405).json({ error: "method_not_allowed" });
      return;
    }

    // An unset key closes the endpoint. It used to open it, which meant a
    // deploy that never bound the secret accepted an unauthenticated write into
    // any tenant — the client id comes from the body.
    const authorized = authorizeIngest(req.get("X-Ingest-Key"), process.env.INGEST_API_KEY);
    if (!authorized.ok) {
      logger.warn("rejected an ingest", { reason: authorized.reason });
      res.status(authorized.status).json({ error: authorized.error });
      return;
    }

    const body = req.body || {};
    const clientId = toClientId(body.client_id || body.client_name);
    // assessment_id is this product's name for it; scan_id is the shared ingest
    // field name. Accept either so one ingest shape serves every ICIT product.
    // Refused rather than rewritten: this id is the record's identity, and a
    // sanitized substitute would file the result under an id nobody asked for
    // and make a re-run create a second record instead of updating the first.
    const rawAssessmentId = String(body.assessment_id || body.scan_id || "").trim();
    const assessmentId = safeDocId(rawAssessmentId);

    if (!clientId) {
      res.status(400).json({ error: "client_id (or client_name) is required" });
      return;
    }
    if (!assessmentId) {
      res.status(400).json({
        error: rawAssessmentId
          ? "assessment_id (or scan_id) is not a usable document id"
          : "assessment_id (or scan_id) is required",
      });
      return;
    }

    const summary = body.summary || {};
    const controls = Array.isArray(body.controls) ? body.controls : [];
    const findings = Array.isArray(body.findings) ? body.findings : [];
    const remediation = body.remediation || {};
    const remediationItems = Array.isArray(remediation.items) ? remediation.items : [];
    const auditEvents = Array.isArray((body.audit || {}).events) ? body.audit.events : [];

    // Ids that could not be used, reported back rather than silently dropped:
    // a pipeline that lost half its remediation items has to be able to see it.
    const rejected = [];

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
          // A control id is a framework identifier, not free text, so a value
          // that is not path-safe is a corrupt payload rather than something to
          // second-guess.
          const id = safeDocId(control.control_id);
          if (!id) {
            rejected.push(`control ${JSON.stringify(String(control.control_id || ""))}`);
            return;
          }
          batch.set(assessmentRef.collection("controls").doc(id), control, { merge: true });
        });
      }

      remediationItems.forEach((item) => {
        const id = safeDocId(item.item_id);
        if (!id) {
          rejected.push(`remediation item ${JSON.stringify(String(item.item_id || ""))}`);
          return;
        }
        batch.set(
          clientRef.collection("remediation").doc(id),
          { ...item, client_id: clientId, assessment_id: assessmentId, updated_at: FieldValue.serverTimestamp() },
          { merge: true }
        );
      });

      auditEvents.forEach((event) => {
        const id = safeDocId(`${assessmentId}-${String(event.event_id || "")}`);
        if (!id) {
          rejected.push(`audit event ${JSON.stringify(String(event.event_id || ""))}`);
          return;
        }
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

      if (rejected.length) {
        logger.warn("some ids in the payload were not usable", {
          client_id: clientId,
          assessment_id: assessmentId,
          rejected: rejected.slice(0, 20),
        });
      }

      logger.info("stored assessment", {
        client_id: clientId,
        assessment_id: assessmentId,
        controls: controls.length,
        findings: findings.length,
        remediation: remediationItems.length,
        rejected: rejected.length,
      });

      res.status(200).json({
        status: "stored",
        client_id: clientId,
        assessment_id: assessmentId,
        controls: controls.length,
        remediation: remediationItems.length,
        rejected: rejected.length,
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
