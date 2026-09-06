/**
 * The Cloud Functions' decisions, tested.
 *
 * These are the rules that decide who may write and which tenant's path a
 * document lands in. They had no tests at all, and `npm run lint` — a syntax
 * check — was the whole of the functions gate.
 *
 * Run: npm --prefix functions test  (node:test, no dependencies)
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  authorizeIngest,
  checkEvidencePath,
  isSafeDocId,
  keyMatches,
  oneOf,
  safeDocId,
  toClientId,
} = require("../core");

// A key shaped like a real one, so length-sensitive comparison is exercised.
const CONFIGURED = "aaaabbbbccccddddeeeeffff";

test("toClientId: the slug the pipeline and the ingest must agree on", async (t) => {
  await t.test("normalizes free text", () => {
    assert.equal(toClientId("Acme Corp"), "acme-corp");
    assert.equal(toClientId("  ACME  Corp  "), "acme-corp");
    assert.equal(toClientId("Acme, Inc."), "acme-inc");
  });

  await t.test("collapses runs and trims the separator", () => {
    assert.equal(toClientId("a---b"), "a-b");
    assert.equal(toClientId("--acme--"), "acme");
    assert.equal(toClientId("!!!"), "");
  });

  await t.test("strips anything that is not path-safe", () => {
    // The slug is the tenant partition. Nothing that could steer a path may
    // survive it.
    assert.equal(toClientId("../../etc/passwd"), "etc-passwd");
    assert.equal(toClientId("acme/beta"), "acme-beta");
    assert.equal(toClientId("clients/beta/assessments"), "clients-beta-assessments");
    assert.equal(toClientId("__proto__"), "proto");
  });

  await t.test("has no opinion about absent input", () => {
    assert.equal(toClientId(undefined), "");
    assert.equal(toClientId(null), "");
    assert.equal(toClientId(""), "");
  });

  await t.test("is idempotent", () => {
    for (const value of ["Acme Corp", "../beta", "a---b", "ACME"]) {
      assert.equal(toClientId(toClientId(value)), toClientId(value), value);
    }
  });
});

test("document ids are checked, not trusted", async (t) => {
  await t.test("accepts an ordinary id", () => {
    assert.ok(isSafeDocId("acme-soc2-20260906120000"));
    assert.ok(isSafeDocId("CC6.1"));
    assert.ok(isSafeDocId("item_1(a)"));
  });

  await t.test("refuses a value that would address another collection", () => {
    // "a/b/c" under assessments is a document in assessments/a/b/c — a path
    // firestore.rules does not match, so the result would be written where
    // nothing can read it.
    assert.equal(safeDocId("a/b/c"), "");
    assert.equal(safeDocId("../beta"), "");
    assert.equal(safeDocId("acme/../beta"), "");
  });

  await t.test("refuses the ids Firestore itself rejects", () => {
    assert.equal(safeDocId("."), "");
    assert.equal(safeDocId(".."), "");
    assert.equal(safeDocId("__name__"), "");
  });

  await t.test("refuses empty, blank and over-long ids", () => {
    assert.equal(safeDocId(""), "");
    assert.equal(safeDocId("   "), "");
    assert.equal(safeDocId(undefined), "");
    assert.equal(safeDocId("x".repeat(1501)), "");
    assert.equal(safeDocId("x".repeat(1500)), "x".repeat(1500));
  });

  await t.test("trims rather than rejects surrounding space", () => {
    assert.equal(safeDocId("  acme-1  "), "acme-1");
  });
});

test("ingest authorization", async (t) => {
  await t.test("an unconfigured key closes the endpoint", () => {
    // The regression this exists for: an unset key used to mean "open by
    // config", so a deploy that never bound the secret accepted an
    // unauthenticated write into any tenant.
    for (const configured of [undefined, null, "", "   "]) {
      const verdict = authorizeIngest("anything", configured);
      assert.equal(verdict.ok, false, `configured=${JSON.stringify(configured)}`);
      assert.equal(verdict.status, 503);
      assert.equal(verdict.error, "ingest_not_configured");
    }
  });

  await t.test("an unconfigured key is closed even when none is supplied", () => {
    const verdict = authorizeIngest(undefined, "");
    assert.equal(verdict.ok, false);
    assert.equal(verdict.status, 503);
  });

  await t.test("the right key is accepted", () => {
    assert.equal(authorizeIngest(CONFIGURED, CONFIGURED).ok, true);
  });

  await t.test("a wrong key is 401, not 503", () => {
    const verdict = authorizeIngest("wrong", CONFIGURED);
    assert.equal(verdict.ok, false);
    assert.equal(verdict.status, 401);
    assert.equal(verdict.error, "unauthorized");
  });

  await t.test("a missing key is refused", () => {
    for (const supplied of [undefined, null, ""]) {
      assert.equal(authorizeIngest(supplied, CONFIGURED).ok, false);
    }
  });

  await t.test("a prefix of the right key is refused", () => {
    assert.equal(authorizeIngest(CONFIGURED.slice(0, -1), CONFIGURED).ok, false);
    assert.equal(authorizeIngest(`${CONFIGURED}x`, CONFIGURED).ok, false);
  });

  await t.test("the surrounding configuration is trimmed, the key is not", () => {
    assert.equal(authorizeIngest(CONFIGURED, ` ${CONFIGURED} `).ok, true);
    assert.equal(authorizeIngest(` ${CONFIGURED} `, CONFIGURED).ok, false);
  });
});

test("keyMatches compares every byte", async (t) => {
  await t.test("equal strings match", () => {
    assert.equal(keyMatches("abc", "abc"), true);
  });

  await t.test("a difference anywhere fails", () => {
    assert.equal(keyMatches("abc", "abd"), false);
    assert.equal(keyMatches("abc", "Abc"), false);
  });

  await t.test("a differing length fails without comparing", () => {
    assert.equal(keyMatches("ab", "abc"), false);
  });

  await t.test("two empty values are not a match anyone should rely on", () => {
    // Equal, but authorizeIngest never reaches here with an unset key.
    assert.equal(keyMatches("", ""), true);
    assert.equal(authorizeIngest("", "").ok, false);
  });
});

test("evidence paths are pinned to the tenant", async (t) => {
  await t.test("accepts the tenant's own prefix", () => {
    const verdict = checkEvidencePath("gs://ironclad-evidence/acme/", "acme");
    assert.equal(verdict.ok, true);
    assert.equal(verdict.bucket, "ironclad-evidence");
    assert.equal(verdict.prefix, "acme");
  });

  await t.test("accepts a deeper prefix under the tenant", () => {
    const verdict = checkEvidencePath("gs://ironclad-evidence/acme/2026-q3/", "acme");
    assert.equal(verdict.ok, true);
    assert.equal(verdict.prefix, "acme/2026-q3");
  });

  await t.test("accepts a path with no trailing slash", () => {
    assert.equal(checkEvidencePath("gs://bucket/acme", "acme").ok, true);
  });

  await t.test("refuses a traversal that lands in another tenant", () => {
    // The regression this exists for: the old containment check passed this.
    const verdict = checkEvidencePath("gs://bucket/acme/../beta/", "acme");
    assert.equal(verdict.ok, false);
    assert.match(verdict.reason, /relative segment/);
  });

  await t.test("refuses another tenant's prefix outright", () => {
    assert.equal(checkEvidencePath("gs://bucket/beta/", "acme").ok, false);
  });

  await t.test("refuses a tenant id buried deeper in the path", () => {
    // gs://bucket/beta/acme/ is beta's bucket layout, not acme's.
    assert.equal(checkEvidencePath("gs://bucket/beta/acme/", "acme").ok, false);
  });

  await t.test("refuses a prefix that merely starts with the tenant id", () => {
    assert.equal(checkEvidencePath("gs://bucket/acme-holdings/", "acme").ok, false);
    assert.equal(checkEvidencePath("gs://bucket/acmeholdings/", "acme").ok, false);
  });

  await t.test("refuses a non-storage scheme", () => {
    for (const path of [
      "https://bucket/acme/",
      "file:///etc/acme/",
      "/acme/",
      "s3://bucket/acme/",
      "gs:/bucket/acme/",
    ]) {
      assert.equal(checkEvidencePath(path, "acme").ok, false, path);
    }
  });

  await t.test("refuses a bucket-only path", () => {
    assert.equal(checkEvidencePath("gs://bucket", "acme").ok, false);
    assert.equal(checkEvidencePath("gs://bucket/", "acme").ok, false);
  });

  await t.test("refuses an empty segment", () => {
    assert.equal(checkEvidencePath("gs://bucket//acme/", "acme").ok, false);
    assert.equal(checkEvidencePath("gs://bucket/acme//x/", "acme").ok, false);
  });

  await t.test("refuses a malformed bucket", () => {
    assert.equal(checkEvidencePath("gs:///acme/", "acme").ok, false);
    assert.equal(checkEvidencePath("gs://UPPER/acme/", "acme").ok, false);
    assert.equal(checkEvidencePath("gs://-bad/acme/", "acme").ok, false);
  });

  await t.test("refuses everything when no tenant is known", () => {
    assert.equal(checkEvidencePath("gs://bucket/acme/", "").ok, false);
    assert.equal(checkEvidencePath("gs://bucket/acme/", undefined).ok, false);
  });

  await t.test("refuses absent input", () => {
    assert.equal(checkEvidencePath(undefined, "acme").ok, false);
    assert.equal(checkEvidencePath("", "acme").ok, false);
  });

  await t.test("every refusal says why", () => {
    for (const path of ["", "https://x/acme/", "gs://bucket/beta/", "gs://bucket/acme/../beta/"]) {
      const verdict = checkEvidencePath(path, "acme");
      assert.equal(verdict.ok, false, path);
      assert.ok(verdict.reason.length > 10, path);
    }
  });
});

test("oneOf falls back rather than passing a value through", async (t) => {
  const allowed = new Set(["quick", "standard", "deep"]);

  await t.test("keeps an allowed value", () => {
    assert.equal(oneOf("quick", allowed, "deep"), "quick");
  });

  await t.test("falls back for anything else", () => {
    for (const value of ["", "  ", "everything", undefined, null, 7, {}]) {
      assert.equal(oneOf(value, allowed, "deep"), "deep", String(value));
    }
  });

  await t.test("trims before deciding", () => {
    assert.equal(oneOf("  quick  ", allowed, "deep"), "quick");
  });
});
