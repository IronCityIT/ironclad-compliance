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
const {
  doc, getDoc, setDoc, deleteDoc, collection, getDocs, serverTimestamp, writeBatch,
} = require("firebase/firestore");

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

test("partner and integration oversight is tenant-scoped and role-gated", async (t) => {
  const ownPartner = (db, id = "partner-1") => doc(db, "clients", ACME, "partners", id);
  const ownIntegration = (db, id = "integration-1") => doc(db, "clients", ACME, "integrations", id);
  const payload = { tenant_id: ACME, name: "Clinical Integration Partner", risk: "Unrated", agreement_status: "Pending review", baa_status: "Pending review", status: "Pending information", created_by: "", updated_by: "", created_at: serverTimestamp(), updated_at: serverTimestamp() };
  const forUser = (db, role) => ({ ...payload, created_by: `auth0|${ACME}-${role}`, updated_by: `auth0|${ACME}-${role}` });
  const history = (ref, revision) => doc(ref, "history", String(revision));

  // The page's write path: the record and its history/{revision} snapshot in
  // one batch. Anything else is refused, so every test that expects a write to
  // land goes through these two.
  const create = (ref, data) => {
    const record = { ...data, revision: 1 };
    const batch = writeBatch(ref.firestore);
    batch.set(ref, record);
    batch.set(history(ref, 1), record);
    return batch.commit();
  };
  const revise = async (ref, patch, role) => {
    const prior = (await getDoc(ref)).data();
    const record = {
      ...prior, ...patch,
      revision: (prior.revision ?? 0) + 1,
      updated_by: `auth0|${ACME}-${role}`, updated_at: serverTimestamp(),
    };
    const batch = writeBatch(ref.firestore);
    batch.set(ref, record);
    batch.set(history(ref, record.revision), record);
    return batch.commit();
  };

  for (const role of ["owner", "compliance_manager", "contributor"]) {
    await t.test(`${role} can maintain its own oversight records`, async () => {
      const db = as(ACME, [role]);
      await assertSucceeds(create(ownPartner(db, `partner-${role}`), forUser(db, role)));
      await assertSucceeds(create(ownIntegration(db, `integration-${role}`), forUser(db, role)));
      await assertSucceeds(getDoc(ownPartner(db, `partner-${role}`)));
    });
  }

  for (const role of ["viewer", "auditor"]) {
    await t.test(`${role} is read-only`, async () => {
      const db = as(ACME, [role]);
      await assertFails(create(ownPartner(db, `blocked-${role}`), forUser(db, role)));
      await assertSucceeds(getDocs(collection(db, "clients", ACME, "partners")));
    });
  }

  await t.test("a tenant id cannot be spoofed in the record", async () => {
    const db = as(ACME, ["owner"]);
    await assertFails(create(ownPartner(db, "spoofed"), { ...forUser(db, "owner"), tenant_id: BETA }));
  });

  await t.test("a contributor cannot write another tenant", async () => {
    const db = as(ACME, ["contributor"]);
    await assertFails(create(doc(db, "clients", BETA, "partners", "cross-tenant"), {
      ...forUser(db, "contributor"),
      tenant_id: BETA,
      name: "Nope",
    }));
  });

  await t.test("client records are retained rather than deleted", async () => {
    const db = as(ACME, ["owner"]);
    const ref = ownPartner(db, "retained");
    await assertSucceeds(create(ref, forUser(db, "owner")));
    await assertFails(deleteDoc(ref));
  });

  await t.test("a contributor cannot self-approve governance state", async () => {
    const db = as(ACME, ["contributor"]);
    const ref = ownPartner(db, "contributor-state");
    await assertSucceeds(create(ref, forUser(db, "contributor")));
    await assertFails(revise(ref, { risk: "Low" }, "contributor"));
  });

  await t.test("a contributor proposes data access, and only an approver moves it after", async () => {
    const db = as(ACME, ["contributor"]);
    const ref = ownPartner(db, "contributor-access");
    await assertSucceeds(create(ref, { ...forUser(db, "contributor"), data_access: "PHI" }));
    await assertFails(revise(ref, { data_access: "PII" }, "contributor"));
    await assertSucceeds(revise(ref, { data_access: "PHI", notes: "Restated, not moved." }, "contributor"));
    await assertSucceeds(revise(ownPartner(as(ACME, ["compliance_manager"]), "contributor-access"),
      { data_access: "PII" }, "compliance_manager"));
  });

  await t.test("a contributor cannot add data access to a record that has none", async () => {
    const ref = ownPartner(as(ACME, ["owner"]), "no-access-yet");
    await assertSucceeds(create(ref, forUser(ref.firestore, "owner")));
    await assertFails(revise(ownPartner(as(ACME, ["contributor"]), "no-access-yet"),
      { data_access: "PHI" }, "contributor"));
  });

  await t.test("a contributor can still correct the descriptive fields", async () => {
    const db = as(ACME, ["contributor"]);
    const ref = ownPartner(db, "contributor-notes");
    await assertSucceeds(create(ref, forUser(db, "contributor")));
    await assertSucceeds(revise(ref, { notes: "Feed confirmed on the clinical VLAN." }, "contributor"));
  });

  await t.test("an approver can rate a record a contributor proposed", async () => {
    const ref = ownIntegration(as(ACME, ["contributor"]), "rated-later");
    await assertSucceeds(create(ref, forUser(ref.firestore, "contributor")));
    const db = as(ACME, ["compliance_manager"]);
    await assertSucceeds(revise(ownIntegration(db, "rated-later"), {
      risk: "High", baa_status: "Executed", baa_execution_date: "2026-09-01",
    }, "compliance_manager"));
  });

  await t.test("a complete, valid record is accepted", async () => {
    const db = as(ACME, ["owner"]);
    await assertSucceeds(create(ownIntegration(db, "complete"), {
      ...forUser(db, "owner"),
      status: "Active", risk: "High", data_access: "PHI", agreement_status: "Under review",
      baa_status: "Required - pending", data_flow_direction: "Outbound / push",
      business_owner: "Practice administrator", technical_owner: "Integration lead",
      phi_scope: "Demographics, imaging metadata", baa_execution_date: "", baa_document_ref: "",
      review_due: "2026-12-31", integration_method: "API", port_protocol: "HTTPS/443",
      network_exposure: "Private network", assurance: "Pending", cert_expiration_date: "",
      notes: "Feed into the imaging broker.",
    }));
  });

  // The register is the only browser-writable path, so its shape is closed.
  const rejected = {
    "an unknown field": { free_text_dump: "anything at all" },
    "a risk outside the scale": { risk: "Approved" },
    "a status outside the lifecycle": { status: "Done" },
    "an agreement state outside the vocabulary": { agreement_status: "Signed probably" },
    "a data classification outside the vocabulary": { data_access: "Some" },
    "a date that is not ISO": { review_due: "12/31/2026" },
    "a month that does not exist": { review_due: "2026-13-01" },
    "a day that does not exist": { baa_execution_date: "2026-09-00" },
    "a day past the 31st": { cert_expiration_date: "2026-10-32" },
    "an empty name": { name: "" },
    "an oversized name": { name: "x".repeat(121) },
    "a non-string owner": { business_owner: 42 },
    "oversized notes": { notes: "x".repeat(2001) },
  };
  for (const [what, patch] of Object.entries(rejected)) {
    await t.test(`${what} is refused`, async () => {
      const db = as(ACME, ["owner"]);
      await assertFails(create(ownPartner(db, "shape"), { ...forUser(db, "owner"), ...patch }));
    });
  }

  await t.test("a required field cannot be omitted", async () => {
    const db = as(ACME, ["owner"]);
    const { risk, ...withoutRisk } = forUser(db, "owner");
    assert.equal(risk, "Unrated");
    await assertFails(create(ownPartner(db, "no-risk"), withoutRisk));
  });

  await t.test("an update cannot smuggle in an unknown field", async () => {
    const db = as(ACME, ["owner"]);
    const ref = ownPartner(db, "smuggle");
    await assertSucceeds(create(ref, forUser(db, "owner")));
    await assertFails(revise(ref, { ssn: "000-00-0000" }, "owner"));
  });

  // Change history: who changed what and when, and no edit lost to a race.
  await t.test("a record cannot be created without its history entry", async () => {
    const db = as(ACME, ["owner"]);
    await assertFails(setDoc(ownPartner(db, "no-history"), { ...forUser(db, "owner"), revision: 1 }));
  });

  await t.test("a record cannot be changed without a history entry", async () => {
    const db = as(ACME, ["owner"]);
    const ref = ownPartner(db, "silent-edit");
    await assertSucceeds(create(ref, forUser(db, "owner")));
    await assertFails(setDoc(ref, {
      notes: "changed off the record", revision: 2,
      updated_by: `auth0|${ACME}-owner`, updated_at: serverTimestamp(),
    }, { merge: true }));
  });

  await t.test("the history entry must be the record exactly as written", async () => {
    const db = as(ACME, ["owner"]);
    const ref = ownPartner(db, "doctored");
    const record = { ...forUser(db, "owner"), revision: 1 };
    const batch = writeBatch(db);
    batch.set(ref, record);
    batch.set(history(ref, 1), { ...record, risk: "Low" });
    await assertFails(batch.commit());
  });

  await t.test("a history entry cannot be filed under another revision", async () => {
    const db = as(ACME, ["owner"]);
    const ref = ownPartner(db, "misfiled");
    const record = { ...forUser(db, "owner"), revision: 1 };
    const batch = writeBatch(db);
    batch.set(ref, record);
    batch.set(history(ref, 1), record);
    batch.set(history(ref, 7), record);
    await assertFails(batch.commit());
  });

  await t.test("a revision cannot be skipped", async () => {
    const db = as(ACME, ["owner"]);
    const ref = ownPartner(db, "skipped");
    await assertSucceeds(create(ref, forUser(db, "owner")));
    const record = {
      ...(await getDoc(ref)).data(), notes: "jumped", revision: 3,
      updated_by: `auth0|${ACME}-owner`, updated_at: serverTimestamp(),
    };
    const batch = writeBatch(db);
    batch.set(ref, record);
    batch.set(history(ref, 3), record);
    await assertFails(batch.commit());
  });

  await t.test("a stale editor cannot overwrite a newer revision", async () => {
    const db = as(ACME, ["owner"]);
    const ref = ownPartner(db, "race");
    await assertSucceeds(create(ref, forUser(db, "owner")));
    const stale = (await getDoc(ref)).data();
    await assertSucceeds(revise(ref, { notes: "first editor" }, "owner"));
    const record = {
      ...stale, notes: "second editor, working from revision 1", revision: 2,
      updated_by: `auth0|${ACME}-owner`, updated_at: serverTimestamp(),
    };
    const batch = writeBatch(db);
    batch.set(ref, record);
    batch.set(history(ref, 2), record);
    await assertFails(batch.commit());
    assert.equal((await getDoc(ref)).data().notes, "first editor");
  });

  await t.test("history says who changed what, and cannot be rewritten or deleted", async () => {
    const contributor = as(ACME, ["contributor"]);
    await assertSucceeds(create(ownIntegration(contributor, "audited"), forUser(contributor, "contributor")));
    const manager = as(ACME, ["compliance_manager"]);
    await assertSucceeds(revise(ownIntegration(manager, "audited"), { risk: "High" }, "compliance_manager"));

    const viewer = as(ACME, ["viewer"]);
    const first = (await assertSucceeds(getDoc(history(ownIntegration(viewer, "audited"), 1)))).data();
    const second = (await assertSucceeds(getDoc(history(ownIntegration(viewer, "audited"), 2)))).data();
    assert.equal(first.updated_by, `auth0|${ACME}-contributor`);
    assert.equal(first.risk, "Unrated");
    assert.equal(second.updated_by, `auth0|${ACME}-compliance_manager`);
    assert.equal(second.risk, "High");

    const entry = history(ownIntegration(as(ACME, ["owner"]), "audited"), 1);
    await assertFails(setDoc(entry, { ...first, risk: "Low" }));
    await assertFails(deleteDoc(entry));
  });

  await t.test("a history entry cannot be forged without changing the record", async () => {
    const db = as(ACME, ["owner"]);
    const ref = ownPartner(db, "forged");
    await assertSucceeds(create(ref, forUser(db, "owner")));
    const current = (await getDoc(ref)).data();
    await assertFails(setDoc(history(ref, 2), { ...current, revision: 2 }));
  });

  await t.test("another tenant cannot read a record's history", async () => {
    const ref = ownPartner(as(ACME, ["owner"]), "private-history");
    await assertSucceeds(create(ref, forUser(ref.firestore, "owner")));
    const outsider = as(BETA, ["owner"]);
    await assertFails(getDoc(doc(outsider, "clients", ACME, "partners", "private-history", "history", "1")));
  });

  await t.test("a record seeded before history existed takes revision 1 on its first edit", async () => {
    await env.withSecurityRulesDisabled(async (context) => {
      await setDoc(doc(context.firestore(), "clients", ACME, "partners", "seeded"), {
        ...payload, name: "Seeded partner", created_by: "seed", updated_by: "seed",
        created_at: new Date("2026-09-01T00:00:00Z"), updated_at: new Date("2026-09-01T00:00:00Z"),
      });
    });
    const ref = ownPartner(as(ACME, ["owner"]), "seeded");
    await assertSucceeds(revise(ref, { notes: "first edit after seeding" }, "owner"));
    assert.equal((await getDoc(ref)).data().revision, 1);
  });

  // The cases above build writes by hand. These drive the page's own
  // buildRecord (dashboard/public/oversight-core.js), so what the browser
  // actually sends is what the rules are proven to accept or refuse.
  const core = await import(require("node:url").pathToFileURL(path.join(REPO_ROOT, "dashboard", "public", "oversight-core.js")).href);
  const uid = (roles) => `auth0|${ACME}-${roles.join("-")}`;
  const pageSave = (ref, { form, prior = null, roles }) => {
    const built = core.buildRecord({
      form, prior, canApprove: roles.some((r) => ["owner", "compliance_manager"].includes(r)),
      uid: uid(roles), clientId: ACME, stamp: serverTimestamp(),
    });
    assert.ok(built.record, built.error);
    const batch = writeBatch(ref.firestore);
    batch.set(ref, built.record);
    batch.set(history(ref, built.record.revision), built.record);
    return batch.commit();
  };
  const read = async (ref) => (await getDoc(ref)).data();

  await t.test("the page's own writes: contributor proposes, owner rates, contributor edits notes", async () => {
    const asContributor = ownIntegration(as(ACME, ["contributor"]), "page-flow");
    const asOwner = ownIntegration(as(ACME, ["owner"]), "page-flow");
    await assertSucceeds(pageSave(asContributor, { form: { name: "DrChrono to PRIMO", notes: "API feed", risk: "Critical" }, roles: ["contributor"] }));
    assert.equal((await read(asOwner)).risk, "Unrated");
    await assertSucceeds(pageSave(asOwner, { form: { name: "DrChrono to PRIMO", risk: "High", status: "Under review" }, prior: await read(asOwner), roles: ["owner"] }));
    // The contributor's form does not submit governance fields (disabled) and
    // a tampered one is ignored: the edit lands and the rating stands.
    await assertSucceeds(pageSave(asContributor, { form: { name: "DrChrono to PRIMO", notes: "API feed, TLS 1.2", risk: "Low" }, prior: await read(asContributor), roles: ["contributor"] }));
    const final = await read(asOwner);
    assert.deepEqual([final.revision, final.risk, final.status, final.notes], [3, "High", "Under review", "API feed, TLS 1.2"]);
    const entries = (await getDocs(collection(asOwner, "history"))).docs.map((d) => d.data());
    assert.equal(entries.length, 3);
    assert.match(core.renderHistory(entries), /Risk: Unrated → High/);
  });

  await t.test("two editors on the same revision: the second save is refused, not merged", async () => {
    const a = ownPartner(as(ACME, ["owner"]), "page-race");
    const b = ownPartner(as(ACME, ["compliance_manager"]), "page-race");
    await assertSucceeds(pageSave(a, { form: { name: "PRIMO" }, roles: ["owner"] }));
    const openedByA = await read(a);
    const openedByB = await read(b);
    await assertSucceeds(pageSave(a, { form: { name: "PRIMO", risk: "Medium" }, prior: openedByA, roles: ["owner"] }));
    await assertFails(pageSave(b, { form: { name: "PRIMO", risk: "Low" }, prior: openedByB, roles: ["compliance_manager"] }));
    assert.equal((await read(a)).risk, "Medium");
  });

  await t.test("a contributor can edit a Sage Spine seed record through the page", async () => {
    const sage = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "tenants", "sage-spine", "seed.json"), "utf8"));
    const seed = sage.oversight.integrations[0];
    await env.withSecurityRulesDisabled(async (context) => {
      await setDoc(doc(context.firestore(), "clients", ACME, "integrations", "sage-seed"), {
        ...seed, tenant_id: ACME, created_by: "seed", updated_by: "seed",
        created_at: new Date("2026-09-01T00:00:00Z"), updated_at: new Date("2026-09-01T00:00:00Z"),
      });
    });
    const ref = ownIntegration(as(ACME, ["contributor"]), "sage-seed");
    await assertSucceeds(pageSave(ref, { form: { name: seed.name, technical_owner: "ICIT" }, prior: await read(ref), roles: ["contributor"] }));
    const after = await read(ref);
    assert.deepEqual([after.revision, after.risk, after.assurance, after.technical_owner], [1, seed.risk, seed.assurance, "ICIT"]);
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
