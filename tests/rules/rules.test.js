/**
 * firestore.rules, exercised against the emulator.
 *
 * These rules are the enforcement point for the product's central promise:
 * a client sees their own compliance position and nobody else's. Until now they
 * had been read carefully and never executed, which for an access-control
 * policy is the same as not having been checked at all — a rule that denies
 * everything and a rule that allows everything both look plausible on the page.
 *
 * The claims under test are minted by functions/exchange.js and by nothing
 * else: `client_id` fixes the tenant, `roles` gates the privileged reads.
 * Documents are seeded with the rules suspended, so a seeding mistake cannot be
 * mistaken for a rule that permits a write.
 *
 * Run: npm --prefix tests/rules test   (starts and stops the emulator itself)
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require("@firebase/rules-unit-testing");
const { doc, getDoc, setDoc, deleteDoc, collection, getDocs } = require("firebase/firestore");

const REPO_ROOT = path.resolve(__dirname, "..", "..");

let env;

const ACME = "acme";
const BETA = "beta-industries";

/** A signed-in caller as exchange.js would mint them. */
function as(clientId, roles) {
  return env.authenticatedContext(`auth0|${clientId}-${(roles || []).join("-") || "none"}`, {
    client_id: clientId,
    roles: roles || [],
  }).firestore();
}

test.before(async () => {
  env = await initializeTestEnvironment({
    projectId: "ironclad-compliance-test",
    firestore: {
      rules: fs.readFileSync(path.join(REPO_ROOT, "firestore.rules"), "utf8"),
      host: "127.0.0.1",
      port: 8080,
    },
  });

  // Seeded with the rules suspended: this is the shape storeAssessmentResults
  // writes through the Admin SDK, which bypasses rules entirely.
  await env.withSecurityRulesDisabled(async (context) => {
    const db = context.firestore();
    for (const clientId of [ACME, BETA]) {
      await setDoc(doc(db, "clients", clientId), {
        client_id: clientId,
        name: clientId,
        latest_readiness: 42,
      });
      await setDoc(doc(db, "clients", clientId, "assessments", `${clientId}-soc2-1`), {
        client_id: clientId,
        readiness_score: 42,
        status: "completed",
      });
      await setDoc(
        doc(db, "clients", clientId, "assessments", `${clientId}-soc2-1`, "controls", "CC6.1"),
        { control_id: "CC6.1", status: "gap" }
      );
      await setDoc(doc(db, "clients", clientId, "remediation", `${clientId}-r1`), {
        client_id: clientId,
        severity: "high",
      });
      await setDoc(doc(db, "clients", clientId, "exceptions", `${clientId}-x1`), {
        client_id: clientId,
        control_id: "CC1.1",
      });
      await setDoc(doc(db, "clients", clientId, "evidence", `${clientId}-ev1`), {
        client_id: clientId,
        sha256: "abc",
      });
      await setDoc(doc(db, "clients", clientId, "audit", `${clientId}-a1`), {
        client_id: clientId,
        action: "assessment.completed",
      });
    }
  });
});

test.after(async () => {
  if (env) await env.cleanup();
});

test("a tenant reads its own record", async (t) => {
  const db = as(ACME, ["compliance_manager"]);

  await t.test("the client document", async () => {
    await assertSucceeds(getDoc(doc(db, "clients", ACME)));
  });

  await t.test("an assessment", async () => {
    await assertSucceeds(getDoc(doc(db, "clients", ACME, "assessments", `${ACME}-soc2-1`)));
  });

  await t.test("control detail stored in its own subcollection", async () => {
    await assertSucceeds(
      getDoc(doc(db, "clients", ACME, "assessments", `${ACME}-soc2-1`, "controls", "CC6.1"))
    );
  });

  await t.test("the remediation queue", async () => {
    await assertSucceeds(getDocs(collection(db, "clients", ACME, "remediation")));
  });

  await t.test("the risk acceptances", async () => {
    await assertSucceeds(getDocs(collection(db, "clients", ACME, "exceptions")));
  });
});

