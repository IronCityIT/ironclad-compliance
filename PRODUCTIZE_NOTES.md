# Productization notes — Ironclad Compliance

The required code review, the plan that came out of it, and the decisions worth
arguing with. Written against the repository as it stood at `8246f45`.

---

## 1. Scope tier

`ironclad-compliance` appears in none of the three tiers in `CLAUDE.md`. The
fallback rule is unambiguous — treat an unlisted repo as HANDS OFF and ask.
Asked before touching anything, and directed to work under the **REVIEW ONLY**
posture: branch, build, run the gates, open a PR, and stop.

So: nothing merged, nothing deployed, no `workflow_dispatch` fired. `STATUS.md`
carries the exact next commands and the decisions that are Bill's to make.

---

## 2. Code review of the existing implementation

Four Python scripts, two workflows, one framework file, one dashboard-less
architecture diagram in the README. Roughly 700 lines. The shape was right —
the README described the correct ICIT architecture — but almost nothing in the
pipeline actually did what the README said it did.

### 2.1 The AI consensus integration was broken end to end

`compliance-assessment.yml` called `consensus-engine` like this:

```yaml
with:
  findings_json: ${{ needs.assess-controls.outputs.findings_json }}   # raw JSON
...
CONSENSUS_SEVERITY="${{ needs.ai-consensus.outputs.consensus_severity }}"
CONFIDENCE="${{ needs.ai-consensus.outputs.confidence_percent }}"
```

Reading `/root/work/consensus-engine/.github/workflows/analyze.yml`, which is
what `CLAUDE.md` requires before wiring to it, the real contract is:

- `findings_json` is **base64-encoded JSON**. Raw JSON there is analysed as
  nothing.
- The workflow declares **exactly one output**, `consensus_b64`. Neither
  `consensus_severity` nor `confidence_percent` exists.

Both halves were wrong, so every assessment this repository has ever produced
carried an empty AI severity and an empty confidence into the client's report,
and the report rendered them as `PENDING` / `N/A` without anyone noticing. The
findings were never analysed at all.

Fixed: the CLI writes `findings.b64` and the report job decodes `consensus_b64`
through `merge_consensus()`, which handles the valid, empty and undecodable
cases distinctly. The empty case is not hypothetical — the engine documents that
its output is empty when analysis fails.

It also now passes `post_to_api: false` explicitly. The engine's own comments
say a caller handling regulated data should store results itself rather than
POST to the legacy QNAP ingest API, which is UPDATE-ONLY and 404s for any scan
it did not create. Compliance evidence is exactly that caller.

### 2.2 A failed evidence download looked like a catastrophic client result

```yaml
gsutil -m cp -r "${{ inputs.evidence_path }}*" evidence/ || true
```

The `|| true` meant a failed fetch left an empty directory, the assessment ran
against nothing, and every control reported as a gap. A client would have
received a report saying they meet none of the Trust Service Criteria because a
bucket path had a typo in it. That is the single worst failure mode this product
has, and it was one shell operator.

Fixed: the fetch fails the run, and a zero-file result is an explicit error. In
addition, `evidence_inventory` raises a `critical` finding when it is handed an
empty evidence set, so the report says "no evidence was submitted" rather than
"33 gaps" even if some future path gets there.

### 2.3 The framework update checker could not return false

```python
update_phrases = ["new version", "updated", "revision", "latest"]
for phrase in update_phrases:
    if phrase in page_text:
        result["update_detected"] = True
```

Every standards-body page on earth contains the word "updated". The check fired
on every run, opened a quarterly PR that always said the same thing, and would
have been ignored within two quarters — at which point a real revision would
also be ignored.

Rewritten around two signals that can actually be false: a version token on the
page higher than the one tracked in `framework-versions.json`, and a change in
the page's content fingerprint since the last run. Fingerprints are committed
with the PR, so the next run compares against what was really seen. Dropping
BeautifulSoup for `html.parser` removed a dependency on the way past.

### 2.4 Extraction failures were indistinguishable from empty documents

```python
except Exception:
    return f"[PDF: {file_path.name}]"
```

A corrupt PDF returned a placeholder string containing no control keywords —
byte-for-byte the same signal as a PDF full of irrelevant content. A broken
document silently became a control gap.

Fixed: extraction returns an `Extraction` carrying either text or a reason, and
the reason becomes an `info` finding naming the file. Also now reads `.docx`
tables, which the original skipped entirely — access matrices and review logs
are the evidence most likely to live in a table.

