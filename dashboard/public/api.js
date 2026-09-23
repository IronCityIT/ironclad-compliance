/**
 * The dashboard's data source when the backend is `ironclad serve`.
 *
 * auth.js reads Firestore, the current implementation. The target architecture
 * retires Firestore (HANDOFF.md §3, §13) and the backend it moves to already
 * exists — `ironclad serve`, the same service the CLI drives, over HTTP. This
 * module is the read side of that move: the two lists the dashboard shows,
 * fetched from the API and shaped into the record `renderAssessments` and
 * `renderRemediation` already take, so the rendering does not change with the
 * backend.
 *
 * What it does not decide is how the browser comes by a bearer token — that is
 * blocker B6 in HANDOFF.md, and it is a decision, not code. The token is taken
 * as a parameter. Nothing here touches the DOM, the Firebase SDK or Auth0, so it
 * is tested in node against a real `ironclad serve` on a loopback port.
 */

const API_PREFIX = "/api/v1";

/** Parse a field that a store may hand back as JSON text rather than a value. */
function parsed(value, fallback) {
  if (value == null) return fallback;
  if (typeof value !== "string") return value;
  const text = value.trim();
  if (!text) return fallback;
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

/**
 * An assessment row as the API lists it, in the shape the card renders.
 *
 * The store keeps the summary flat on the row and nested structures as JSON
 * text; the card was written against the stored document, where the summary
 * is an object and `warnings` is a list. One adapter, so the card stays one
 * function whichever backend fed it.
 */
export function recordFromRow(row) {
  const r = row || {};
  const number = (v) => (v == null || v === "" ? 0 : Number(v));
  return {
    assessment_id: r.assessment_id ?? "",
    tenant_id: r.tenant_id ?? "",
    status: r.status || "completed",
    framework: {
      id: r.framework_id ?? "",
      name: r.framework_name || r.framework_id || "",
      version: r.framework_version ?? "",
    },
    started_at: r.started_at ?? "",
    summary: {
      readiness_score: number(r.readiness_score),
      total_controls: number(r.total_controls),
      compliant: number(r.compliant),
      partial: number(r.partial),
      gap: number(r.gap),
      accepted_risk: number(r.accepted_risk),
      not_applicable: number(r.not_applicable),
      pending: number(r.pending),
      evidence_artifacts: number(r.evidence_artifacts),
      stale_artifacts: number(r.stale_artifacts),
    },
    warnings: parsed(r.warnings, []),
    failed_modules: parsed(r.failed_modules, {}),
    consensus: parsed(r.consensus, null),
  };
}

/** A remediation row as the API lists it, in the shape the queue renders. */
export function itemFromRow(row) {
  const r = row || {};
  return { ...r, evidence_gap: parsed(r.evidence_gap, []) };
}

/**
 * A data source over `ironclad serve`.
 *
 * `baseUrl` is the server's origin (no trailing slash); `token` is the bearer
 * token the server's token file knows; `fetchImpl` exists so a test can
 * substitute one. Every call raises on a refusal with the server's own
 * message, which is written for a person.
 */
export function createApiSource({ baseUrl, token, fetchImpl } = {}) {
  const doFetch = fetchImpl || globalThis.fetch;
  const origin = String(baseUrl || "").replace(/\/+$/, "");
  const headers = { Authorization: `Bearer ${token || ""}` };

  async function get(path) {
    const response = await doFetch(`${origin}${API_PREFIX}${path}`, { headers });
    let body = {};
    try {
      body = await response.json();
    } catch {
      body = {};
    }
    if (!response.ok || body.ok === false) {
      const reason = (body.errors && body.errors[0]) || `HTTP ${response.status}`;
      throw new Error(reason);
    }
    return body.data || {};
  }

  const tenantPath = (tenant) => `/tenants/${encodeURIComponent(tenant)}`;

  return {
    /** The principal the token authenticates, and its permissions. */
    me: () => get("/me"),

    listAssessments: async (tenant, limit = 20) => {
      const data = await get(`${tenantPath(tenant)}/assessments?limit=${limit}`);
      return (data.assessments || []).map(recordFromRow);
    },

    listRemediation: async (tenant, limit = 50) => {
      const data = await get(`${tenantPath(tenant)}/remediation?limit=${limit}`);
      return (data.items || []).map(itemFromRow);
    },

    /**
     * Poll the two lists. Firestore pushed changes; the API is asked. Returns
     * a function that stops the polling. Errors go to `onError` and the
     * polling continues, so one failed request is a message, not a dead page.
     */
    subscribe(tenant, { onAssessments, onRemediation, onError }, intervalMs = 30000) {
      let stopped = false;
      let timer = null;
      const tick = async () => {
        if (stopped) return;
        try {
          const [assessments, items] = await Promise.all([
            this.listAssessments(tenant),
            this.listRemediation(tenant),
          ]);
          if (stopped) return;
          onAssessments?.(assessments);
          onRemediation?.(items);
        } catch (err) {
          onError?.(err);
        }
        if (!stopped) timer = setTimeout(tick, intervalMs);
      };
      tick();
      return () => {
        stopped = true;
        if (timer) clearTimeout(timer);
      };
    },
  };
}