test("a tenant cannot reach another tenant", async (t) => {
  const db = as(ACME, ["owner"]);

  await t.test("not the client document", async () => {
    await assertFails(getDoc(doc(db, "clients", BETA)));
  });

  await t.test("not an assessment", async () => {
    await assertFails(getDoc(doc(db, "clients", BETA, "assessments", `${BETA}-soc2-1`)));
  });

  await t.test("not control detail", async () => {
    await assertFails(
      getDoc(doc(db, "clients", BETA, "assessments", `${BETA}-soc2-1`, "controls", "CC6.1"))
    );
  });

  await t.test("not the remediation queue", async () => {
    await assertFails(getDocs(collection(db, "clients", BETA, "remediation")));
  });

  await t.test("not the evidence index", async () => {
    await assertFails(getDocs(collection(db, "clients", BETA, "evidence")));
  });

  await t.test("not the audit trail", async () => {
    await assertFails(getDocs(collection(db, "clients", BETA, "audit")));
  });

  await t.test("not by listing every client", async () => {
    // The one that would undo the whole partition: a collection query at the
    // root. `allow read` on clients/{clientId} covers get and list, and list is
    // evaluated against the query, not the documents — so this must fail.
    await assertFails(getDocs(collection(db, "clients")));
  });
});

test("an unauthenticated caller reads nothing", async (t) => {
  const db = env.unauthenticatedContext().firestore();

  for (const [name, ref] of [
    ["the client document", () => getDoc(doc(db, "clients", ACME))],
    ["an assessment", () => getDoc(doc(db, "clients", ACME, "assessments", `${ACME}-soc2-1`))],
    ["the remediation queue", () => getDocs(collection(db, "clients", ACME, "remediation"))],
    ["the audit trail", () => getDocs(collection(db, "clients", ACME, "audit"))],
  ]) {
    await t.test(`not ${name}`, async () => {
      await assertFails(ref());
    });
  }
});

test("a signed-in caller with no tenant claim reads nothing", async (t) => {
  // exchange.js refuses to mint a token without a client_id, but a token minted
  // by any other route must not be a way in either.
  const db = env.authenticatedContext("auth0|stray", {}).firestore();

  await t.test("not the client document", async () => {
    await assertFails(getDoc(doc(db, "clients", ACME)));
  });

  await t.test("not an assessment", async () => {
    await assertFails(getDoc(doc(db, "clients", ACME, "assessments", `${ACME}-soc2-1`)));
  });
});

test("the privileged reads are gated on role, inside the tenant", async (t) => {
  await t.test("a viewer sees the position but not the evidence index", async () => {
    const db = as(ACME, ["viewer"]);
    await assertSucceeds(getDoc(doc(db, "clients", ACME)));
    await assertSucceeds(getDoc(doc(db, "clients", ACME, "assessments", `${ACME}-soc2-1`)));
    await assertFails(getDoc(doc(db, "clients", ACME, "evidence", `${ACME}-ev1`)));
    await assertFails(getDoc(doc(db, "clients", ACME, "audit", `${ACME}-a1`)));
  });

  await t.test("a contributor is not privileged either", async () => {
    const db = as(ACME, ["contributor"]);
    await assertFails(getDoc(doc(db, "clients", ACME, "evidence", `${ACME}-ev1`)));
    await assertFails(getDoc(doc(db, "clients", ACME, "audit", `${ACME}-a1`)));
  });

  await t.test("an auditor sees both", async () => {
    const db = as(ACME, ["auditor"]);
    await assertSucceeds(getDoc(doc(db, "clients", ACME, "evidence", `${ACME}-ev1`)));
    await assertSucceeds(getDoc(doc(db, "clients", ACME, "audit", `${ACME}-a1`)));
  });

  for (const role of ["owner", "compliance_manager"]) {
    await t.test(`${role} sees both`, async () => {
      const db = as(ACME, [role]);
      await assertSucceeds(getDoc(doc(db, "clients", ACME, "evidence", `${ACME}-ev1`)));
      await assertSucceeds(getDoc(doc(db, "clients", ACME, "audit", `${ACME}-a1`)));
    });
  }

  await t.test("a privileged role in another tenant grants nothing here", async () => {
    // Both halves of the check matter: the tenant and the role. This is the
    // case that fails if ownsTenant is ever dropped from the privileged rules.
    const db = as(BETA, ["owner", "auditor"]);
    await assertFails(getDoc(doc(db, "clients", ACME, "evidence", `${ACME}-ev1`)));
    await assertFails(getDoc(doc(db, "clients", ACME, "audit", `${ACME}-a1`)));
  });

  await t.test("a roles claim that is not a list is not a grant", async () => {
    const db = env
      .authenticatedContext("auth0|malformed", { client_id: ACME, roles: "owner" })
      .firestore();
    await assertSucceeds(getDoc(doc(db, "clients", ACME)));
    await assertFails(getDoc(doc(db, "clients", ACME, "evidence", `${ACME}-ev1`)));
  });

  await t.test("an unknown role grants nothing privileged", async () => {
    const db = as(ACME, ["superuser", "admin"]);
    await assertFails(getDoc(doc(db, "clients", ACME, "evidence", `${ACME}-ev1`)));
  });
});

