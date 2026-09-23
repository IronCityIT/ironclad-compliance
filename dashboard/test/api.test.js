/**
 * The `ironclad serve` data source, against a real server.
 *
 * Not mocked: a mock of the API proves the mock matches the module, which is
 * the one thing never in doubt. The test publishes an assessment to a volume
 * store, starts `ironclad serve` on a loopback port with a token file, and
 * asks it what the dashboard would ask. Needs python3 on the PATH.
 *
 * Run: npm --prefix dashboard test
 */

import test from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createApiSource, itemFromRow, recordFromRow } from "../public/api.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");
const PYTHON = process.env.PYTHON || "python3";
const TOKEN = "dashboard-test-token";
const STRANGER = "somebody-elses-token";

function python(args, opts = {}) {
  const result = spawnSync(PYTHON, ["-m", "ironclad.cli", ...args], {
    cwd: REPO_ROOT,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: REPO_ROOT, ...(opts.env || {}) },
  });
  assert.equal(result.status, 0, `${args.join(" ")}\n${result.stdout}\n${result.stderr}`);
  return result;
}

const sha256 = (text) => createHash("sha256").update(text).digest("hex");

/** Publish one assessment and start a server over it. */
async function startServer() {
  const work = mkdtempSync(path.join(tmpdir(), "ironclad-api-"));
  const store = path.join(work, "store");
  const out = path.join(work, "out");
  python([
    "assess", "--client", "Acme Corp", "--framework", "soc2", "--group", "standard",
    "--evidence-dir", path.join(REPO_ROOT, "examples", "evidence"), "--out", out,
  ]);
  python(["store", "publish", "--to", store, "--input", path.join(out, "assessment.json")]);

  const policies = path.join(work, "policies");
  mkdirSync(policies); // the server refuses to start without one
  const tokens = path.join(work, "tokens.json");
  writeFileSync(
    tokens,
    JSON.stringify({
      tokens: [
        { sha256: sha256(TOKEN), user_id: "viewer@acme.example", tenant_id: "acme-corp", roles: ["viewer"] },
        { sha256: sha256(STRANGER), user_id: "x@beta.example", tenant_id: "beta", roles: ["viewer"] },
      ],
    })
  );
  const port = 8800 + Math.floor(Math.random() * 500);
  const server = spawn(
    PYTHON,
    ["-m", "ironclad.cli", "serve", "--to", store, "--policy-root", policies,
     "--tokens", tokens, "--port", String(port), "--quiet"],
    { cwd: REPO_ROOT, env: { ...process.env, PYTHONPATH: REPO_ROOT }, stdio: ["ignore", "pipe", "pipe"] }
  );
  let stderr = "";
  server.stderr.on("data", (chunk) => {
    stderr += String(chunk);
  });
  const baseUrl = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 15000;
  let up = false;
  while (Date.now() < deadline && !up) {
    if (server.exitCode !== null) break;
    try {
      const r = await fetch(`${baseUrl}/api/v1/health`);
      up = r.ok;
    } catch {
      // not up yet
    }
    if (!up) await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (!up) {
    server.kill();
    throw new Error(`ironclad serve did not come up: ${stderr}`);
  }
  return {
    baseUrl,
    stop() {
      server.kill();
      rmSync(work, { recursive: true, force: true });
    },
  };
}

test("the API data source, against a real ironclad serve", async (t) => {
  const server = await startServer();
  const source = createApiSource({ baseUrl: server.baseUrl, token: TOKEN });
  t.after(() => server.stop());

  await t.test("the token names its principal", async () => {
    const me = await source.me();
    assert.equal(me.principal.tenant_id, "acme-corp");
    assert.ok(me.permissions.includes("assessment:read"));
  });

  await t.test("assessments arrive in the shape the card renders", async () => {
    const records = await source.listAssessments("acme-corp");
    assert.equal(records.length, 1);
    const [record] = records;
    assert.equal(record.framework.name, "SOC 2 Trust Service Criteria");
    assert.equal(typeof record.summary.readiness_score, "number");
    assert.equal(record.summary.total_controls, 33);
    assert.ok(Array.isArray(record.warnings));
    assert.equal(typeof record.failed_modules, "object");
    assert.ok(record.started_at.startsWith("20"));
  });

  await t.test("the remediation queue arrives with its evidence gap as a list", async () => {
    const items = await source.listRemediation("acme-corp", 5);
    assert.ok(items.length > 0 && items.length <= 5);
    assert.ok(Array.isArray(items[0].evidence_gap));
    assert.ok(items[0].control_id);
  });

  await t.test("another tenant's data is refused with the server's own words", async () => {
    await assert.rejects(source.listAssessments("beta"), /may not act on another tenant/);
  });

  await t.test("a wrong token is refused, never an empty list", async () => {
    const stranger = createApiSource({ baseUrl: server.baseUrl, token: "not-a-token" });
    await assert.rejects(stranger.listAssessments("acme-corp"), /HTTP 401|token/i);
  });

  await t.test("subscribe delivers both lists and stops when told", async () => {
    const seen = { assessments: 0, remediation: 0, errors: 0 };
    const stop = await new Promise((resolve, reject) => {
      const bail = setTimeout(() => reject(new Error("subscribe never delivered")), 5000);
      const halt = source.subscribe(
        "acme-corp",
        {
          onAssessments: (records) => {
            seen.assessments += records.length;
          },
          onRemediation: (items) => {
            seen.remediation += items.length;
            clearTimeout(bail);
            resolve(halt);
          },
          onError: () => {
            seen.errors += 1;
          },
        },
        50
      );
    });
    stop();
    const after = { ...seen };
    await new Promise((resolve) => setTimeout(resolve, 200));
    assert.deepEqual(seen, after, "polling continued after stop()");
    assert.equal(seen.errors, 0);
    assert.ok(seen.assessments >= 1 && seen.remediation >= 1);
  });

  await t.test("subscribe reports an error and carries on rather than dying", async () => {
    const errors = [];
    const stop = createApiSource({ baseUrl: server.baseUrl, token: TOKEN }).subscribe(
      "beta",
      { onError: (err) => errors.push(err.message) },
      30
    );
    await new Promise((resolve) => setTimeout(resolve, 200));
    stop();
    assert.ok(errors.length >= 2, `expected repeated polling errors, got ${errors.length}`);
    assert.match(errors[0], /another tenant/);
  });
});

test("the row adapters tolerate what a store hands back", async (t) => {
  await t.test("JSON text becomes values, and numbers are numbers", () => {
    const record = recordFromRow({
      assessment_id: "a", framework_id: "soc2-tsc", readiness_score: "46.50",
      total_controls: "33", warnings: '["one"]', failed_modules: '{"x":"boom"}', consensus: "null",
    });
    assert.equal(record.summary.readiness_score, 46.5);
    assert.equal(record.summary.total_controls, 33);
    assert.deepEqual(record.warnings, ["one"]);
    assert.deepEqual(record.failed_modules, { x: "boom" });
    assert.equal(record.consensus, null);
    assert.equal(record.framework.name, "soc2-tsc");
  });

  await t.test("broken JSON text falls back rather than throwing", () => {
    const record = recordFromRow({ warnings: "[broken", failed_modules: "{" });
    assert.deepEqual(record.warnings, []);
    assert.deepEqual(record.failed_modules, {});
    assert.deepEqual(itemFromRow({ evidence_gap: "nope" }).evidence_gap, []);
  });

  await t.test("a row that already carries values keeps them", () => {
    const record = recordFromRow({ warnings: ["a"], failed_modules: { m: "e" } });
    assert.deepEqual(record.warnings, ["a"]);
    assert.deepEqual(record.failed_modules, { m: "e" });
  });
});