### 2.5 The matcher held every control to the same absolute bar

```python
matches = sum(1 for kw in control_keywords if kw in text_lower)
if matches > 2:
```

Two problems. The threshold was absolute, so a control offering three keywords
and one offering twelve needed the same two hits — the sparse control was four
times easier to satisfy. And `kw in text_lower` is substring matching: a control
expecting a "register" was satisfied by any document containing "registers", and
more damagingly `"act"` matched inside `"contract"`, `"audit"` inside
`"auditorium"`. An unrelated control read as evidenced when it was a gap.

The substring problem was found by the test suite, not by reading. Fixed:
scoring is a *share* of the control's own terms, and matching is on whole words
with light inflection stripping, so `registers` still matches `register` and
`contract` no longer matches `act`.

### 2.6 Nothing could ever be more than "potential"

Every status the original produced was `potential_compliant`,
`potential_partial` or `potential_gap`, deferring the real verdict to the AI —
which, per §2.1, was never running. So the product had no opinion about
anything. It produced a document that looked like a compliance assessment and
asserted nothing.

The engine now reaches a verdict from the evidence, deterministically, and
carries AI commentary alongside it as advisory text. The readiness score is
computed from the verdicts alone.

### 2.7 Firestore was written from two places

`store_results.py` wrote Firestore directly from the runner, which meant the
runner needed Firestore credentials and the multi-tenant partitioning rule
existed both there and (per the ICIT standard architecture) in the Cloud
Function. Two writers, one of which nobody was looking at.

Fixed: the script POSTs to `storeAssessmentResults`, which owns the write. It
uses stdlib `urllib`, so that job no longer installs `firebase-admin`,
`google-cloud-firestore` and `google-cloud-storage` to write one document.

### 2.8 What was missing entirely

Three of the four advertised frameworks (`nist-csf-2.0.json`, `pci-dss-4.0.json`,
`hipaa.json` were all referenced by `framework-versions.json` and offered as
workflow choices — none existed, so choosing any of them failed validation). No
crosswalk data behind `docs/control-mapping.md`, which was a hand-written table
of five rows. No remediation model, no exceptions, no audit trail, no tenancy,
no RBAC, no dashboard, no Cloud Functions, no Firestore rules, no tests, no
Jenkins.

---

## 3. Plan, in the order it was built

1. Domain model — controls, evidence, assessment, remediation, exceptions,
   audit, tenancy. Pure data and pure rules, no I/O.
2. Framework content — NIST CSF 2.0 (43), PCI DSS 4.0 (27), HIPAA (23) — plus
   94 crosswalk mappings.
3. Ingestion contract v1.0, extractors, collectors.
4. Capabilities, registry, engine.
5. Reports and exports.
6. Tenancy, RBAC, service API, CLI.
7. Workflow fixes, Jenkins, Cloud Functions, Firestore rules, dashboard.
8. Tests, then documentation.

---

## 4. Adapting the ICIT module framework

`CLAUDE.md` mandates the shared `module_framework/` pattern — one `ScanModule`
per capability, `--modules` / `--group` selection, `registry.catalog()` driving
the dashboard, `targets.py` for input shapes.

Six of those seven things port directly and were adopted as written. One does
not: `targets.py` parses IPs, CIDRs, URLs and hostnames, and a compliance
assessment has no network target. Its equivalent input is a tenant's evidence
corpus, and forcing that through a CIDR parser would be cargo-culting the letter
of the standard against its purpose.

What was kept, deliberately identically:

- one capability per file in `modules/`, discovered by a registry
- `--modules a,b,c` and `--group quick|standard|deep`
- a `name`, a client-safe `description`, and group membership on each
- `registry.catalog()` as the one source the CLI and dashboard both render
- the `Finding` shape — `module, target, severity, title, detail, evidence` —
  with severity validated against the same five-value vocabulary, so findings
  flow to `consensus-engine` in the shape every other ICIT product emits

What was added: `requires`, and a registry that topologically orders the run.
The scanning tools' modules are independent; these are not — freshness cannot
downgrade a verdict that control mapping has not set yet. Declaring the
dependency beat relying on alphabetical order happening to come out right, which
it did, by luck, until `remediation_plan` needed to run after `exception_review`.

`target` on a Finding is the control id. That is this product's equivalent of a
host or a URL.

---

## 5. Decisions worth arguing with

**Two independent items before a control reads as met.** One document is a
claim; corroboration is what an auditor asks for. This makes early client
reports look worse than the tools they replace. It is deliberate, and it is a
commercial call as much as a technical one.

