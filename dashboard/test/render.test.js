/**
 * The dashboard's rendering, tested without a browser.
 *
 * Everything here builds HTML by string concatenation from data that arrives
 * out of Firestore — which is to say, from whatever the ingest was given. The
 * only thing standing between a crafted assessment record and script running in
 * a client's compliance dashboard is that every interpolation is escaped, and
 * that was true of all but one of them: the "N of M evidence items are out of
 * date" line interpolated two record fields raw.
 *
 * So the rule under test is blunt: no field taken from a record reaches the
 * output unescaped. It is asserted field by field rather than by eye.
 *
 * Run: npm --prefix dashboard test
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  STATUS_LABEL,
  escapeHtml,
  renderAssessments,
  renderCatalog,
  renderRemediation,
  selectionToArgs,
} from "../public/app.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");

// The payload a crafted record would carry. Any of these reaching the output
// intact is a script running in somebody's dashboard.
const XSS = '<img src=x onerror="alert(1)">';
const BREAKOUT = '"><script>alert(1)</script>';

/**
 * Every way a raw payload could survive into rendered HTML.
 *
 * Escaped, the payload's own text still reads `onerror=` — as text, inside an
 * escaped tag, which is exactly what should happen. So what is asserted is that
 * no new element opens, no handler is live, and the payload never lands
 * verbatim: the three things that separate rendered text from executed script.
 */
