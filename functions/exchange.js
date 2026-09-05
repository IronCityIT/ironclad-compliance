/**
 * exchangeAuth0Token — the bridge between Auth0 and Firestore's tenancy model.
 *
 * firestore.rules gate every read on `request.auth.token.client_id`, and on the
 * caller's roles. Nothing else mints those claims, so without this function the
 * rules are unsatisfiable and the dashboard can never read its own data.
 *
 *   Auth0 access token  ->  verified against the tenant's JWKS
 *                       ->  client_id resolved from the Auth0 Organization
 *                       ->  roles resolved from the Organization role claim
 *                       ->  Firebase custom token carrying both
 *
 * The client_id comes ONLY from the verified token. A caller cannot ask for
 * another tenant's id: it is never read from the request body or query string.
 *
 * Region: us-east5 (Columbus) — ICIT standard, no exceptions.
 */

const { onRequest } = require("firebase-functions/v2/https");
const logger = require("firebase-functions/logger");
const { initializeApp, getApps } = require("firebase-admin/app");
const { getAuth } = require("firebase-admin/auth");
const { createRemoteJWKSet, jwtVerify } = require("jose");

if (!getApps().length) initializeApp();

const REGION = "us-east5";
const AUTH0_DOMAIN = process.env.AUTH0_DOMAIN || "dev-ws5377dam2tnlv5g.us.auth0.com";
const AUTH0_AUDIENCE = process.env.AUTH0_AUDIENCE || "";

// Namespaced claims are the preferred source — an Auth0 Action sets them
// explicitly. Falling back to the Organization means SSO tenants work without
// a custom Action having been written first.
const CLIENT_CLAIM = "https://ironcityit.com/client_id";
const ROLES_CLAIM = "https://ironcityit.com/roles";

// Must match ironclad.model.tenant.Role. An unrecognised role string is dropped
// rather than guessed at: a typo in Auth0 must not become a permission grant.
const KNOWN_ROLES = new Set([
  "owner",
  "compliance_manager",
  "contributor",
  "auditor",
  "viewer",
]);

const ISSUER = `https://${AUTH0_DOMAIN}/`;
const jwks = createRemoteJWKSet(new URL(`${ISSUER}.well-known/jwks.json`));

/** Normalize into the same slug shape the pipeline and the ingest use. */
function toClientId(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function toRoles(value) {
  const raw = Array.isArray(value) ? value : String(value || "").split(",");
  const roles = raw
    .map((r) => String(r).trim().toLowerCase())
    .filter((r) => KNOWN_ROLES.has(r));
  // Least privilege by default. A user with no recognised role can sign in and
  // read their tenant's dashboard, and nothing more.
  return roles.length ? Array.from(new Set(roles)) : ["viewer"];
}

exports.exchangeAuth0Token = onRequest(
  { region: REGION, cors: true },
  async (req, res) => {
    if (req.method !== "POST") {
      res.status(405).json({ error: "method_not_allowed" });
      return;
    }

    const header = req.get("Authorization") || "";
    const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
    if (!token) {
      res.status(401).json({ error: "missing_token" });
      return;
    }

    let claims;
    try {
      const verified = await jwtVerify(token, jwks, {
        issuer: ISSUER,
        ...(AUTH0_AUDIENCE ? { audience: AUTH0_AUDIENCE } : {}),
      });
      claims = verified.payload;
    } catch (err) {
      // Signature, issuer, audience or expiry — all mean "not a valid session".
      logger.warn("token verification failed", { reason: String(err && err.code) });
      res.status(401).json({ error: "invalid_token" });
      return;
    }

    const clientId = toClientId(claims[CLIENT_CLAIM] || claims.org_name || claims.org_id);
    if (!clientId) {
      // Authenticated but unassigned. Deliberately distinct from 401 so the
      // dashboard can tell the user to contact an administrator.
      logger.warn("no tenant on token", { sub: claims.sub });
      res.status(403).json({ error: "no_client_assigned" });
      return;
    }

    const roles = toRoles(claims[ROLES_CLAIM] || claims.roles);

    try {
      const uid = `auth0:${claims.sub}`;
      // These claims are what firestore.rules read. Nothing else grants tenancy.
      const firebaseToken = await getAuth().createCustomToken(uid, {
        client_id: clientId,
        roles,
      });
      logger.info("minted tenant token", { client_id: clientId, sub: claims.sub, roles });
      res.status(200).json({
        firebase_token: firebaseToken,
        client_id: clientId,
        client_name: claims.org_name || clientId,
        roles,
      });
    } catch (err) {
      logger.error("custom token mint failed", err);
      res.status(500).json({ error: "mint_failed" });
    }
  }
);
