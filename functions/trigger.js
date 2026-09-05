/**
 * triggerAssessment — start an assessment from the dashboard.
 *
 * Dispatching a GitHub workflow requires a token that must never reach the
 * browser, so the dashboard calls this instead:
 *
 *   dashboard button -> triggerAssessment (this function)
 *                         -> writes clients/{client_id}/assessments/{id}
 *                            with status "queued"
 *                         -> POST /actions/workflows/{file}/dispatches
 *                            -> the assessment workflow runs
 *                               -> storeAssessmentResults replaces the record
 *                                  with status "completed" (or "failed")
 *
 * The queued record is written first and on purpose: it is what makes the run
 * visible the instant the button is pressed, and it is the record that gets
 * marked failed if the dispatch itself dies.
 *
 * MULTI-TENANCY: client_id comes from the VERIFIED token claim, never from the
 * request body. A caller cannot queue an assessment into another tenant.
 *
 * Region: us-east5 (Columbus) — ICIT standard, no exceptions.
 *
 * ---------------------------------------------------------------------------
 * REQUIRES A SECRET THAT MUST BE PROVISIONED FIRST.
 * Dispatching a workflow needs a GitHub token with `actions:write` on
 * IronCityIT/ironclad-compliance. That secret is not in the approved ICIT list,
 * so no value is invented here: it is referenced as GITHUB_DISPATCH_TOKEN and
 * must exist in Secret Manager (us-east5) before this function will deploy.
 * See PRODUCTIZE_NOTES.md.
 * ---------------------------------------------------------------------------
 */

const { onCall, HttpsError } = require("firebase-functions/v2/https");
const { defineSecret } = require("firebase-functions/params");
const logger = require("firebase-functions/logger");
const { initializeApp, getApps } = require("firebase-admin/app");
const { getFirestore, FieldValue } = require("firebase-admin/firestore");

if (!getApps().length) initializeApp();
const db = getFirestore();

const REGION = "us-east5";
const REPO = "IronCityIT/ironclad-compliance";

const GITHUB_DISPATCH_TOKEN = defineSecret("GITHUB_DISPATCH_TOKEN");

/**
 * What the dashboard is allowed to start, and the inputs each accepts. An
 * allow-list on purpose: an arbitrary workflow file from the browser would let
 * a caller run anything in the repository.
 *
 * Keep in step with .github/workflows/ and with registry.catalog() — the CLI,
 * this trigger and the dashboard must offer the same selection.
 */
const DISPATCHABLE = {
  assessment: {
    file: "compliance-assessment.yml",
    inputs: ["client_id", "framework", "evidence_path", "assessment_type", "group"],
  },
};

const FRAMEWORKS = new Set(["soc2", "nist-csf", "pci-dss", "hipaa"]);
const GROUPS = new Set(["quick", "standard", "deep"]);
const TYPES = new Set(["full", "gap-only", "readiness"]);

// Only a compliance manager or the tenant owner may commission an assessment.
// Mirrors the `assessment:run` permission in ironclad.model.tenant.
const MAY_RUN = new Set(["owner", "compliance_manager"]);

exports.triggerAssessment = onCall(
  { region: REGION, secrets: [GITHUB_DISPATCH_TOKEN] },
  async (request) => {
    const auth = request.auth;
    if (!auth) {
      throw new HttpsError("unauthenticated", "Sign-in required.");
    }

    const clientId = String(auth.token.client_id || "").trim();
    if (!clientId) {
      throw new HttpsError("permission-denied", "No client is associated with this account.");
    }

    const roles = Array.isArray(auth.token.roles) ? auth.token.roles : [];
    if (!roles.some((r) => MAY_RUN.has(String(r)))) {
      throw new HttpsError(
        "permission-denied",
        "Starting an assessment requires the compliance manager or owner role."
      );
    }

    const data = request.data || {};
    const workflow = DISPATCHABLE[String(data.workflow || "assessment")];
    if (!workflow) {
      throw new HttpsError("invalid-argument", "Unknown assessment type.");
    }

    const framework = String(data.framework || "").trim();
    if (!FRAMEWORKS.has(framework)) {
      throw new HttpsError("invalid-argument", "Unknown framework.");
    }

    const evidencePath = String(data.evidence_path || "").trim();
    // Evidence must come from the tenant's own prefix. Without this check a
    // caller could point the run at another client's evidence bucket and have
    // the result written under their own tenant.
    if (!evidencePath.startsWith(`gs://`) || !evidencePath.includes(`/${clientId}/`)) {
      throw new HttpsError(
        "invalid-argument",
        "The evidence path must be a storage path under this client's own prefix."
      );
    }

    const group = GROUPS.has(String(data.group)) ? String(data.group) : "deep";
    const assessmentType = TYPES.has(String(data.assessment_type))
      ? String(data.assessment_type)
      : "full";

    // Minted server-side so the dashboard can poll for it immediately and two
    // tenants can never collide on one document.
    const assessmentId = `${clientId}-${framework}-${Date.now()}`;
    const ref = db
      .collection("clients")
      .doc(clientId)
      .collection("assessments")
      .doc(assessmentId);

    await ref.set({
      client_id: clientId,
      assessment_id: assessmentId,
      scan_id: assessmentId,
      scan_type: "compliance-assessment",
      product: "ironclad-compliance",
      framework: { id: framework },
      status: "queued",
      summary: {},
      findings: [],
      requested_by: auth.uid,
      created_at: FieldValue.serverTimestamp(),
    });

    const url = `https://api.github.com/repos/${REPO}/actions/workflows/${workflow.file}/dispatches`;
    const inputs = {
      client_id: clientId,
      framework,
      evidence_path: evidencePath,
      assessment_type: assessmentType,
      group,
    };

    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${GITHUB_DISPATCH_TOKEN.value()}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main", inputs }),
      });
    } catch (err) {
      // A dispatch that never left the building still has to resolve in the UI.
      logger.error("dispatch request threw", { assessment_id: assessmentId, err: String(err) });
      await ref.set(
        {
          status: "failed",
          error: { stage: "dispatch", message: "The assessment could not be started." },
        },
        { merge: true }
      );
      throw new HttpsError("unavailable", "The assessment could not be started.");
    }

    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      // Upstream detail goes to the logs only. The caller sees a generic message.
      logger.error("workflow dispatch rejected", {
        assessment_id: assessmentId,
        status: response.status,
        detail: detail.slice(0, 500),
      });
      await ref.set(
        {
          status: "failed",
          error: { stage: "dispatch", message: "The assessment could not be started." },
        },
        { merge: true }
      );
      throw new HttpsError("internal", "The assessment could not be started.");
    }

    logger.info("assessment dispatched", {
      client_id: clientId,
      assessment_id: assessmentId,
      framework,
      group,
    });

    return { assessment_id: assessmentId, client_id: clientId, status: "queued" };
  }
);
