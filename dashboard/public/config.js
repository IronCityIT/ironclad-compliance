/**
 * Runtime configuration — REPLACED AT DEPLOY TIME.
 *
 * These are placeholders on purpose: the Firebase web config and the Auth0 SPA
 * client id are environment facts, not source. No workflow injects them yet —
 * the deploy.yml this comment once named does not exist, and Firebase Hosting
 * is being retired (HANDOFF.md §13) — so whoever deploys fills them in.
 *
 * The dashboard detects the placeholders the sign-in path reads (app.js
 * isConfigured) and renders an explicit "not configured" state rather than
 * failing with a console error. api.baseUrl is not one of them until B6.
 */
window.ICIT_CONFIG = {
  auth0: {
    domain: "__AUTH0_DOMAIN__",
    clientId: "__AUTH0_CLIENT_ID__",
    audience: "__AUTH0_AUDIENCE__",
  },
  firebase: {
    apiKey: "__FIREBASE_API_KEY__",
    authDomain: "__FIREBASE_AUTH_DOMAIN__",
    projectId: "__FIREBASE_PROJECT_ID__",
  },
  // Swaps a verified Auth0 token for a Firebase custom token carrying the
  // client_id and roles claims that firestore.rules gate on.
  exchangeUrl: "__EXCHANGE_URL__",
  region: "us-east5",
  // The target backend: `ironclad serve`, behind a reverse proxy that
  // terminates TLS. Read by auth.js's startApi once B6 decides how the
  // browser obtains a token; until then this stays a placeholder and the
  // Firestore path above is the one index.html starts.
  api: {
    baseUrl: "__API_BASE_URL__",
    pollMs: 30000,
  },
};