function assertNoInjection(html, label) {
  assert.ok(!html.includes(XSS), `${label}: a record field landed verbatim`);
  assert.ok(!html.includes(BREAKOUT), `${label}: a record field landed verbatim`);
  assert.ok(!html.includes("<img"), `${label}: an element from the record survived`);
  assert.ok(!html.includes("<script"), `${label}: a script tag from the record survived`);
  assert.ok(!/\son\w+\s*=\s*["']/.test(html), `${label}: a live event handler survived`);
}

test("escapeHtml neutralises every character that matters", async (t) => {
  await t.test("the five", () => {
    assert.equal(escapeHtml(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
  });

  await t.test("a tag becomes text", () => {
    assert.equal(escapeHtml("<script>"), "&lt;script&gt;");
  });

  await t.test("an attribute cannot be broken out of", () => {
    // The quote is what turns class="pill x" into class="pill" onclick="...".
    assert.ok(!escapeHtml(BREAKOUT).includes('"'));
  });

  await t.test("absent values render as empty, not as the word", () => {
    assert.equal(escapeHtml(undefined), "");
    assert.equal(escapeHtml(null), "");
  });

  await t.test("a number survives", () => {
    assert.equal(escapeHtml(42), "42");
  });
});

test("the assessment list escapes every field it takes from a record", async (t) => {
  const hostile = {
    status: "completed",
    assessment_id: XSS,
    framework: { name: XSS },
    created_at: null,
    summary: {
      readiness_score: XSS,
      total_controls: 10,
      compliant: 1,
      partial: 1,
      gap: 8,
      accepted_risk: 0,
      stale_artifacts: XSS,
      evidence_artifacts: BREAKOUT,
    },
  };

  await t.test("a completed assessment", () => {
    const html = renderAssessments([hostile]);
    assertNoInjection(html, "completed");
  });

  await t.test("the stale-evidence line", () => {
    // The regression this file exists for: both counts were interpolated raw.
    const html = renderAssessments([hostile]);
    assert.ok(html.includes("evidence items are out of date"), "the line must render");
    assert.ok(!html.includes(XSS), "stale_artifacts reached the output unescaped");
    assert.ok(!html.includes(BREAKOUT), "evidence_artifacts reached the output unescaped");
  });

  await t.test("a queued assessment", () => {
    assertNoInjection(renderAssessments([{ ...hostile, status: "queued" }]), "queued");
  });

  await t.test("a running assessment", () => {
    assertNoInjection(renderAssessments([{ ...hostile, status: "running" }]), "running");
  });

  await t.test("a failed assessment, including the upstream error text", () => {
    const html = renderAssessments([
      { ...hostile, status: "failed", error: { message: XSS } },
    ]);
    assertNoInjection(html, "failed");
  });

  await t.test("a status the dashboard does not know", () => {
    assertNoInjection(renderAssessments([{ ...hostile, status: XSS }]), "unknown status");
  });

  await t.test("an empty list says so rather than rendering nothing", () => {
    assert.match(renderAssessments([]), /No assessments yet/);
  });

  await t.test("a record with no summary at all still renders", () => {
    // storeAssessmentResults writes summary: {} when a run failed early.
    const html = renderAssessments([{ status: "completed", framework: {}, summary: {} }]);
    assert.ok(html.includes("<article"));
  });
});

test("the remediation queue escapes every field it takes from a record", async (t) => {
  const hostile = {
    control_id: XSS,
    control_name: XSS,
    guidance: XSS,
    severity: BREAKOUT,
    due_date: "2026-01-01T00:00:00+00:00",
    evidence_gap: [XSS, BREAKOUT],
    status: "open",
  };

  await t.test("every column", () => {
    assertNoInjection(renderRemediation([hostile]), "remediation");
  });

  await t.test("the severity, which lands inside a class attribute", () => {
    const html = renderRemediation([hostile]);
    assert.ok(!html.includes(BREAKOUT), "severity broke out of the class attribute");
  });

  await t.test("an item with no guidance or evidence gap", () => {
    const html = renderRemediation([{ control_id: "CC6.1", control_name: "Access" }]);
    assert.ok(html.includes("CC6.1"));
  });

  await t.test("a past due date is marked overdue", () => {
    const html = renderRemediation([{ ...hostile, due_date: "2000-01-01T00:00:00+00:00" }]);
    assert.match(html, /overdue/);
  });

  await t.test("a completed item is not overdue whatever its date", () => {
    const html = renderRemediation([
      { control_id: "CC6.1", due_date: "2000-01-01T00:00:00+00:00", status: "complete" },
    ]);
    assert.ok(!html.includes("overdue"));
  });

  await t.test("an empty queue says so", () => {
    assert.match(renderRemediation([]), /Nothing outstanding/);
  });
});

test("the catalog renders from the engine, and escapes it anyway", async (t) => {
  const catalog = JSON.parse(
    readFileSync(path.join(REPO_ROOT, "dashboard", "public", "catalog.json"), "utf8")
  );

  await t.test("every capability the engine publishes becomes a checkbox", () => {
    const { modules } = renderCatalog(catalog);
    for (const module of catalog.modules) {
      assert.ok(modules.includes(`value="${module.name}"`), module.name);
    }
  });

  await t.test("every group becomes a preset, with deep pre-selected", () => {
    const { groups } = renderCatalog(catalog);
    for (const group of catalog.groups) {
      assert.ok(groups.includes(`value="${group}"`), group);
    }
    assert.match(groups, /value="deep" checked/);
  });

  await t.test("every framework becomes an option", () => {
    const { frameworks } = renderCatalog(catalog);
    for (const framework of catalog.frameworks) {
      assert.ok(frameworks.includes(`value="${framework.alias}"`), framework.alias);
    }
  });

  await t.test("every assessment type becomes an option, described", () => {
    const { assessmentTypes } = renderCatalog(catalog);
    for (const type of catalog.assessment_types) {
      assert.ok(assessmentTypes.includes(`value="${type.name}"`), type.name);
      assert.ok(assessmentTypes.includes(type.title), type.title);
    }
  });

  await t.test("a hostile catalog cannot inject", () => {
    // catalog.json is generated from the engine, but it is fetched over the
    // network like anything else.
    const parts = renderCatalog({
      modules: [{ name: XSS, description: XSS }],
      groups: [XSS],
      frameworks: [{ alias: XSS, name: XSS, version: XSS, control_count: XSS }],
      assessment_types: [{ name: XSS, title: XSS, description: BREAKOUT }],
    });
    for (const [name, html] of Object.entries(parts)) {
      assertNoInjection(html, name);
    }
  });

  await t.test("an empty catalog renders nothing rather than throwing", () => {
    const parts = renderCatalog({});
    assert.deepEqual(Object.values(parts), ["", "", "", ""]);
  });
});

test("the form selection maps onto the CLI's own resolution", async (t) => {
  /** The smallest thing that answers querySelector/querySelectorAll like a form. */
  function form({ modules = [], group = "", framework = "soc2", path = "gs://b/acme/", type = "full" }) {
    return {
      querySelector(selector) {
        if (selector === '[name="framework"]') return { value: framework };
        if (selector === '[name="evidence_path"]') return { value: path };
        if (selector === '[name="assessment_type"]') return { value: type };
        if (selector === 'input[name="group"]:checked') return group ? { value: group } : null;
        return null;
      },
      querySelectorAll(selector) {
        if (selector === 'input[name="module"]:checked') {
          return modules.map((value) => ({ value }));
        }
        return [];
      },
    };
  }

  await t.test("named capabilities win over a group preset", () => {
    // Exactly how the CLI resolves --modules against --group.
    const args = selectionToArgs(form({ modules: ["control_mapping"], group: "deep" }));
    assert.deepEqual(args.modules, ["control_mapping"]);
    assert.equal(args.group, undefined);
  });

  await t.test("a group is used when nothing is ticked", () => {
    const args = selectionToArgs(form({ group: "quick" }));
    assert.equal(args.group, "quick");
    assert.equal(args.modules, undefined);
  });

  await t.test("neither is sent when neither is chosen", () => {
    const args = selectionToArgs(form({}));
    assert.equal(args.group, undefined);
    assert.equal(args.modules, undefined);
  });

  await t.test("the evidence path is trimmed", () => {
    assert.equal(selectionToArgs(form({ path: "  gs://b/acme/  " })).evidence_path, "gs://b/acme/");
  });

  await t.test("the assessment type is carried through", () => {
    assert.equal(selectionToArgs(form({ type: "gap-only" })).assessment_type, "gap-only");
  });
});

test("the status labels are client language, not engine language", async (t) => {
  await t.test("no raw engine status reaches a reader", () => {
    assert.equal(STATUS_LABEL.compliant, "Met");
    assert.equal(STATUS_LABEL.gap, "Not met");
    assert.equal(STATUS_LABEL.accepted_risk, "Risk accepted");
    assert.equal(STATUS_LABEL.pending, "Not assessed");
  });

  await t.test("no underlying tool is named anywhere in the dashboard module", () => {
    const source = readFileSync(
      path.join(REPO_ROOT, "dashboard", "public", "app.js"),
      "utf8"
    ).toLowerCase();
    for (const name of ["zap", "nuclei", "wazuh", "prowler", "puppeteer", "openai", "groq"]) {
      assert.ok(!source.includes(name), `the dashboard names ${name}`);
    }
  });
});
