/**
 * Auth0 sign-in, tenant resolution and the live assessment feed.
 *
 * TENANCY: the browser never chooses its own client_id. Auth0 authenticates the
 * user, the exchange function verifies that token server-side and mints a
 * Firebase custom token carrying the client_id and roles claims, and
 * firestore.rules gate every read on them. Tampering with a client-side value
 * buys nothing — the rules reject the read.
 *
 * Kept separate from app.js so the rendering logic stays testable without
 * pulling the SDKs, and the network, into a test.
 */

import { createAuth0Client } from "https://cdn.jsdelivr.net/npm/@auth0/auth0-spa-js@2.1.3/+esm";
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth,
  signInWithCustomToken,
  signOut,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import {
  getFirestore,
  collection,
  query,
  orderBy,
  limit,
  where,
  onSnapshot,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";
import {
  getFunctions,
  httpsCallable,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-functions.js";

import { renderAssessments, renderRemediation, selectionToArgs } from "/app.js";

const $ = (id) => document.getElementById(id);

function showError(message) {
  const el = $("app-error");
  el.textContent = message;
  el.hidden = false;
}

// Only these roles may commission an assessment. Mirrors the check in
// functions/trigger.js and the permission matrix in the engine; the button is
// hidden for everyone else, and the function refuses regardless.
const MAY_RUN = new Set(["owner", "compliance_manager"]);

export async function startAuth(config) {
  const auth0 = await createAuth0Client({
    domain: config.auth0.domain,
    clientId: config.auth0.clientId,
    authorizationParams: {
      redirect_uri: window.location.origin,
      ...(config.auth0.audience ? { audience: config.auth0.audience } : {}),
    },
    cacheLocation: "localstorage",
  });

  if (location.search.includes("code=") && location.search.includes("state=")) {
    try {
      await auth0.handleRedirectCallback();
      window.history.replaceState({}, document.title, window.location.pathname);
    } catch (err) {
      showError("Sign-in could not be completed. Try again.");
      return;
    }
  }

  const signedIn = await auth0.isAuthenticated();
  $("sign-in").hidden = signedIn;
  $("sign-out").hidden = !signedIn;

  $("sign-in").onclick = () => auth0.loginWithRedirect();
  $("sign-out").onclick = async () => {
    await signOut(getAuth()).catch(() => {});
    await auth0.logout({ logoutParams: { returnTo: window.location.origin } });
  };

  if (!signedIn) {
    $("signed-out").hidden = false;
    return;
  }

  let accessToken;
  try {
    accessToken = await auth0.getTokenSilently();
  } catch (err) {
    showError("Your session expired. Sign in again.");
    return;
  }

  let session;
  try {
    const response = await fetch(config.exchangeUrl, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (response.status === 403) {
      showError("Your account is not linked to a client. Contact your administrator.");
      return;
    }
    if (!response.ok) throw new Error(String(response.status));
    session = await response.json();
  } catch (err) {
    showError("Could not establish a session. Try again shortly.");
    return;
  }

  const firebaseApp = initializeApp(config.firebase);
  try {
    await signInWithCustomToken(getAuth(firebaseApp), session.firebase_token);
  } catch (err) {
    showError("Could not establish a session. Try again shortly.");
    return;
  }

  const roles = Array.isArray(session.roles) ? session.roles : [];
  $("client-name").textContent = session.client_name || session.client_id;
  $("client-roles").textContent = roles.join(", ") || "viewer";
  $("signed-in").hidden = false;

  const canRun = roles.some((r) => MAY_RUN.has(r));
  $("new-assessment").hidden = !canRun;
  if (!canRun) {
    $("run-note").textContent =
      "Your role can view results. Starting an assessment requires the compliance manager or owner role.";
    $("run-note").hidden = false;
  }

  subscribe(firebaseApp, session.client_id);
  wireTrigger(firebaseApp, config);
}

/** Live feeds for the two lists the dashboard shows. */
function subscribe(firebaseApp, clientId) {
  const db = getFirestore(firebaseApp);

  onSnapshot(
    query(
      collection(db, "clients", clientId, "assessments"),
      orderBy("created_at", "desc"),
      limit(20)
    ),
    (snapshot) => {
      $("assessments").innerHTML = renderAssessments(snapshot.docs.map((d) => d.data()));
    },
    () => showError("Could not load your assessments.")
  );

  onSnapshot(
    query(
      collection(db, "clients", clientId, "remediation"),
      where("status", "in", ["open", "in_progress", "blocked"]),
      orderBy("priority", "desc"),
      limit(50)
    ),
    (snapshot) => {
      $("remediation").innerHTML = renderRemediation(snapshot.docs.map((d) => d.data()));
    },
    // A missing composite index is the usual cause here, and it is an
    // operational fault rather than a client-visible one.
    () => showError("Could not load the remediation queue.")
  );
}

function wireTrigger(firebaseApp, config) {
  const form = $("new-assessment");
  if (!form) return;

  form.onsubmit = async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "Starting…";

    try {
      const trigger = httpsCallable(
        getFunctions(firebaseApp, config.region),
        "triggerAssessment"
      );
      await trigger(selectionToArgs(form));
      // The queued record arrives through the live feed; nothing to render here.
    } catch (err) {
      showError(err?.message || "The assessment could not be started.");
    } finally {
      button.disabled = false;
      button.textContent = "Start assessment";
    }
  };
}