**Evidence expires, by class, whether or not anyone said so.** 90 days for an
access review, 365 for a policy, 30 for a scan. These are ICIT policy numbers,
not standard ones, and they are the most likely thing to need arguing with a
real auditor. They live in one dict: `ironclad/model/evidence.py::VALIDITY_DAYS`.

**AI commentary never moves the readiness score.** A number that changes because
a model felt differently today is worthless to an auditor. The score is
computed from the control verdicts and is reproducible from the exported control
register alone.

**An accepted risk earns half credit, not zero.** An organisation that knows
about a gap and has formally signed for it is in a materially better position
than one with an unknown gap. It is not a working control either.

**A risk acceptance needs a second approver and an expiry.** Both are enforced
in the model rather than the UI, so they hold no matter which surface calls in.
An auditor who cannot see a second signature and an end date does not accept the
acceptance.

**An auditor role cannot approve an exception.** An auditor signing off on the
risk they are auditing is the exact conflict the role exists to prevent, so
`exception:approve` is absent from that role even though it reads everything
else.

**The pipeline's own identity cannot approve an exception either.** Accepting
risk is a human decision; automation must never sign for it.

**The auditor package contains references and checksums, never evidence bytes.**
The artifacts stay in the client's storage. The package's `README.txt` says so
explicitly, because the failure mode is somebody assuming the evidence travelled
with it.

**Crosswalk relationships are directional and the inverse is computed.** The
inverse of a `subset` is a `superset`. Getting that backwards would let a narrow
control claim to cover a broad one — the whole risk of an automated crosswalk. A
`related` mapping never carries a verdict at all.

---

## 6. Deliberate limits

**The crosswalks are ICIT's reading of the control text, not a published
mapping.** 94 mappings, hand-authored, each with a note saying why. Every edge
is checked by a test to point at a control that exists in both frameworks, but
"the edge is well-formed" is not "the mapping is correct". A projection is
labelled as a projection everywhere it appears and states how many controls
still need direct review.

**The framework control sets are abridged.** NIST CSF 2.0 has 106 subcategories;
43 are here, chosen for the ones a mid-market client is assessed on. PCI DSS 4.0
has some 300 sub-requirements; 27 requirement-level controls are here. The
control text is faithful, the coverage is not exhaustive, and a client should be
told which.

**Points-of-focus coverage is a keyword heuristic.** It separates a compliant
verdict from a partial one and is deliberately crude — it is a readiness signal
for a human reviewer, not an audit opinion.

**`InMemoryStore` is the reference store.** The Firestore-backed implementation
of the `Store` protocol is the Cloud Function; the service layer has no
production persistence of its own yet. Authorization and workflow rules live in
the service rather than the store, so they hold whichever backing is in use.

---

## 7. Secrets

Referenced by name only. No value is written anywhere in this repository, and a
grep for hardcoded credential patterns returns nothing.

Approved and used: `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`
(passed through to `consensus-engine`), `GCP_SA_KEY`, `GCS_BUCKET`,
`FIREBASE_PROJECT_ID`, `GITHUB_TOKEN`.

**Not on the approved list, and therefore not invented — HALT items:**

- `GITHUB_DISPATCH_TOKEN` — a GitHub token with `actions:write` on
  `IronCityIT/ironclad-compliance`, needed by `functions/trigger.js` so the
  dashboard can start an assessment. Referenced by name; the function will not
  deploy until it exists in Secret Manager (us-east5). Only the dashboard's
  "Start assessment" button depends on it.
- `STORE_RESULTS_URL` and `INGEST_API_KEY` — the ingest endpoint and its key.
  `store_results.py` prints the record instead of posting when the endpoint is
  unset, so the pipeline runs without them; it simply does not publish.
- Jenkins credential ids `ironclad-store-results-url` and
  `ironclad-ingest-api-key` do not exist on any agent yet.

---

## 8. What has not been proven

Set out in full in `STATUS.md`. In short: everything that runs locally has been
run, repeatedly. Nothing that needs a GitHub runner, a Jenkins agent or a GCP
project has run at all. The consensus contract fix in §2.1 is the most valuable
untested path — CI on the PR is the first time it executes for real.

The security gate could not run on this machine and is **not** reported as
green. `bandit` will not install into an externally-managed Python (PEP 668) and
`pip-audit` aborts on an unrelated package installed on the host. A manual
review was done in its place and is recorded in `STATUS.md`; it is not a
substitute for the tools, and CI in a clean container is the first real result.
