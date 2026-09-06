/**
 * The decisions the Cloud Functions make, with none of the cloud.
 *
 * index.js, exchange.js and trigger.js each open a connection to Firestore at
 * require time, so nothing in them could be tested without a live project. The
 * rules that decide who may write, which tenant a record belongs to and where a
 * document lands are the highest-consequence code in the product, and they were
 * the least examined. They live here instead: no firebase imports, no network,
 * no state — so functions/test can execute every branch.
 *
 * This module is the authority on three things:
 *
 *   1. tenant slugs, which must agree with ironclad.ids.slugify byte for byte,
 *      or the pipeline and the ingest address different documents;
 *   2. document ids, which are attacker-influenced and go straight into a
 *      Firestore path;
 *   3. whether an ingest is authorized at all.
 */

"use strict";

/**
 * Normalize free text into a stable, path-safe tenant slug.
 *
 * Must match ironclad.ids.slugify exactly. tests/test_tenancy.py asserts the
 * two agree over a shared table of cases; this is not a similarity anyone
 * should have to check by eye.
 */
function toClientId(value) {
  return String(value === undefined || value === null ? "" : value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Firestore document ids: no "/" (it would address a different collection), not
// "." or ".." (rejected outright by Firestore), no leading "__" (reserved), and
// under 1500 bytes. Everything here is caller-supplied, so it is checked rather
// than trusted.
const DOC_ID_MAX = 1500;

/**
 * True if `value` is usable verbatim as a Firestore document id.
 *
 * Deliberately a predicate and not a sanitizer for anything that identifies a
 * record: rewriting a bad assessment_id into a valid one would quietly file the
 * result under an id nobody asked for, and a re-run would then create a second
 * record instead of updating the first.
 */
function isSafeDocId(value) {
  const id = String(value === undefined || value === null ? "" : value).trim();
  if (!id || id.length > DOC_ID_MAX) return false;
  if (id.includes("/")) return false;
  if (id === "." || id === "..") return false;
  if (id.startsWith("__") && id.endsWith("__")) return false;
  return true;
}

/** The id if it is safe, otherwise "". */
function safeDocId(value) {
  const id = String(value === undefined || value === null ? "" : value).trim();
  return isSafeDocId(id) ? id : "";
}

/** Constant-time comparison, so a wrong key cannot be probed byte by byte. */
function keyMatches(supplied, expected) {
  const a = String(supplied === undefined || supplied === null ? "" : supplied);
  const b = String(expected === undefined || expected === null ? "" : expected);
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/**
 * Decide whether an ingest request may write.
 *
 * The endpoint used to treat an unset key as "open by config". That is a
 * fail-open: the ingest writes into clients/{client_id}/... with the client id
 * taken from the request body, so a deploy that never bound the secret would
 * have left an unauthenticated endpoint able to create or overwrite a record in
 * any tenant. A missing key now closes the endpoint rather than opening it —
 * a misconfiguration must degrade to refusing work, never to accepting anyone's.
 */
function authorizeIngest(suppliedKey, configuredKey) {
  const configured = String(configuredKey === undefined || configuredKey === null ? "" : configuredKey).trim();
  if (!configured) {
    return {
      ok: false,
      status: 503,
      error: "ingest_not_configured",
      reason: "no ingest key is configured; the endpoint refuses writes",
    };
  }
  if (!keyMatches(suppliedKey, configured)) {
    return { ok: false, status: 401, error: "unauthorized", reason: "the ingest key did not match" };
  }
  return { ok: true, status: 200, error: "", reason: "" };
}

const BUCKET = /^[a-z0-9][a-z0-9._-]{1,221}$/;

/**
 * Validate that an evidence location belongs to the calling tenant.
 *
 * The previous check asked whether the path *contained* "/<client_id>/", which
 * `gs://any-bucket/acme/../beta/` satisfies while pointing at another tenant's
 * evidence. The tenant prefix is structural, so it is checked structurally: the
 * client id must be the first object segment, and no segment may be a traversal.
 */
function checkEvidencePath(path, clientId) {
  const raw = String(path === undefined || path === null ? "" : path).trim();
  const tenant = String(clientId || "").trim();
  const refuse = (reason) => ({ ok: false, reason });

  if (!tenant) return refuse("no client is associated with this account");
  if (!raw.startsWith("gs://")) return refuse("the evidence path must be a gs:// storage path");

  const rest = raw.slice("gs://".length);
  const [bucket, ...segments] = rest.split("/");
  if (!BUCKET.test(bucket)) return refuse("the evidence path names no valid storage bucket");

  // A trailing slash is how a prefix is normally written; anything else empty
  // is a malformed path rather than a prefix.
  const parts = segments.length && segments[segments.length - 1] === "" ? segments.slice(0, -1) : segments;
  if (!parts.length) return refuse("the evidence path must be under this client's own prefix");
  if (parts.some((s) => s === "" || s === "." || s === ".."))
    return refuse("the evidence path may not contain an empty or relative segment");
  if (parts[0] !== tenant)
    return refuse("the evidence path must be under this client's own prefix");

  return { ok: true, reason: "", bucket, prefix: parts.join("/") };
}

/** A value from a fixed set, or the documented default. */
function oneOf(value, allowed, fallback) {
  const candidate = String(value === undefined || value === null ? "" : value).trim();
  return allowed.has(candidate) ? candidate : fallback;
}

module.exports = {
  DOC_ID_MAX,
  authorizeIngest,
  checkEvidencePath,
  isSafeDocId,
  keyMatches,
  oneOf,
  safeDocId,
  toClientId,
};