test("no client may write anywhere, whatever their role", async (t) => {
  const paths = [
    ["the client document", (db) => doc(db, "clients", ACME)],
    ["an assessment", (db) => doc(db, "clients", ACME, "assessments", `${ACME}-soc2-1`)],
    [
      "control detail",
      (db) => doc(db, "clients", ACME, "assessments", `${ACME}-soc2-1`, "controls", "CC6.1"),
    ],
    ["a remediation item", (db) => doc(db, "clients", ACME, "remediation", `${ACME}-r1`)],
    ["a risk acceptance", (db) => doc(db, "clients", ACME, "exceptions", `${ACME}-x1`)],
    ["an evidence reference", (db) => doc(db, "clients", ACME, "evidence", `${ACME}-ev1`)],
    ["an audit event", (db) => doc(db, "clients", ACME, "audit", `${ACME}-a1`)],
  ];

  for (const [name, ref] of paths) {
    await t.test(`an owner cannot overwrite ${name}`, async () => {
      const db = as(ACME, ["owner"]);
      await assertFails(setDoc(ref(db), { tampered: true }, { merge: true }));
    });

    await t.test(`an owner cannot delete ${name}`, async () => {
      const db = as(ACME, ["owner"]);
      await assertFails(deleteDoc(ref(db)));
    });
  }

  await t.test("an owner cannot close their own remediation item", async () => {
    // The plausible-sounding feature that would breach the model: remediation
    // status is engine-owned, so the dashboard cannot mark work done.
    const db = as(ACME, ["owner"]);
    await assertFails(
      setDoc(doc(db, "clients", ACME, "remediation", `${ACME}-r1`), { status: "closed" }, { merge: true })
    );
  });

  await t.test("a compliance manager cannot create a risk acceptance", async () => {
    // Accepting risk goes through the service API and the audit trail, never
    // straight into the store.
    const db = as(ACME, ["compliance_manager"]);
    await assertFails(
      setDoc(doc(db, "clients", ACME, "exceptions", "self-approved"), {
        control_id: "CC1.1",
        status: "approved",
      })
    );
  });

  await t.test("nobody can create a new tenant", async () => {
    const db = as(ACME, ["owner"]);
    await assertFails(setDoc(doc(db, "clients", "invented-tenant"), { client_id: "invented" }));
  });
});

test("anything outside the modelled tree is closed", async (t) => {
  const db = as(ACME, ["owner"]);

  await t.test("an unmodelled root collection", async () => {
    await assertFails(getDoc(doc(db, "settings", "global")));
    await assertFails(setDoc(doc(db, "settings", "global"), { x: 1 }));
  });

  await t.test("an unmodelled subcollection inside the tenant", async () => {
    // A collection added later is closed until a rule is written for it — the
    // default is stated explicitly in the rules for exactly this reason.
    await assertFails(getDoc(doc(db, "clients", ACME, "notes", "n1")));
    await assertFails(setDoc(doc(db, "clients", ACME, "notes", "n1"), { x: 1 }));
  });

  await t.test("a document nested under an assessment id containing a slash", async () => {
    // What an unchecked assessment_id would have produced: assessments/a/b/c.
    // Unreadable, which is the loss the ingest's id check now prevents.
    await assertFails(
      getDoc(doc(db, "clients", ACME, "assessments", "a", "b", "c", "d", "e"))
    );
  });
});
