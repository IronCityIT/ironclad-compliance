# Productization notes — Ironclad Compliance

The required code review, the plan that came out of it, and the decisions worth
arguing with. §§1–7 were written against the repository as it stood at `8246f45`
and describe what was found there; §§8–11 record what has been found since, each
against the code at the time. Verified against `ad2d57a` — where a claim in the
earlier sections no longer holds it is struck through and pointed at what
replaced it, rather than quietly rewritten, because the review is a record of
what was true when as much as a description of what is true now.

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

**~~`InMemoryStore` is the reference store.~~ Superseded — §11.5–11.6 and
`HANDOFF.md` §13.** This
said the Firestore-backed implementation of the `Store` protocol was the Cloud
Function and the service layer had no production persistence of its own. Both
halves are now false: Firestore is retired from the target architecture, and
`ironclad/store/` holds a persistence seam with a NAS-volume and a MariaDB
backend, both exercised against real storage. The single `Store` protocol has
split in two — `PolicyRecords` for a client's determinations, `ResultStore` for
assessments — because no shipped implementation could satisfy the combined one.

What still holds, and was the point of the original paragraph: authorization and
workflow rules live in the service rather than the store, so they hold whichever
backing is in use.

---

## 7. Secrets

Referenced by name only. No value is written anywhere in this repository, and a
grep for hardcoded credential patterns returns nothing.

Approved and used: `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`
(passed through to `consensus-engine`), `GITHUB_TOKEN`.

Retired with the GCP path: `GCP_SA_KEY`, `GCS_BUCKET`, `FIREBASE_PROJECT_ID`.
They remain referenced only by the fallback branches that run when no NAS volume
or store is configured, and go with `functions/` when the transport is decided.

**Not on the approved list, and therefore not invented — HALT items:**

- `GITHUB_DISPATCH_TOKEN` — a GitHub token with `actions:write` on
  `IronCityIT/ironclad-compliance`, needed by `functions/trigger.js` so the
  dashboard can start an assessment. Referenced by name; the function will not
  deploy until it exists in Secret Manager (us-east5). Only the dashboard's
  "Start assessment" button depends on it.
- `STORE_RESULTS_URL` and `INGEST_API_KEY` — the retired ingest endpoint and its
  key. `store_results.py` prints the record instead of posting when the endpoint
  is unset, so the pipeline runs without them; it simply does not publish. The
  key is no longer optional at the far end: an unset `INGEST_API_KEY` makes the
  ingest refuse every write rather than accept unauthenticated ones (§8.1), and
  `store_results.py` says so before it posts rather than leaving it to be
  inferred from a 503.
- `IRONCLAD_STORE`, `IRONCLAD_EVIDENCE_ROOT`, `IRONCLAD_ARTIFACTS` — the target
  architecture's three: where a result is written, where a tenant's evidence is
  read from, and where the deliverables land. Referenced by name only. The
  workflow skips publishing when the store is unset and **fails outright** when
  no evidence source is configured, because an unconfigured evidence source must
  never become an assessment of nothing. None is on the approved ICIT list.
- Jenkins credential ids `ironclad-store-results-url` and
  `ironclad-ingest-api-key` do not exist on any agent yet.

---

## 8. The Cloud Functions had no tests, and three defects

Added after the first PR was open, when the question "what is the highest-value
thing here that nobody has looked at" had an obvious answer: `functions/`. Three
files and 558 lines *as they stood then*, carrying the code that decides which
tenant a write lands in — and the whole gate on them was `node --check`, a
syntax check. (They are 717 lines now; `core.js` is the difference.) `CLAUDE.md` says
"Never expose one client's data path to another"; nothing was verifying it.

They could not be tested as written: each file opens a Firestore connection at
require time, so importing one needs a live project. The decisions moved into
`functions/core.js`, which imports nothing, and `functions/test` covers every
branch on the runtime's own test runner — no install step, so it runs here, in
CI, and on a Jenkins agent that has node.

### 8.1 The ingest failed open

```js
function keyMatches(supplied, expected) {
  if (!expected) return true; // no key configured: the endpoint is open by config
```

`storeAssessmentResults` takes `client_id` from the request body and writes to
`clients/{client_id}/...`. So a deploy where `INGEST_API_KEY` was never bound —
a missing Secret Manager binding, a typo in the env var name — published an
unauthenticated endpoint that could create or overwrite an assessment record in
any tenant, and the only sign would have been that it worked.

A misconfiguration must degrade to refusing work, never to accepting anyone's.
An unset key is now a 503 and a logged reason. `scripts/store_results.py` says
so before it posts, rather than leaving the operator to infer it from the
status code.

### 8.2 The evidence-path check was a containment test

```js
if (!evidencePath.startsWith(`gs://`) || !evidencePath.includes(`/${clientId}/`))
```

`gs://any-bucket/acme/../beta/` contains `/acme/`. It passes, and it points the
run at beta's evidence while filing the result under acme. Also passing:
`gs://bucket/beta/acme/`, which is beta's layout, not acme's.

The tenant prefix is structural, so it is now checked structurally — the client
id must be the *first* object segment, and no segment may be empty, `.` or `..`.
The refusal names the reason, because "invalid path" against a path that looks
right is the kind of message that gets worked around rather than fixed.

### 8.3 Payload-supplied ids went into Firestore paths unchecked

`assessment_id`, remediation `item_id` and audit `event_id` were `.trim()`ed and
handed to `.doc()`. A value containing `/` addresses a different collection:
`assessments/a/b/c` rather than `assessments/a`. `firestore.rules` matches
`/clients/{c}/assessments/{a}` and closes everything else, so the record would
have been written where nothing can ever read it — a silent data loss that looks
like a successful store, complete with a 200.

Ids are checked now. The assessment id is *refused* rather than rewritten: it is
the record's identity, and a sanitized substitute files the result under an id
nobody asked for, which makes the next run of the same assessment create a
second record instead of updating the first. Item and event ids are skipped and
counted, and the count comes back in the response, so a pipeline that lost half
its remediation items can see that it did.

### 8.4 The slug existed twice

`toClientId` was copy-pasted into `index.js` and `exchange.js`, and both had to
match `ironclad.ids.slugify` in Python for a client's results to land where their
dashboard reads. Nothing checked any of the three against each other. One
implementation now, and `tests/test_tenancy.py` runs the JavaScript against the
Python over a shared table of cases.

---

## 9. Two counts were the dashboard's only unescaped fields

Same question as §8, asked of the last untested client-facing surface. The
dashboard builds every element by string concatenation from data that arrived
out of Firestore — which is to say, from whatever the ingest was given — so
escaping every interpolation is the entire defence.

It held everywhere a reviewer looks first: the framework name, the control name,
the guidance text, the error message from a failed run. It failed in the two
places nobody looks, because both are counts and a count is obviously a number:

```js
${summary.stale_artifacts} of ${summary.evidence_artifacts} evidence items…
${f.control_count} controls
```

Neither is guaranteed to be a number. `storeAssessmentResults` copies
`body.summary` verbatim from the payload, and `catalog.json` is fetched over the
network like anything else. A crafted or corrupted record put script into a
client's compliance dashboard — in the banner that warns them their evidence is
stale, which is a place a client is being asked to trust.

Both are escaped now, and `dashboard/test` asserts it field by field over every
render path: all three status branches, a status the dashboard does not know, a
record with no summary at all, and a hostile catalog. The assertion is that no
new element opens, no event handler is live, and no payload lands verbatim —
escaped text that still reads `onerror=` is the correct outcome, not a failure,
and writing the check the obvious way got that wrong first.

The remaining raw interpolations are literals and computed numbers. They say so
in a comment now, so the next reader does not have to re-derive it.

---

## 10. The rules were read carefully and never executed

`firestore.rules` is where the product's central promise is actually enforced:
a client sees their own compliance position and nobody else's. It had been
written carefully, reviewed, and never run — and for an access-control policy
that is the same as not having been checked, because a rule that denies
everything and a rule that allows everything both read plausibly on the page.

`tests/rules` starts the Firestore emulator, seeds two tenants **with the rules
suspended** — so a seeding mistake cannot be mistaken for a rule that permits a
write — and then drives the real client SDK as a signed-in user of each, with
the claims `functions/exchange.js` mints. 53 cases, both directions: a tenant
reads its own record and an auditor sees the evidence index; a tenant cannot
reach another tenant by any of seven paths, cannot list the `clients`
collection, and no role can write anywhere at all.

A suite of denials that all pass proves nothing on its own — rules that deny
everything would pass it too. So the positives are asserted as well, and the
whole thing was checked by mutation: replacing `ownsTenant` with `return true`
fails 17 cases. The suite is testing the partition, not agreeing with it.

Two cases are there for reasons worth keeping:

- **Listing `clients`.** `allow read` covers `get` and `list`, and a list is
  evaluated against the query rather than the documents. A root collection query
  is the one request that would undo the whole partition in a single call.
- **An assessment id containing a slash.** `assessments/a/b/c` matches no rule
  and is therefore closed — which is exactly the silent loss the ingest's id
  check in §8.3 prevents, demonstrated at the layer where it would have bitten.

This is the only gate needing an installed toolchain, so it is its own CI job.

---

## 11. Eight more defects, and how each was found

Everything in §2 came out of reading the original code. Everything here came out
of **running something against reality** — a live page, a real database, two
entry points side by side. That difference is the most useful thing in this
document: after §2 the reading was done, and the remaining defects were all
invisible to it.

### 11.1 The update checker was blind on three of four sources

`meta` and `link` were in the HTML extractor's skip set. Both are void elements —
`<meta charset="utf-8">` has no closing tag — so the skip counter went up on the
first one in `<head>` and nothing ever brought it down. Every text node after it
was discarded.

SOC 2, PCI DSS and HIPAA were being fingerprinted as the empty string, compared
against the empty string, and reported "unchanged" with confidence. The checker
could not have detected a change to three of the four frameworks it watches,
ever. NIST worked — which is why this looked fine — because that page
self-closes its meta tags and HTMLParser synthesises the end tag.

Found by fetching the four real pages and printing the character counts: 0,
5,368, 0, 0. Nothing in the code says "returns empty for most inputs".

**The first working run found a real update: PCI DSS 4.0.1 against the 4.0 this
repository ships.** That is an open product task in `HANDOFF.md`, not something
to fix automatically — the checker never transcribes a regulator's wording.

### 11.2 An empty response read as a content change

A WAF interstitial, a CDN error or an empty 200 produced a fingerprint of
nothing, which differs from the stored one. So the checker reported a change
*and* recorded the digest of nothing as the new baseline — poisoning it, so the
next run compared the real page against nothing and reported a change again. Two
false pull requests from one blip.

A response yielding under 500 characters of visible text is "unchecked" now and
leaves the recorded fingerprint alone. The floor is set against the real
sources, which yield 5,368 to 9,139 characters.

### 11.3 A policy file that validated could fail to load

`policy_from_document` replayed a rejection without submitting the exception
first, and the state machine correctly refuses draft → rejected. So a policy
carrying `"status": "rejected"` passed `ironclad validate --policy` and then
raised at assessment time. Validation and loading disagreeing is the worst of
both: the check that exists to catch a bad file said the file was fine.

An expired acceptance was worse in a quieter way — nothing replayed it, so it
came out as a draft and the file's own status was silently discarded.

Found by asking what every status a policy may legitimately carry actually does,
and running all six.

### 11.4 The legacy wrapper ignored the tenant policy

`scripts/assess_controls.py` had no `--policy` flag and did not look for one
beside the evidence. A client's scope exclusions and risk acceptances were
silently not applied: a control the client had formally accepted, with a written
justification and a named approver, came back as a gap.

`STATUS.md` promised anything that called these scripts still worked. Nothing
verified it — none of the four had a test. Found by running both entry points
over the same evidence and comparing verdicts, which is now the test.

### 11.5 MariaDB truncated silently, and the projection truncated first

The first CI run against a real MariaDB 10.5 found that an over-long value is
shortened and reported as stored unless a strict `sql_mode` is set. Adding one
did not fix it, which was the more interesting result: `rows.py` truncated every
bounded value itself, so the database never saw anything too long. The same
silent truncation applied to the volume store, which has no column widths at all.

Nothing is truncated now — an over-long value is refused with its table, column
and length named — and the bounds are parsed from `schema.sql` rather than
declared twice.

### 11.6 A client's second assessment could not be stored

Remediation item ids are deterministic on (tenant, control), so the same control
produces the same id in every assessment of that client. Keyed globally, the
second run collided with the first. The key is `(assessment_id, item_id)` now,
and `list_remediation` returns the latest assessment's queue rather than every
item ever raised — one control outstanding in two runs is one piece of work.

Both found by the persistence job's first run against a real server. Neither
would have appeared against a mock, which is the argument for testing a database
with a database.

### 11.7 The ingestion contract had drifted from the engine

A bare `scan` is a 30-day evidence class in the code and `docs/ingestion-contract.md`
did not list it, so a client submitting `Q3 scan.pdf` got a 30-day clock the
contract never mentioned. Every other documented rule was checked against the
validator and holds.

The freshness table is checked against `VALIDITY_DAYS` by a test now, verified by
breaking it on purpose. A contract nobody checks is prose.

### 11.8 Two pipelines that were meant to be identical were not

`ci.yml` opens by saying it runs the same gates as the Jenkins pipeline. CI
gained the persistence, rules and end-to-end gates and `Jenkinsfile` was never
told. A pipeline that silently does not know a gate exists is worse than one
that cannot run it, because only the second says so.

### 11.9 What this pattern means for whoever picks this up

Four of the five modules whose coverage was raised this session turned up a real
defect; `freshness_check` did not. A coverage gap is not evidence of a bug, and
saying so matters as much as the four that were.

The defects that remained after §2 were not findable by reading. They needed the
real page fetched, the real database written to, the two entry points run side
by side, the document checked against the constant. When the next gap has to be
chosen, prefer the check that executes something over the one that inspects it.

---

## 12. What has not been proven

Set out in full in `STATUS.md` and `HANDOFF.md` §16. This section said, when it
was written, that nothing needing a GitHub runner, a Jenkins agent or a GCP
project had run at all. That is no longer the shape of it, and the correction is
worth more than the edit:

**A GitHub runner has run a great deal.** CI executes six jobs on every push,
including the store against a real MariaDB 10.5 and the whole path end to end
against both a database and a volume. The consensus contract fix in §2.1 has
been exercised by every CI run since.

**A Jenkins agent still has not.** The pipeline is syntactically balanced and
its gates are the ones run here by hand, and it has never executed. Three of its
gates will report UNAVAILABLE on the current agent image, which is accurate
rather than a defect (§11.8).

**No GCP project has run anything, and none now should.** Firebase, Firestore
and GCP product storage are retired from the target architecture. Nothing was
ever deployed, so the retirement costs no client data — which is the one piece
of luck in the changeover and will not come again.

**The NAS has not been written to.** MariaDB 10.5.8 answers on
192.168.1.177:3306 and no credential exists; the transport from a GitHub-hosted
runner to an RFC1918 address is undecided and is what gates the rest of the
migration.

`ci.yml` originally had no security gate at all, despite `CLAUDE.md` listing one
and the Jenkins pipeline running it. That was fixed rather than explained away:
CI now audits the declared dependencies, runs static analysis, and fails on a
credential-shaped literal or a tool name reaching a client-facing surface. All
four are green.

Adding it earned its keep immediately. `bandit`'s first real run — it will not
install on the build machine under PEP 668, so CI was the first place it ran —
found that `scripts/store_results.py` handed an operator-supplied endpoint to
`urllib.request.urlopen`, which honours `file://`. A mistyped or tampered
endpoint would have read a local file and reported its contents back as an HTTP
response. Rewriting the publish step onto `http.client`, which speaks only HTTP,
removed the risk structurally rather than checking for it — and surfaced a second
bug while it was open: the old code inferred success from "no exception raised",
so a 204 or a 302 from a misconfigured ingest would have been recorded as a
stored result.

---

## 13. The HTTP surface, and what its first run found

Session of 2026-09-12. `HANDOFF.md` §15 listed a `ComplianceService` HTTP
surface as the highest-value item that needed no decision and no credential:
migration stage 5 — replacing the dashboard's Firestore reads — cannot start
without a backend to read from. It exists now as `ironclad serve`
(`ironclad/api/http.py`, `docs/http-api.md`), standard library only, tested
against a real socket by `tests/test_http.py`.

Four defects, all found by the tests on their first run, none by reading:

### 13.1 Every write route was unreachable

The router walked the route table and answered 405 on the first regex that
matched the path if the verb differed. `GET /exceptions` is registered before
`POST /exceptions`, so every POST to a path that also had a GET was refused
before its own registration was reached. The first test that raised an
acceptance found it.

### 13.2 A refused write created the victim's directory

`service_for(tenant, writing=True)` made `<policy-root>/<tenant>/` before the
service had authorized anything, so a stranger's 403 left a directory named for
the tenant they were probing. The policy store now creates the directory on its
own first write, which is after authorization by construction. Asserted: the
stranger's refused POST leaves the policy root untouched.

### 13.3 The body could name the requester

`ComplianceService.request_exception` takes `requested_by` from the request
because the CLI passes the actor as a flag. Over HTTP that meant a compliance
manager could write a colleague's name into the body, raise the acceptance
"for" them, and approve it themselves — the model's second-person rule compares
approver to `requested_by`, and `requested_by` was whatever the caller said.
The transport now sets it to the token's user, whatever the body says. The
service is unchanged: the CLI's contract is right for the CLI, where the actor
is already the operator's own claim.

### 13.4 An unread body became the next request

A body over the limit is refused without being read. On a kept-alive HTTP/1.1
connection the server then read the 64 KiB of unread body as the next request
line, answered `414 URI Too Long` to a client that had already gone, and logged
a broken pipe from its own thread — visible only because the test run printed a
traceback that no assertion had asked for. The refusal now closes the
connection.

### 13.5 The white-label gate read four files

Not the HTTP surface, but found the same day and the same way. The gate
enforcing "no tool named on a client surface" checked an enumerated list of
four files. A fifth file dropped into `dashboard/public/` — served to every
visitor — was not read. It is now one script scanning the surfaces as
directories, shared by CI, `gates.sh` and the Jenkinsfile (which had no
white-label check at all), and the dashboard test scans every served file.
Verified both ways: green on the committed tree, red on the working tree — see
§14.

---

## 14. Uncommitted work in the tree, reviewed and left alone

At the start of this session the working tree carried changes not made by any
recorded session and not committed: a rebranded `dashboard/public/index.html`,
`dashboard/public/demo.js`, `dashboard/public/sage-demo.json`,
`dashboard/public/ironclad-mark.svg`, a `tenants/sage-spine-pain-and-nerve-center/`
baseline and `automation/sage/`. File times are 2026-09-10 20:04–20:16, after
the last commit that day. They were not committed, deleted or edited here —
they are someone else's work in progress — but they were read and checked
against the engine, and this is what that found. Each item is a blocker for
committing them as they stand.

1. **A tool name on a client surface.** `sage-demo.json` lists "Wazuh SIEM" as
   an asset and is served from `dashboard/public/`. `CLAUDE.md`'s white-label
   rule forbids it; the hardened gate (§13.5) now fails on it, by name. The
   tenant baseline under `tenants/` names the same product, which is internal
   and allowed, but the dashboard copy is not.
2. **The demo renders for every tenant, unauthenticated.** `index.html` loads
   `demo.js` unconditionally, before sign-in, and it fills six sections with a
   named healthcare provider's posture, risk register, vendors and assets. Any
   visitor, and every other client who signs in, sees Sage's name and its
   (demo) risk data. The multi-tenant rule is no cross-tenant leakage; a client
   name is client data. A demo needs to be gated — a `?demo` flag, a demo
   tenant, or a separate page — and `sage-demo.json` should not sit in the
   publicly served directory at all.
3. **A framework id the engine does not know.** `tenant.json` lists
   `"nist-csf-2.0"`; the loader's aliases are `soc2`, `nist-csf`, `pci-dss`,
   `hipaa`. A request naming `nist-csf-2.0` is refused with "not one of".
4. **The tenant files have no consumer.** Nothing in the engine reads
   `tenants/<slug>/tenant.json`, `scope.json`, `integrations.json`,
   `risk-register.json` or `automation.json`. The slug is right —
   `slugify("Sage Spine Pain and Nerve Center")` produces exactly that
   directory name — but the files describe a schema (assets, vendors, BAAs,
   risk register) the product does not have. `automation/sage/README.md`
   describes an "upstream native GRC engine" with a REST API, MCP and Kafka;
   that is not this product either. Whether this is a design brief for a
   different system or a spec for extending this one is a question for whoever
   wrote it.
5. **Escaping is right.** `demo.js` escapes every field before `innerHTML`, so
   the demo data cannot inject script. Worth saying, since two count fields in
   the real dashboard could once (§9).
6. **The rest of the dashboard tests still pass** with the modified
   `index.html`, and every JSON file validates.

None of this is a judgement on the demo's purpose. It is that the tree cannot
be committed in this state without breaking a gate and a rule, and the gate
that would have let it through has been fixed first.

---

## 15. The product workflow ran for the first time, and what it found

2026-09-12. The `Compliance Assessment` workflow had never executed: without an
evidence secret it stops at "Refuse to assess with no evidence source", so no
run had reached the consensus-engine call — the contract fix that is the reason
this branch exists — or the report stage. A `dry_run` input now assesses the
synthetic sample evidence, runs every stage, uploads the deliverables and
publishes nowhere; a test asserts that every publishing and evidence-reading
step is gated on it. The REVIEW ONLY definition of done asks for exactly this
dispatch.

### 15.1 Run 1 — [34722216087](https://github.com/IronCityIT/ironclad-compliance/actions/runs/34722216087)

`prepare` ✅ 7s · `assess` ✅ 11s, readiness 46.5% over the sample evidence,
identical to the local run · `ai-consensus` ❌ after **23 minutes** ·
`report` ✅ (it runs regardless, and said `consensus status: unavailable`).

The consensus stage did not fail at analysing. It analysed all 57 findings,
14 of 15 models answered every one, and it wrote a valid 1.6 MB result. It
failed at *"Evaluate and set job outputs — Maximum object size exceeded"*: the
`consensus_b64` job output is capped at 1 MB and the base64 was 1.7 MB. The
analysis was lost at the boundary, after it had been paid for. The engine also
uploads the same result as an artifact, `consensus-result-<run id>`, and that
upload succeeded — 208 KB compressed, downloaded and read here.

Reading what came back against what the merge expected found the rest:

| | The engine emits | The merge read |
|---|---|---|
| shape | a JSON **list**, one result per finding, index-aligned, naming no finding | a dict; a list was `unexpected_shape` — and a test asserted that |
| severity | `consensus_severity` | `severity` |
| confidence | `confidence_percent` | `confidence` |

So had the output fitted, every real assessment would still have discarded its
analysis, and the report's commentary block had never had a field to show.
The input half of the contract was fixed on this branch in §2.1; the output
half was written from the engine's README rather than from its dataclass.

And the 57: the control mapping and the remediation plan each raise a finding
for the same gap, so half the payload restated the other half and the AI
analysed each gap twice; three `info` coverage notes had nothing to triage.
Fifteen model calls per item is the cost model, so the payload is now one item
per control, gaps only, most severe first, capped at 25 —
`consensus_findings()`, the one function both the payload and the merge call,
because the results come back by position and nothing else.

Run 1's real output, merged through the fixed code: 25 analysed, overall
critical, 80% mean confidence, 342 of 375 model answers.

Two things for the engine's owner, not this repository:

- `gemini-flash` answered **403 Forbidden on all 57 calls**. The `GEMINI_API_KEY`
  org secret is rejected by the endpoint, or the project behind it is not
  enabled. The engine degrades to 14 models and says so; nothing here fails.
- `gpt-oss-20b` returned no JSON object on 18 of 57 calls.

### 15.2 Found by reading the report job, not by running it

- **The auditor package certified an empty trail.** The report job exports
  the package from the stored `assessment.json` through `_StoredResult`, which
  started with a fresh, empty `AuditLog`. So `audit-trail.csv` was a header
  and `package.json` carried the genesis hash as a *verified* chain head —
  for every package the pipeline would have issued. `STATUS.md`'s "a verified
  audit chain" was true of a chain with nothing in it. `AuditLog.from_dict`
  rebuilds the stored trail with its digests intact; a stored event edited on
  disk now fails `verify()` rather than being re-signed.
- **The fold step doubled every warning** — it extended the document's list
  with a result list that already contained it.
- **The consensus-merged audit event was thrown away**, recorded on the fresh
  log and never written back. It is chained and persisted now.

The fold step is the one piece of Python that lives in YAML. A test extracts it
from the workflow as committed and runs it against a real stored assessment,
with the artifact carrying the answers and the job output carrying a decoy.

### 15.3 Run 2 — [34723682288](https://github.com/IronCityIT/ironclad-compliance/actions/runs/34723682288)

On the fixed workflow. 25 findings sent; the engine took 13 minutes; the
report job downloaded the engine's artifact (707 KB), and the fold step
printed **`consensus status: ok analysed: 25 of 25`**. The report rendered
with the commentary block populated for the first time, the auditor package
exported with its real trail, the artifacts validated, nothing published.

The AI job was still red — *"Job outputs exceed 1,048,576 bytes"*, with every
step green — because 25 results are 0.9 MB of base64 and the step output is
counted alongside the job output. That is the engine's output, not its
analysis, and the fix belongs there: [consensus-engine PR #6](https://github.com/IronCityIT/consensus-engine/pull/6)
drops the model transcripts from the output (~90% of the bytes; 57 results
become 203 KB) and keeps them in the artifact. REVIEW ONLY: opened, not
merged. DNSGuard reached the same limit earlier by a different route —
"Argument list too long" through an environment variable — and reads the
artifact for the same reason; it also strips `model_responses` on receipt as
vendor-naming, so no caller loses anything from the output.

Until it merges, the run summary reports what the report got and what the AI
job said, side by side, rather than letting a red job stand for a lost
analysis.

## 16. The evidence directory was not a boundary

Session of 2026-09-16. Nothing was waiting on this machine — PR #4 open, CI
green, consensus-engine PR #6 unmerged, no word from Bill — so the session
went back to the pattern that has found every defect on this branch: hand the
engine something a real tenant might, and read what comes out.

What it was handed: an evidence directory with a `manifest.json` in it naming
three items — its own file, `../other/beta-access-policy.txt`, and
`/etc/passwd`. Then a directory with no manifest, containing a symlink to a
file outside it, a symlink loop and a directory link climbing out.

### 16.1 A manifest could point anywhere on the volume

`collect_from_manifest` resolved every local URI relative to the evidence
directory and read whatever was there. The borrowed file was extracted,
matched and linked to eleven of the tenant's controls; its path went into the
evidence inventory on the record. `/etc/passwd` was catalogued too, with its
path, and reported as "unsupported evidence format" — which is the only
reason it contributed no text.

Why this matters more than the local repro suggests: the pipeline stages a
tenant's prefix with `ironclad evidence stage`, which refuses a traversal and
a symlink — that was §11's work and it holds. Then it runs `assess
--evidence-dir evidence/`, and if the tenant's prefix carries a manifest, the
URIs in it were never judged against anything. On a shared NAS volume that is
one tenant's manifest reading another tenant's documents into the first
tenant's assessment. The prefix was confined; what the prefix's own manifest
could name was not.

Fixed in `ironclad/ingest/collectors.py`: when the engine is given a
directory, every local URI must resolve — `..` segments and symlinks judged by
where they land — to a path inside it. One escaping item refuses the whole
ingest, every offender named, exit 2, nothing written. Existence is not the
test: a URI outside the directory is refused whether or not a file is there,
because the path itself would otherwise be recorded on the tenant's record.
Remote URIs are untouched — they were never read. An API caller who passes no
directory gets no confinement, which is documented rather than guessed at;
the CLI and the workflow always pass one.

### 16.2 The derived manifest followed symlinks

With no manifest, `manifest_from_directory` walked the folder with
`rglob("*")` and took `is_file()` as the filter — true for a symlink to a
file — and wrote `path.resolve()` as the URI. A `secret.txt -> /etc/passwd`
became an artifact whose recorded URI was `/etc/passwd`. Directory links were
the opposite failure: `rglob` does not descend into them, so `deep/up -> ../..`
was neither read nor mentioned. The loop did not hang, for the same reason.

Now refused, files and directories alike, with every link named — the rule
staging already applies to the same data, applied at the second place the
data is read.

### 16.3 What was not changed

- The tenant id inside a manifest was already checked: `run_assessment`
  refuses an evidence set whose tenant is not the one being assessed. Verified
  by reading `engine.py`, not re-tested; the existing test stands.
- `_local_path` still returns `None` for an item inside the directory that
  does not exist, so a declared-but-missing item is catalogued without text,
  as the contract says.

Ten tests in `tests/test_ingest.py::TestTheEvidenceDirectoryIsABoundary`,
including the CLI's exit code and that the output directory is not created.
`docs/ingestion-contract.md` now states the rule under *Rules*. The clean
sample evidence assesses to the same 46.5% it did before.

### 16.4 An acceptance could never be renewed

Same session, same method, pointed at `ironclad serve` with curl and a
handful of bodies a browser would never send. Most were handled as the tests
promised. Four were not:

- **Request, approve, revoke, request again — 500.** `validate_policy`'s
  one-acceptance-per-control rule counted every entry regardless of status,
  so once a control had carried an acceptance it could never carry another.
  Acceptances expire by design — 90 days by default, 365 at most — and the
  engine's own "Risk acceptance has lapsed" finding tells the client to
  *renew* it; the policy file refused the renewal, and the refusal surfaced
  as `refusing to write a policy that would not load` with a 500. The CLI
  path shares the service and had the same wall. The rule now counts open
  acceptances — draft, pending, approved — and history stays on the record
  without occupying the control. A second *open* request is refused before
  anything is created, naming the acceptance in the way, as a 400.
  Writing that test exposed the next layer: the engine sweeps lapsed
  approvals before every assessment, but nothing swept the *policy store*,
  so an acceptance past its expiry sat on file as "approved" — and under the
  corrected rule would have blocked the very renewal it was meant to invite.
  The request path now sweeps first, persists the expiry and chains an
  `exception.expired` event, then applies the rule.
- **`expires_in_days: 99999999999` — 500 "internal error".** The model caps
  an acceptance at 365 days, but only after computing the expiry, and the date
  arithmetic overflowed first. The request validator now applies the model's
  own ceiling before any date is computed.
- **`control_id: {"a": 1}` — 200**, and an acceptance recorded on the control
  `"{'a': 1}"`. `str()` on an untrusted body is a coercion, not a check. A
  non-string control id is 400.
- **`expires_in_days: 30.5` — 200**, recorded as 30. A whole number of days is
  accepted as an int, a whole float or a digit string; anything else is 400.

Verified by replaying the same curl sequence against the restarted server:
400, 400, 400, then request → approve → revoke → request again lands
`[revoked, pending_approval]` in the policy file. Tests in `tests/test_http.py::
TestAcceptanceWorkflow` and `tests/test_policy.py`; `docs/http-api.md` states
the rule.

Seen and left: an acceptance may name a control that exists in no shipped
framework (`ZZ9.9` was accepted). It is inert — the engine warns at assessment
time that the control is not in the framework — and a tenant policy is
deliberately not bound to one framework, nor to the shipped set, because the
CLI takes a framework file by path. Refusing it in the service would break
that; recorded here rather than guessed at.

### 16.5 An id the store would refuse was accepted by `assess`

`assess --assessment-id ../../escape` ran to completion; `store publish`
then refused the id. In the workflow the id is generated, so nothing reaches
this — but a manual run would have paid for the assessment and the AI stage
before finding out. The same `is_safe_document_id` rule is applied at the
start of `assess`, exit 2, nothing written.

### 16.6 `--client ../beta` assessed tenant "beta"

`slugify` strips what it does not like, and what was left of `../beta` was a
different valid tenant, so the record was minted for `beta`. `ironclad
evidence stage` has refused exactly this since §11, with a comment explaining
why — "a silent reinterpretation of what was asked for" — and the workflow's
`prepare` job constrains `client_id` to letters, digits, space, hyphen and
underscore before anything runs, so neither the pipeline nor a staged run
was exposed. The local CLI and the legacy wrapper were. `ids.client_slug`
now carries the rule, and both entry points refuse with exit 2 before
reading any evidence.

### 16.7 `compare` and `report` on the wrong files

- Two tenants' assessments: `compare` raised the right `ValueError` and the
  CLI let it through as a traceback. Exit 2 now, same message.
- `--from` and `--to` the wrong way round: trusted, so every improvement
  would have read as a regression. Where both records say when they started,
  a pair in the wrong order is refused with both ids and times named; the
  same record twice is a level trend, not an error.
- `report --input findings.b64`, `--compare-to README.md`, and a JSON file
  that is not an assessment: two `JSONDecodeError` tracebacks and a
  `KeyError` from inside the renderer. One reader for `report`, `export` and
  `compare` now refuses a missing file, a non-JSON file and JSON of the wrong
  shape, naming the file and the reason.
- Checked and already right: an earlier assessment against a *different
  framework* produces a "Since the last assessment" section that states the
  reason and shows no numbers. The CLI's stderr headline still prints the
  movement figure for that case; the report a client sees does not.

### 16.8 Hostile and incidental content

A 62 MB single-line Markdown file, a text file with NUL bytes and invalid
UTF-8, a Latin-1 file, an empty file, a file with no suffix, an upper-case
suffix, a dotfile: all handled in 0.6 s, each catalogued or warned about as
the contract says, the truncation named. Two things were not right:

- **A folder's `manifest.json` that belongs to something else.** A browser
  extension's manifest in an evidence dump is picked up as the evidence
  manifest and the assessment is refused — with the three contract faults
  named, so the operator knows which file and why. Left as is: a fail-closed
  refusal with the reason is the right answer, and renaming the file is the
  fix.
- **`.DS_Store`, `.git/objects/*` and `__MACOSX/._policy.pdf` were evidence
  items.** Counted in "N evidence items" on the report, and — unreadable —
  reported as facts about the pipeline. Skipped now, with one warning naming
  them; a file that really is evidence can still be declared in a manifest.

### 16.9 Hand-edited policy files

The runbook has an operator editing `policy.json` by hand, so eight
mis-edits went through `ironclad validate --policy`: a two-year acceptance,
an expiry before its request, a self-approval, an exclusion for a control
that exists nowhere, `owners` as a list, a tenant that is not the
assessment's, a top-level array, naive timestamps. Seven were named
correctly, in the operator's terms — the self-approval as "needs a second
person", the tenant mismatch at `assess` time with both tenants named. The
eighth was the file that was not JSON at all: every one of `validate`'s
three flags produced a traceback for it. The command exists to be handed
dubious files; a non-JSON file is now the first finding it reports.

Naive timestamps are read as UTC and the acceptance in that file, expiring
2026-09-01, correctly counted for nothing on 2026-09-17.

### 16.10 A stalled connection kept its thread forever

2026-09-17. `ironclad serve` had no read timeout. Forty connections that sent
a request line, headers and `Content-Length: 500` and then nothing, plus
twenty that connected and sent nothing at all: sixty handler threads and
sixty sockets, still there ten seconds later, gone only when the clients hung
up — read from `/proc/<pid>/status`. The server kept answering others, so it
is a resource leak rather than an outage, but a dashboard poller behind a
flaky network is exactly the client that does this, and threads and file
descriptors are finite.

`READ_TIMEOUT_SECONDS = 30` on the handler now, applied to the socket; a
timeout mid-request closes the connection without a 500 attempt or a
traceback. The test shortens it to a second and asserts each stalled socket
reads EOF and the thread count returns to where it started. Writing the test
cost more than the fix: the first version asserted a thread *peak*, and the
sampling loop did not start until the connects had finished — on this
machine ten local connects took a second, by which time the handler threads
were already timing out. The peak was the wrong thing to measure; the EOF is
the fact.

### 16.11 The auditor package could not prove it was the package issued

`package.json` listed the files by name. No digests. The README told the
auditor the audit trail was hash-chained — true, and the trail is one of
seven files; `control-register.csv`, the one that carries the verdicts, was
covered by nothing. Change `partial` to `compliant` on one row and the
package still read as issued.

Every file is now checksummed twice: `sha256` in `package.json`, and a
`SHA256SUMS` in the format `sha256sum -c` reads, written last, over
everything including `package.json` and the README. The README says how to
run it. Proven with the stock tool: the edited row reads
`control-register.csv: FAILED`, exit 1; a test runs `sha256sum -c` where the
binary exists and checks the digests by hand where it does not.

### 16.12 `store verify` stopped at the first fault

The volume store's verify — the check the runbook says to run on a restore
from backup — returned on the first missing or altered file. A restore with
one file missing, one altered and one that should not be there reported the
missing one and nothing else, so the operator learned what was wrong one
re-run at a time. It now reports every fault, and also names a file that is
on the volume and not in the manifest: a deliverable set must contain only
what was issued, and a stray beside the report is the same class of problem
as an edited one. Nested layouts (the auditor package is a directory) are
walked.

Also exercised, and right: publishing the same assessment twice leaves one
record; an unknown assessment id and another tenant's id both answer "no
manifest was stored", exit 2, indistinguishably.

### 16.13 The CLI acceptance workflow, and `--control ../x`

The same lifecycle as §16.4 through `ironclad exception`: request, the
requester's own approval refused ("needs a second person"), a second
person's approval, revocation, and the renewal — which lands, since the CLI
shares the service. 400 days and 99999999999 days both refused at 365; a
viewer and an actor with no role refused by name. One thing got through:
`--control ../x`, accepted and written to the register as an acceptance of
nothing. Every shipped framework's control ids satisfy the document-id rule
(the loader enforces it), so an id that does not can never match a control.
Refused now, in a request and in a hand-edited policy file, for acceptances
and scope exclusions alike.

### 16.14 The workflow did not speak the standard input names

`CLAUDE.md` fixes the dispatch inputs every product declares — `target`,
`client_name`, `scan_id` — and every sibling's scan workflow declares them;
the portal's dispatcher falls back to `{target, scan_id, client_id}`. This
workflow predates the standard and declared `client_id` only. A dispatch
carrying `scan_id` would have been rejected by GitHub as an unexpected input
before a job ran, and `client_name` likewise; the deviation was not recorded
anywhere. §4 recorded why `target` is not declared (no network target) and
said nothing about the other two.

`client_name` and `scan_id` are declared now. `client_id` stays as an alias,
so `functions/trigger.js` and anything else that dispatches today keeps
working; the prepare job resolves the client once — refusing neither-given
and both-given-and-disagreeing — and every later job reads the resolved
value. A `scan_id` becomes the assessment id after the same character rule
the engine applies, and a dry run still suffixes it. The prepare job's shell
is extracted from the workflow as committed and run by a test, because
nothing else tests shell.

Then proven on a runner, the way the first two dry runs were:
[35170758865](https://github.com/IronCityIT/ironclad-compliance/actions/runs/35170758865),
dispatched with `client_name="ICIT Dry Run"`, `scan_id=icit-dry-run-standard-inputs-20260917`,
`dry_run=true`, `group=quick`. `prepare` resolved the client and
`assess` ran as `icit-dry-run-standard-inputs-20260917-dry-run` at the
familiar 46.5%. The AI job was **cancelled while still queued** — fifteen
models over twenty-five findings for thirteen minutes proves nothing about
input names — and the report job, which runs regardless, rendered with
`consensus status: unavailable`, exported the package, validated the
artifacts and published nothing. A third dry run on record; nothing real
dispatched.

### 16.15 A copy of the policy was corroboration

The scoring rule says a control reads as met only with two current items —
"one document is a claim; two is corroboration" — and the contract said the
checksum was an artifact's identity, so a re-submitted file would be
recognised rather than counted twice. Tried: the sample evidence plus a
byte-identical copy of `access-control-policy.txt` under a second name. Same
artifact id in the inventory, listed twice; `evidence_count` up by one on
eleven controls; CC6.8 moved from one item at 0.34 confidence to two at
0.59. Had its coverage been over 75%, the copy would have flipped it to
compliant. A copy with one byte appended did exactly the same.

`EvidenceSet.add` appended regardless of id. It refuses a duplicate id now,
and the collector goes one step further: two items whose extracted text is
the same once case and whitespace are set aside are one document. The
earlier submission is kept — by the manifest's `collected_at`, or the file's
own timestamp, whichever sorts first — its operator hints merged, and the
copy named in a warning. A test asserts the whole verdict table is identical
with and without the copy. A copy with a *word* changed is still two
documents; that is a similarity question, not an identity one, and it is
recorded here rather than approximated.

### 16.16 The manifest could move the freshness clock

Freshness held up well under `touch`: a 200-day-old access review and a
400-day-old policy read as stale, five controls dropped from compliant to
partial, readiness 46.5% → 37.0%. A file dated ten days ahead was accepted
without a word, which led to the manifest: `collected_at: 2030-01-01` made a
review fresh until 2030, and `valid_until: 2099-01-01` was accepted as
quietly as any other date. The windows are Iron City policy (STATUS, open
decision 5) and the manifest is the tenant's file. A future `collected_at`
or `valid_from` — beyond a day of clock skew — is now pulled back to
ingestion time, named in a warning. An explicit `valid_until` past the
standard window for the class stands, because the contract promises the
override for evidence with a real validity period, and is disclosed on the
record and in the report's caveats; a shorter one is nobody's business.

### 16.17 Two URLs nobody read scored 100%

`control_hints` is how an operator links a scanned policy the engine cannot
read, and the mapping took the assertion at face value: full coverage of
every point of focus. The manifest is the tenant's file. Two `gs://` items —
catalogued, never fetched — each hinting all 33 SOC 2 control ids: **100.0%
readiness, 33 met, 0 remediation items**, from zero bytes read. A verdict
table that says "compliant" on the strength of items nobody opened is an
assertion wearing an assessment's clothes.

The assertion is kept, because the scanned-policy case is real: beside a
readable item, an asserted link still counts as the corroborating second and
still fills the points. But a control whose *every* link is an assertion
about an unread item is held at partial, with a rationale saying so, a
warning naming the controls (it reaches the report's caveats), and
`asserted_only` on the module output. The same manifest now reads 50.0%, 0
met, 33 partial, 33 remediation items — still generous for nothing read, and
partial-counts-half is the scoring rule rather than this change; recorded as
a residual.

### 16.18 A document that *is* the framework scores 100%

Two text files holding every SOC 2 control's description and points of
focus, differing by one sentence: 100.0%, 33 met. Matching is on words, by
design ("crude, and deliberately so: a readiness signal for a human
reviewer, not an audit opinion"), and a document that contains the
framework's words matches the framework. The engine cannot tell a policy
that quotes the criteria — many do — from a copy of them, so it does not
pretend to. It now names two signals, as warnings that reach the report's
caveats and as fields on the module output for the analyst and the AI
stage: an item matched to at least half the framework (and ten controls),
and an item that carries three or more controls' descriptions verbatim. The
verdicts are left alone. The residual is the nature of keyword matching, and
it is what the AI stage and the auditor are for.

**Calibrated the same day.** "Half the framework" was the first bar, tested
on SOC 2 alone, and it named the sample access-control policy on HIPAA (13
of 23), PCI DSS (15 of 27) and the incident-response plan on NIST CSF (21 of
43). A framework whose controls all speak of access is matched widely by any
policy about access; that is the framework's vocabulary, not a stuffed
document. The bar is four fifths now, the stuffed pair (33 of 33) still
trips it, and a test runs the sample evidence against all four shipped
frameworks and asserts neither signal fires.

### 16.19 Scoping out the framework

A policy scoping out all 33 SOC 2 controls: readiness 0.0%, no crash, every
control not applicable, the report saying so. All but one: 0.0% over one
control, with the scope review already raising "scoped-out control has
supporting evidence" for the ones that had evidence — the right finding. What
was missing was the headline: a readiness figure computed over one control
looked exactly like one computed over thirty-three. When half or more of the
framework is scoped out, the caveats now say how many and over how many the
number is computed. Each exclusion is still a documented, approved decision;
this is about where the number is read.

### 16.20 Accepting the framework

The same shape from the other direction: an approved, time-boxed, second-
person acceptance on every one of the 27 gaps. Readiness 46.5% → 61.2%, 27
accepted, **0 remediation items** — every one of those decisions is
legitimate on its own terms and the engine applied each correctly, and the
headline said nothing about there being twenty-seven of them. When half or
more of the framework is under accepted risk, the caveats now say so, and
say what it does to the number: each counts as half-met and none carries a
remediation item. The 0.5 weight is the scoring rule (STATUS, open decision
4's neighbour) and is not changed here.

### 16.21 Twenty people at once: fourteen acknowledged, eight on file

Twenty concurrent POSTs to `ironclad serve`, twenty different controls.
Fourteen answered 200; **eight** acceptances were in `policy.json`
afterwards. Six answered 500 — "not valid JSON" — having read the file while
another thread was half-way through writing it. Each request read the
policy, appended its entry and wrote the whole document back over whatever
the others had written since; the audit sidecar raced the same way. An
acknowledged acceptance that is not on file is the worst outcome a record
store can produce, and a dashboard with two compliance managers is exactly
where it happens.

`PolicyStore.locked()` now takes an advisory `flock` on `policy.json.lock`
— across threads, since each acquisition opens its own descriptor, and
across processes, so the CLI and the server can share a volume — and the
service holds it around the whole of request, approve and revoke: the read
that decides, the write that records, the audit event that chains onto the
last. Both files are written to a temp file and renamed over the original.
Authorization happens *before* the lock is taken, because the lock file
lives beside the tenant's policy and a stranger's refused probe must still
leave nothing named for the tenant (§13.2 — the test for that failed on the
first attempt and pointed at the ordering). Replayed: 20 of 20 answered 200,
20 on file, 20 audit events, chain intact.

### 16.22 A 0.57 MB document that cost 545 MB to read

The extraction extras do not install on this machine (PEP 668), so the
binary formats had only ever been exercised in CI. A venv in the scratchpad
fixed that: 825 passed, 19 skipped (the MariaDB ones). Then the formats a
client actually sends were handed something unfriendly.

A `.docx` is a zip, and its `document.xml` is parsed in full by
`python-docx` before the first paragraph comes back. One built with 143 MB
of `<w:t>` inside — 0.57 MB on disk — took **19 s and 545 MB of RSS** to
yield the 20,000 characters the clip keeps. Four of those in an evidence
folder and the assess job is out of memory on a 7 GB runner, which is the
one failure the ingest contract promises never to allow: "an assessment must
not die because one artifact in a hundred is corrupt". `openpyxl` in
read-only mode streams rows but loads the shared-strings table whole, so an
`.xlsx` has the same door. And `_extract_text_file` read a 62 MB file whole
to keep 20,000 characters of it.

Now the zip's central directory — free to read — is consulted first, and a
member that would expand past 50 MB is refused unopened; any non-text file
over 200 MB is not parsed; a text file is read only as far as the clip. Each
refusal is catalogued and worded like every other unreadable item. The same
document: 0.08 s, 26 MB, "expands to 136 MB, over the 50 MB a document may
expand to; too large to read safely", and the assessment runs on.

PDF, checked the same way: a 0.9 MB file whose one page carries a 310 MB
FlateDecode content stream. `pypdf` 6 refuses it on its own — "Limit reached
while decompressing" — in 0.4 s and 171 MB, and the extractor reports that
in the usual words. Nothing to add there; recorded so nobody adds it twice.

And the ordinary case, for the record: the sample access-control policy
saved as a `.docx` and the access review as an `.xlsx` (one line per cell),
beside the three remaining `.txt` files, assess to the same 46.5% as the
all-text set, with the review on its 90-day clock and the scan on its 30
from the file names. The binary paths and the text path agree.

### 16.23 consensus-engine PR #6, validated against the real artifact

The fix that unblocks the red AI job sits in another repo, unmerged since
2026-09-12, and had been argued from arithmetic. The artifact from run
34723682288 is still downloadable, so the argument became a measurement:
707,453 bytes as written; 86,669 after the PR's `jq`; 115,560 as base64 —
under the 1 MB cap with room for roughly 200 findings. Every field the merge
reads survives. Fed to `ironclad assess --consensus-b64`, the stripped list
folds as `ok, 25 of 25, critical, 81.7%, 338 of 375`, with the commentary
block rendered — the same result the report job got from the artifact.
Posted as a comment on PR #6 for the reviewer; nothing merged.

### 16.24 The one text the white-label gate cannot scan

With the real engine output in hand (§16.23), its 250 lines of aggregated
remediation and verification advice were read for product and vendor names.
None — the models wrote "EDR", "SIEM", "DLP", "FIM", not brands. But that
text is stored on the record and shipped in `assessment.json` inside the
auditor package, and the gate that enforces the white-label rule scans the
static surfaces at build time; nothing stood between a model recommending a
tool by name tomorrow and that name reaching a client. `ironclad/white_label.py`
carries the gate's own pattern — a test holds the two identical — and the
merge replaces a match in the models' advice before it lands, counting the
replacements on the record and in a warning. The real artifact folds with
zero replacements.

### 16.25 Three pipelines, and the gates only one of them ran

`ci.yml`, `scripts/gates.sh` and the `Jenkinsfile` are meant to run the same
gates (§11.8). Read side by side: the committed-secrets check was inline
shell in `ci.yml` and existed nowhere else; the Jenkins security gate
audited the whole environment (the scoping to `requirements*.txt` that made
`pip-audit` runnable in CI never reached it), ran `bandit` without `tools/`,
and had no catalog gate. Then a parity test written to hold the three
together failed on its first run against **CI**: `tools/build_catalog.py
--check` — the gate that keeps the dashboard's `catalog.json` equal to what
the registry says — ran in `gates.sh` and the Jenkinsfile and not in CI. A
registry change could have shipped a stale catalog with six green jobs.

The secrets check is `scripts/check_secret_literals.sh` now, run by all
three (and proven to catch a planted key and to pass a secret's *name*); CI
runs the catalog check; the Jenkins security gate matches CI's. The parity
test names any script or gate command missing from any of the three.

### 16.26 The Jenkins pipeline ran on a controller

"DONE, not executed on an agent" since it was written. This machine has a
JVM, so a throwaway Jenkins (`jenkins.war`, setup wizard off, the
declarative-pipeline, git, docker-workflow and junit plugins from the update
centre) ran in the scratchpad on a loopback port. Two things came of it.

**The declarative linter passes the committed Jenkinsfile.** That is the
first check the file had ever had beyond balanced braces.

**Then the pipeline itself ran.** The committed file declares a
`python:3.11-slim` Docker agent and this controller has no Docker, so a copy
with `agent any` substituted — and nothing else — was built from a local
clone, with the CI-parity venv on the controller's PATH. Build 3: every gate
in the Gates stage green in order (format, lint, typecheck, test, artifacts,
catalog, end-to-end, build), then `rules` green — the Firestore emulator
started and the 53 cases ran — `functions` green, `security` green (the
first `bandit` run on this machine, through the venv), and `persistence`
UNAVAILABLE with no MariaDB, which marked the build UNSTABLE exactly as the
pipeline promises. 775 seconds.

Two defects, both found by the run and neither by the linter:

- **`cleanWs(...)` in the `always` post section is the ws-cleanup plugin,
  not a core step.** On a controller without it the whole post section
  threw "No such DSL method 'cleanWs'" — after the gates, so a green build
  would have ended red. `dir('out') { deleteDir() }` and the same for
  `dist/` do what the patterns did, with core steps only.
- **An UNSTABLE build had no description.** The `success` and `failure`
  branches set one; `unstable` echoed a line into the log and left the
  build list blank. The unavailable gates are now accumulated beside the
  failed ones and named in the description.

Builds 3 through 6 on the throwaway controller: 775 s the first time (the
venv installing), ~220–275 s after. Not proven: the Docker agent itself, and
the pipeline on ICIT's own controller with its plugin set. The `junit` step is the JUnit plugin, which
is in the setup wizard's recommended set and was installed here to match a
normal controller; it is the one plugin the file still assumes.

### 16.27 The "free integrity check on any restore" cried tamper on every second assessment

Build 4 of the same throwaway Jenkins job, run to prove the description
change, failed its end-to-end gate: *"the stored chain breaks at event
000000"*. Nothing had changed in the store code. What had changed was the
workspace: build 3 had already published `icit-internal`'s assessment into
`$WORKSPACE/.ironclad-volume`, and build 4 published a second one beside it.

Every assessment's audit trail starts at the genesis hash; a tenant's store
holds every assessment's trail, one after another. The end-to-end check —
and `MariaDBResultStore.verify_audit_chain`, the check `HANDOFF.md` calls
"the free integrity check on any restore from backup" — walked a tenant's
whole trail as one chain. Green against a fresh store, which is all CI ever
has; a break at the second assessment's first event on any store that has
been used twice. A restore check that reports tampering on every tenant with
two assessments would have been switched off the first week.

`verify_stored_chains` in `store/base.py` verifies one chain per
`assessment_id` — each starting at genesis, each linking forward — and both
stores and the end-to-end script use it; `ironclad store verify` now reports
the chain verdict beside the deliverables' and is red if either is wrong.
Run three times into one volume: 2, 4, 6 events across 1, 2, 3 assessments,
every chain verifying. The contract test covers two assessments on both
stores, and the volume store test edits a line and gets the event and the
assessment named. Found by a pipeline that had never run, running twice.

### 16.28 The Jenkins assessment mode ran, and its publish stage was wired to the retired path

`RUN_ASSESSMENT=true`, `CLIENT_ID="ICIT Dry Run"`, `EVIDENCE_DIR=examples/evidence`
on the throwaway controller: assess, package, validate, archive — 46.5%,
eleven artifacts including `SHA256SUMS`, fourteen seconds. Then the
Publish stage, which had never run either: it bound the two retired-ingest
credential ids unconditionally, so on a controller without them — every
controller, today — an assessment that had run failed at publish; and it
knew nothing of `IRONCLAD_STORE`, the sink the GitHub workflow has
published to since the architecture change. It now makes the workflow's
three-way choice in the workflow's order: the store when an `ironclad-store`
credential exists, the retired ingest when only those two do, otherwise a
named note and UNSTABLE, each credential bound only inside the step that
uses it. Builds 7 and 8 (SOC 2, HIPAA): archived, not published, and the
build description says exactly that — "assessment: ICIT Dry Run / hipaa —
not published: no store is configured on this controller".

Then with an `ironclad-store` secret-text credential on the controller
pointing at a scratch volume, build 9: SUCCESS in fifteen seconds,
"published to the store", the credential value masked in the log, the
record and twelve deliverables on the volume, and `ironclad store verify`
green on both the deliverables and the chain. That is the Jenkins route
from evidence to a store, end to end, for the first time.

### 16.29 The trend did not work against the target store

MariaDB 10.11 turned out to be installed on this machine, so a scratch
server with its own data directory went up on a loopback port: the 73 store
tests pass against it (CI's is 10.5.29, the NAS's 10.5.8), the end-to-end
round trip ran twice into it, and twenty concurrent publishes of different
assessments plus ten of the same one landed clean — one record, 33 controls,
21 chains verifying, no deadlock.

Then `ironclad compare --client acme --store mariadb://…`: *"this store
keeps the projected rows, not the whole document, so it cannot be compared
from"*. The feature the README leads with — "a compliance programme is a
trend, not a snapshot" — was unavailable against the store the architecture
is moving to. Everything the comparison reads is in the rows: the summary
and framework on `assessments`, each control's status and points on
`assessment_controls`, the queue on `remediation_items`. The MariaDB store
now rebuilds a comparable document from them, claiming nothing it does not
hold, and a contract test on both stores asserts the comparison read out of
the store is identical to the one built from the documents that went in.

### 16.30 The trend reaches the client's report

The comparison existed, the report rendered it, and nothing in either
pipeline ever fetched the previous assessment — so no client report has ever
carried a "Since the last assessment" section unless someone ran two CLI
commands by hand. `ironclad store latest --client X --framework Y --out
previous.json` writes the tenant's most recent stored assessment against
that framework (exit 3 and no file when there is none, which a pipeline
reads as "first assessment"; never the run being produced, by `--before`).
The workflow's report job fetches it when a store is configured and renders
against it; the Jenkins assessment stage does the same behind the
`ironclad-store` credential. Both steps' shell is run as committed by a
test: a first assessment gets no section and no error; a second gets the
section naming the first.

### 16.31 Two reports: the one issued, and the one in the package

Build 11 on the throwaway controller, the first pipeline run anywhere to
carry a trend: `out/report.html` had "Since the last assessment" against
build 9's stored assessment; `out/package/report.html` — the file the
package's README calls "the deliverable as issued" — did not. The package
re-rendered the report from the stored result, and the result does not know
about the previous assessment; the two were identical until the trend gave
the issued one something the re-render could not reproduce. Two versions of
a client's deliverable in circulation is the thing the artifact store's own
comment says must never happen. `export --format package --report
out/report.html` now carries the issued file byte for byte, so the package's
`SHA256SUMS` line is the issued report's digest; both pipelines pass it.
Without the flag the package still renders one, for a stored result that
has no issued report beside it. Build 12 on the controller: the issued and
the packaged report share one digest, the trend is in both, and the stored
deliverables verify — three chains in the tenant's trail by now, all sound.

### 16.32 The same record, two types

`ironclad serve` in front of the scratch MariaDB: health reports the store
kind, a stranger's read is 403, the listing and the queue come back. And
`readiness_score` came back as the string `"46.50"`. From the volume store
the same field is the number `46.5`. The driver returns DECIMAL as
`Decimal` and TIMESTAMP as `datetime`, and the HTTP layer's JSON serialises
whatever it does not recognise with `str`. A dashboard reading one store and
then the other — which is exactly the migration in HANDOFF §13 — would watch
a number turn into a string. Rows are normalised on the way out of MariaDB
now, Decimal to float and datetime to ISO-8601, and a contract test on both
stores asserts the record reads back in the same types.

### 16.33 Two clients, one scan id, one IntegrityError

`scan_id` is a standard dispatch input now (§16.14) and becomes the
assessment id verbatim; nothing about it is tenant-scoped, and two clients'
dispatchers can hand in the same one. The volume store partitions by tenant
and stored both. MariaDB keyed `assessments` on `assessment_id` alone, so
the second tenant's publish died with `StoreError: … failed: IntegrityError`
— an opaque failure of one client's run caused by another client's id. The
key is `(tenant_id, assessment_id)` now, the child tables carry the composite
key and cascade on it, the one join matches the tenant too, and a contract
test publishes the same id for two tenants on both stores and re-stores one
without touching the other. Nothing has been initialised from the old
schema anywhere but CI's throwaway and this machine's scratch server, so
there is nothing to migrate; a database that had been would need the tables
recreated, since `init` only creates what is missing.

### 16.34 The dashboard showed the bare number

Every caveat added this week — half the framework scoped out, half under
accepted risk, controls held at partial on assertions about unread items, a
document that matches most of a framework, a lapsed acceptance — reaches
the report and is stored on the record. The dashboard card, the surface a
client looks at most often, rendered the readiness figure, four bars and
the stale-evidence line, and nothing else: a 100% over one control with 32
scoped out was indistinguishable from any other 100%, and an assessment
with a failed stage (exit 3, "partial", named in the report) carried no
mark at all.

The card now shows a scoped-out count beside the other four, a partial
notice naming any stage that did not complete, and the first three caveats
with a count of the rest. `warnings` is a list on the record and a JSON
string out of a MariaDB row, and a hand-edited record could make it
anything, so it is coerced before it is read, every entry is escaped, and
the hostile-record test covers all three new fields. The CSS went into the
committed `index.html` with the foreign working-tree edits set aside and
put back afterwards, untouched (§14).

### 16.35 Nothing could ever be overdue

`build_item` minted every remediation item with `created_at=now` and
`due_date=now + SLA`, on every run. A control outstanding for six months
read "due in 30 days" in every report; `RemediationPlan.overdue()` could
not be true within the run that made the plan; the dashboard's overdue
mark and the `idx_remediation_tenant (priority, due_date)` index were
decorative. The item id is minted from tenant and control precisely so a
run can recognise last run's item — the comparison uses that — and the
plan never did.

With the previous assessment in hand (which both pipelines now fetch,
§16.30, and pass as `assess --previous`), an item still open keeps the
first-raised and target dates it was given, unless its severity rose — then
the target is the sooner of the two, because a gap that got worse does not
get more time. The plan counts what it carried and what is overdue, the
caveats name the overdue controls, and the report marks each overdue row
with the date it was first raised, judged against the plan's own
generation time so the document reads the same whenever it is opened. Run
against a previous assessment dated a hundred days back: 27 carried, 27
overdue, every row marked. The workflow's assess job fetches the previous
assessment (it needed the store read there) and hands it to the report job
as an artifact, so the plan and the trend see the same one; the Jenkins
stage fetches first and assesses second.

### 16.36 Accepting every gap read as eleven improvements and 27 items closed

`compare` between the sample baseline and the same evidence with all 27
gaps under approved acceptances (§16.20's file): *"readiness 46.5% → 61.2%
(up 14.7), 11 improved, 0 regressed, 27 remediation item(s) closed"*. The
movement rank put `accepted_risk` beside `partial`, so partial → accepted
was "unchanged" (there was a test for that) but gap → accepted was
"improved", and an item that left the plan for any reason was "closed".
A trend section saying 27 items closed after a mass acceptance is the
number that looks like progress and is not — exactly what §16.19–16.20
added caveats about, and the comparison was contradicting them.

A risk acceptance is a decision about a control, not a change to it, in
either direction. Into acceptance is `risk_accepted`; out of it without a
fix is `acceptance_lapsed`; accepted and then actually met is an
improvement. An item that left the plan because its control is now accepted
or scoped out is `set_aside`, not closed. The headline names the decisions,
the report gets a "Decisions, not movement" block with both tables and a
"Set aside by decision" card beside "Remediation closed". The same pair now
reads *"0 improved, 0 regressed, 0 closed, 0 opened; 27 accepted as risk"*.

And its neighbour: a `--group quick` run followed by a deep one read as
"27 remediation items opened" — quick leaves the remediation capability
out, so it planned nothing and every item in the deep run was new against
it. The comparison now says when either side did not run remediation
planning and that the opened/closed counts are not a trend; the counts stay,
the caveat sits beside them.

### 16.37 A fourth dry run, for the report job's new shape

[35183541091](https://github.com/IronCityIT/ironclad-compliance/actions/runs/35183541091),
`group=quick`, the AI stage cancelled once `assess` had reported. What it
proved: the report job tolerates the absent `previous-assessment` artifact
(a dry run and a first assessment look the same to it), renders without a
trend, packages the report as issued, validates the artifacts and publishes
nothing. The `hashFiles` guard on the upload and the `continue-on-error`
download are the two pieces of YAML the local shell tests cannot exercise,
and they behaved.

### 16.38 Looked at and left

Examined during §16 and deliberately not changed, each with the reason:

- **An acceptance or exclusion may name a control that exists in no shipped
  framework** (`ZZ9.9`). Inert — the engine warns at assessment time — and
  a tenant policy is deliberately not bound to the shipped set because the
  CLI takes a framework file by path (§16.4).
- **A static file with a space in its name is not served** by `ironclad
  serve`'s static handler (404). The dashboard's assets have no spaces and
  the strict path rule is worth more than the convenience.
- **Partial counts as half-met, and so does accepted risk.** The scoring
  weights (STATUS, open decisions 4 and 5) are a commercial call; the
  caveats now say when they dominate the number (§16.19–16.20), which is
  the most the engine should do on its own.
- **A document with a *word* changed is two documents** (§16.15): a
  similarity question, not an identity one.
- **The `python:3.11-slim` Docker agent** in the Jenkinsfile (§16.26): the
  file runs; the agent image has not been proven from this machine.
- **The dashboard reads Firestore** and cannot read `ironclad serve` until
  B6 is decided (HANDOFF §16). Every field the card now shows is in the
  record both stores hand back, so the switch is a data-source change.
- **PCI DSS 4.0.1**, below.

`frameworks/pci-dss-4.0.json` is still a revision behind (§15, STATUS). The
PCI SSC's own announcement, read this session, says v4.0.1 added and deleted
no requirements and changed no numbering; v4.0 was retired on 2024-12-31, so
a report issued today names a retired revision. The 27 controls here are the
`x.y` objective statements and their points of focus are Iron City
paraphrases, so the bump is probably a version string — but "probably" is
what a compliance framework file cannot run on, and the summary-of-changes
document is behind a click-through this machine cannot get past (403). Left
for someone with the document. One thing to check when they do: `8.4`'s
points of focus label `8.4.1` as remote access; in the published numbering
`8.4.1` is non-console administrative access into the CDE and remote access
from outside the network is `8.4.3` (checked against three independent QSA
write-ups, not the standard itself). That reads like a paraphrase written from
memory, and it predates the version question.

### 16.39 The dashboard's read path over `ironclad serve`, short of the token

Stage 5 (HANDOFF §13) had two halves: the dashboard reading `ironclad serve`
instead of Firestore, and a way for the browser to get a token (B6). The
first half is not blocked, so it is done. The second is a decision and is left
alone.

- `dashboard/public/api.js`: a data source over `/api/v1/me`,
  `/tenants/{t}/assessments` and `/tenants/{t}/remediation`. Its adapters turn
  a store row (a flat summary, with nested fields as JSON text when it comes
  out of MariaDB) into the record `renderAssessments` / `renderRemediation`
  already take, so rendering doesn't change with the backend. It polls where
  Firestore pushed. A failed request goes to `onError` and polling carries
  on. A refusal is raised with the server's own message, never returned as an
  empty list.
- `app.js`: the card's timestamp takes the engine's ISO `started_at` as well
  as a Firestore Timestamp.
- `auth.js::startApi(config, token)` and `config.api`: the wiring. The token
  is a parameter, and **`index.html` does not call it** until B6 is decided.
- `dashboard/test/api.test.js`: 22 cases against a **real** `ironclad serve`
  on a loopback port over a volume store with a published assessment. They
  cover: the principal, the record shape, the remediation evidence gap, a
  cross-tenant refusal, a wrong token refused rather than read as empty,
  polling that stops when told and survives errors, and the adapters on
  malformed JSON text.
- `ci.yml`: the dashboard job now pins Python 3.12, because the test starts
  the engine. It used to rely on the runner image's python3.

Found uncommitted in the working tree, dated 2026-09-17 01:02–01:12, after the
last commit. The style and cross-references show it is this branch's
interrupted work, not the Sage WIP (§14). It was tested on its own in a clean
worktree of `f50a899` with only these files applied: dashboard 60/60,
`sh scripts/gates.sh` all green. In the shared working tree the dashboard run
is 58/60. Both failures are `sage-demo.json names wazuh`, the known foreign
file, and are correct.

What remains of stage 5 is B6 alone: once a browser has a bearer token the
server accepts, `index.html` calls `startApi` instead of `startAuth`.

### 16.40 A request inside a request body ran as its own request

**Failure.** `ironclad serve` only reads a body framed by `Content-Length`.
Against a live server on 2026-09-23, a `POST .../exceptions` sent with
`Transfer-Encoding: chunked` and a complete `GET /api/v1/me` as its body got
**two** answers on one connection. The first was 400 for the POST, read as an
empty body. The second was 200 for the `/me`, which no proxy in front of the
server would have seen as a request. `HEAD` did the same with a
`Content-Length` body, because `do_HEAD` never reads one.

**Root cause.** `_read_body` read `Content-Length` bytes and ignored any
transfer coding, so a chunked body was treated as absent and its bytes stayed
on the kept-alive connection to be parsed as the next request line. This is
the same class of fault as the 413 case (§ earlier, `test_an_oversize_body…`),
arriving by a different header. It matters here because the stated deployment
is behind a reverse proxy, and a proxy that forwards chunked bodies is exactly
the gap request smuggling uses.

**Fix.** Any `Transfer-Encoding` is refused unread with 501, which RFC 9112
§6.1 specifies for a coding the server does not implement. The message says
to send `Content-Length`. Because the body is refused unread, the existing
path closes the connection. A `HEAD` that announces a body now closes the
connection after its answer. `docs/http-api.md` lists the 501.

**Validation.** Four new tests in `tests/test_http.py` (`TestTransport`) failed
first and now pass: chunked, chunked plus `Content-Length`, `gzip, chunked`,
and a HEAD with a body. Each asserts exactly one response on the socket. The
live reproduction now gets a single 501. `sh scripts/gates.sh`: every gate
green except white-label, which fails only on the foreign `sage-demo.json`
(§14), as before.

**Looked at and left.** A token-file role outside the five (`admin`) is
dropped and the token authenticates with no permissions. This is deliberate
(`Principal.from_claims`: a typo must not become a grant) and fails closed.

### 16.41 One unreproduced failure of the twenty-at-once test

**Failure.** Once on 2026-09-23, a full local `pytest` run just after §16.40
reported `test_twenty_people_at_once_all_land_and_the_chain_holds` failed.
The message was lost: the run was piped to `tail -1`. The fix was committed
before the failure was looked at. That was a process slip, and it is recorded
here rather than hidden.

**Is §16.40 the cause? No, on evidence.** The test sends `Content-Length`
POSTs through `http.client`, never a `Transfer-Encoding` header or a HEAD,
which are the only paths §16.40 changed. Since then it has passed 8/8 alone,
5/5 in the full suite, and 30/30 run ten copies at once. CI at `f774081` is
green on both Pythons.

**Root cause: not established.** One gap in the test is real: a client-side
exception in a worker thread (a 5 s timeout on this QNAP disk under load,
for example) died with the thread and left no outcome. The first assertion
could pass without it, and the fault would surface as a confusing mismatch
in the policy file. The test now records every thread's exception or non-200
body and asserts one outcome per control. If it happens again, the assertion
names the cause.

**Update.** The probable cause was found the same day: the server's listen
backlog of 5 (§16.44).

### 16.42 The same smuggling, through Content-Length

**Failure.** After §16.40, the other framing header was checked against a
live server. A POST whose body was followed by a complete `GET /api/v1/me`
got the `/me` answered (200) when its length was `Content-Length: 0_7`,
`+7`, or two differing `Content-Length` fields in either order. A `HEAD`
with `Content-Length: 0` followed by a second, non-zero length ran its body
as a request too.

**Root cause.** The length went through `int()`, which accepts `+`, `_` and
non-ASCII digits that the grammar (1*DIGIT, RFC 9110 §8.6) does not.
`headers.get` returned only the first of several fields. A proxy that rejects
`0_7`, or takes the last of two lengths, frames the connection differently
from the server: the disagreement request smuggling needs.

**Fix.** `_read_body` reads every `Content-Length` field. More than one field,
or a value that is not ASCII digits after trimming whitespace, is a 400
refused unread, so the connection closes (RFC 9112 §6.3). A listed value
such as `7, 7`, which RFC 9110 allows a server either to collapse or to
refuse, is refused. `do_HEAD` checks every length too.

**Validation.** Eight new cases in `TestTransport`, each asserting one
response per socket: underscore, plus, full-width, duplicates in both
orders, list, and HEAD with a zero before a length. One more asserts that a
padded ` 2 ` is still a length. The five that exposed the bug failed first;
all pass. The live probe now answers every malformed form with a single
400. A correctly framed body followed by a second request still gets two
answers, which is ordinary pipelining. `sh scripts/gates.sh`: every gate
green except white-label, which fails only on the foreign `sage-demo.json`
(§14).

### 16.43 The remediation queue was upside down on both new stores

**Failure.** The dashboard's `api.js` was read against a MariaDB-backed
`ironclad serve` (a scratch 10.11 server) and against a volume, then diffed.
The cards matched but the remediation queue did not. The engine's plan, for
the example evidence, leads with **CC6.7, critical, score 7.5**. Both
stores put it **last** and led with medium items scoring 2.0–2.8. The two
stores also disagreed with each other on the order within a tie. `api.js`
asks for 50 items, so on a larger plan the critical items would not have
reached the page at all, and `?limit=5` returned the five least urgent. The
retired Firestore path orders `priority` descending (`auth.js`) and was right;
this is a regression introduced by the persistence seam.

**Root cause.** Two compounding faults, found by comparing stores rather than
by reading. (1) `rows.py` projected the engine's float score
(`priority_score`: "higher is more urgent") through `int()`, and
`schema.sql` held it in an `INT`. 7.5 became 7 and 2.83 became 2, which
erased most of the ranking. (2) Both `FileResultStore.list_remediation` and
MariaDB's `list_remediation` / `get_document` sorted it **ascending**, with
different tie-breaks (document order vs. `item_id`, a hash).

**Fix.** The score is stored as the engine wrote it (`round(float, 3)`,
`DECIMAL(8,3)`). Both stores order by the plan's own rule, `priority DESC,
control_id` (`RemediationPlan.ordered`). The rebuild in `get_document` no
longer truncates.

**Validation.**
- A new `StoreContract` test asserts the queue is the plan's order and
  score, and that `limit=2` returns the plan's first two. It fails on both
  backends first and passes after the fix: volume in the suite, MariaDB with
  `IRONCLAD_TEST_DSN` against the scratch 10.11 server, where all store tests
  pass.
- A new `api.test.js` case asserts, through a real `ironclad serve`, that
  the queue is descending, that the score is not an integer, and that
  `limit=1` is the most urgent. It fails without the store fix.
- `scripts/end_to_end.py` passes against both stores.
- The dashboard's rendering of the same assessment is now byte-identical
  from the two stores, and leads with CC6.7.

**For a database initialised before this change.** `CREATE TABLE IF NOT
EXISTS` does not alter an existing column. HANDOFF records none outside
throwaways, but one would need:
`ALTER TABLE remediation_items MODIFY priority DECIMAL(8,3) NOT NULL DEFAULT 0;`
followed by a re-publish of each tenant's latest assessment.
Without that, MariaDB rounds the score into the INT column and the order is
coarse but no longer inverted.

**On the way.** An inline comment added to `schema.sql` carried a `;`, and
`statements_in` splits on it. The existing schema tests caught it at once.

### 16.44 A burst of connections waited for a retransmit; concurrent health checks said 503

**Failure 1: the listen backlog.** Looking for the §16.41 intermittent
failure: `serve()` built a stock `ThreadingHTTPServer`, whose
`request_queue_size` is 5 (from `socketserver`). Measured against a live
server on 2026-09-23, with simultaneous `GET /api/v1/health`:

| backlog | 20 at once | 100 at once |
|---|---|---|
| 5 | 12 of 20 took ≥1 s, worst 3.1 s | 80–92 of 100 ≥1 s, worst 8 s, up to 10 timeouts at a 10 s limit |
| 128 | worst 0.05 s | worst 0.66 s, none ≥1 s |

**Root cause 1.** Connects beyond the backlog had their SYNs dropped. Each
client waited for its own retransmit, 1 s and then 3 s later. That is
multi-second stalls for a burst of dashboard users. It is also the probable
cause of §16.41: the twenty-at-once test opens twenty connections with a 5 s
client timeout, and the next retransmit step lands past it. That test was not
caught failing in three further full runs. What was reproduced is the
mechanism: with backlog 5, 16–17 of 40 simultaneous requests failed outright
on the 5 s timeout.

**Fix 1.** `serve()` returns `_Server`, a `ThreadingHTTPServer` with
`request_queue_size = 128` (the kernel caps it at `net.core.somaxconn`,
4096 here) and daemon threads, as before.

**Failure 2, found by the fix's own test.** With the backlog raised, every
request was fast, but 15 of 40 simultaneous `/health` calls answered
**503**. A load balancer probing from several nodes would take a healthy
server out of rotation.

**Root cause 2.** `FileResultStore.health()` wrote and then unlinked one
shared file, `.ironclad-write-probe`. When two checks overlapped, one
unlinked the other's file, and the loser's `unlink()` raised
`FileNotFoundError`, which was reported as "not writable". MariaDB's check
is read-only and has no such race.

**Fix 2.** One probe name per check (`uuid4`).

**Validation.**
- `test_a_burst_of_connections_is_not_made_to_wait_for_a_retry`: 40
  simultaneous requests all answer 200, and at most 2 take ≥1 s, against
  about 25 with backlog 5. It fails with backlog 5 (only 23 of 40 even
  complete) and with the shared probe name (503s). It passes with both fixes.
- The StoreContract test `test_health_asked_at_once_is_still_healthy` runs
  8 threads × 20 checks. It fails on the volume store first and passes on
  both stores, MariaDB against the scratch 10.11 server.
- `sh scripts/gates.sh`: every gate green except white-label, which fails
  only on the foreign `sage-demo.json` (§14).

### 16.45 On MariaDB, every open item looked newly raised on every run

**Failure.** §16.35 made an open remediation item keep its first-raised date
across assessments, so overdue and age are real. The pipeline does it by
planning each run against the previous stored document (`ironclad store
latest` → `assess --previous`). On 2026-09-23 the same first assessment was
published to a volume and to a scratch MariaDB 10.11, and a second
assessment was planned against each:

| previous from | open items keeping their first-raised date |
|---|---|
| volume | 27 of 27 |
| MariaDB | **0 of 27** |

**Root cause.** `MariaDBResultStore.get_document` rebuilds the document from
rows and returned nine fields per remediation item. `created_at` was not
among them, and `carry_forward` reads it. The column had been stored all
along (`rows.py`). The same rebuild also dropped `modules_run`, which
`compare` reads to tell "planned, nothing open" from "never planned". A run
with nothing open would therefore read as one that never planned
remediation. Found by diffing the two stores' `get_document` output field by
field, then checking each missing field against what its consumers read.

**Fix.** `get_document` returns what the rows already hold: each item's
`created_at`, `guidance`, `evidence_gap`, `exception_id` and `source`, and
the run's `modules_run`, `failed_modules` and `warnings` (JSON text parsed
back). Still not rebuilt: the audit chain, findings, and per-control
rationale, notes and evidence links. Neither consumer reads them, and they
are available through their own reads.

**Validation.** Two StoreContract tests fail on MariaDB first and pass on
both stores:
- `carry_forward` over the stored document keeps every item's first-raised
  date.
- A run that planned remediation with nothing open keeps its `modules_run`.

All 87 store tests pass against the volume and the scratch MariaDB. The live
reproduction now keeps 27 of 27. `sh scripts/gates.sh`: every gate green
except white-label, which fails only on the foreign `sage-demo.json` (§14).

### 16.46 The dashboard's due date could be a day earlier than the report's

**Failure.** The plan reaches a client four ways, and they were checked
against each other on 2026-09-23:
- **Order:** the engine's plan, the HTML report, and both CSVs (plain export
  and package) agree, as does the control register's status for all 33
  controls.
- **Dates:** the dashboard disagreed. The report and CSV print a due date as
  its **UTC** day (`due_date.date()`). The card printed
  `toLocaleDateString()`, the **browser's** day. A due date of
  `2026-10-07T02:00Z` is 7 Oct in the report and 6 Oct on a New York screen.
  Due dates are the run time plus an SLA, so a pipeline run between 00:00 and
  04:00 UTC (evening on the US east coast) moves every date on the card a day
  earlier than the deliverable the client holds.
- **Overdue:** the card exempted only `complete`. The engine's
  `RemediationPlan.overdue` also exempts `risk_accepted`. Nothing sets that
  status on an item today, so this one is latent; it was aligned while the
  function was open.

**Fix.** The card formats the due date with `timeZone: "UTC"` and exempts
the same statuses as the engine. The overdue test itself still compares
against now, deliberately: the card is live, and the report is as of its
issue.

**Validation.** Two `render.test.js` cases fail first and pass after the
fix. One pins the timezone to America/New_York and asserts the report's day
appears and the local day does not; the other covers `risk_accepted`. The
dashboard suite passes under the default timezone, Pacific/Auckland and
America/Los_Angeles, apart from the two foreign `sage-demo.json` failures.
`sh scripts/gates.sh`: every gate green except white-label, which fails
only on `sage-demo.json` (§14).

### 16.47 The auditor package promised checks an auditor could not make

**Failure.** On 2026-09-23 the package's own `README.txt` was followed claim
by claim with standard tools and nothing from this repository:
- **Checksums:** `sha256sum -c SHA256SUMS` reads OK on every line. ✔
- **Evidence index:** all 37 items carry a SHA-256. ✔
- **Audit trail:** "each entry carries the digest of the one before it."
  ✘ The digest covers nine fields. `audit-trail.csv` carried six plus
  `hash`, with no `prev_hash`, `tenant_id` or `metadata`. Nothing in the
  package said how a digest is computed. The chain was sound (it recomputes
  from `assessment.json` to `package.json`'s head), but only for someone
  who had read `ironclad/model/audit.py`.
- **Report:** "report.html is the deliverable as issued." ✘ unless
  `--report` is passed. Both pipelines pass it. A manual
  `export --format package` re-rendered the report instead, and the stored
  result has no display name, so the re-render addressed the client as
  `acme-corp` ("prepared for acme-corp") where the issued report said
  "Acme Corp". It was labelled "as issued" regardless.

**On the way.** Writing the rule down exposed a trap. The engine hashes with
Python's `json.dumps` default, which escapes non-ASCII as `\uXXXX`. An
auditor re-implementing in `jq` or JavaScript writes raw UTF-8, gets a
different digest for any event naming "Müller" or carrying an em dash, and
would call an intact trail tampered with. `scope.excluded` events carry the
client's own justification text and an approver's name, so this is ordinary
input.

**Fix.**
- `audit-trail.csv` gains `tenant_id`, `prev_hash` and `metadata` (canonical
  JSON), after `hash`, so no existing column moves.
- The package README states the rule: the fields, sorted keys, compact
  separators, `\uXXXX` escaping, UTF-8, and a genesis of 64 zeros.
- With no issued report, `package.json` has `"report": "re-rendered"`, the
  README says the file is not the issued one and names the client by id, and
  the CLI warns. With one, `"report": "issued"` and the wording is unchanged.
- The product README's package table says the same.

**Validation.**
- A new test does the auditor's check using only `csv`, `json` and
  `hashlib` and the README's stated rule: it recomputes the chain from the
  CSV to `package.json`'s head, including an event with non-ASCII text, and
  a one-cell edit breaks it. It fails first.
- The issued-report test now asserts provenance both ways. The CLI test
  asserts the warning and fails without the change.
- A real CLI-built package verifies the same way, and its issued report is
  byte-identical to the file issued.
- `sh scripts/gates.sh`: every gate green except white-label, which fails
  only on the foreign `sage-demo.json` (§14).

### 16.48 A plain copy made two-year-old evidence current, without a word

**Failure.** With no manifest, `manifest_from_directory` dates each item by
its file's modification time (`st_mtime`). On 2026-09-23 the five sample
documents were given a March 2024 timestamp and assessed, then copied with a
plain `cp -r` and assessed again:

| same documents | readiness | stale | warnings |
|---|---|---|---|
| timestamps kept | 35.2% | 5 of 5 | none |
| after `cp -r` | **46.5%** | **0 of 5** | none |

**Root cause.** An mtime records when a file last landed somewhere, not when
the document was produced. Anything that does not keep timestamps (`cp`
without `-p`, most uploads, most downloads) resets every document's age.
Neither the result nor the contract said the dates were file timestamps.
The pipelines are not exposed on the evidence path: `ironclad evidence stage`
uses `copy2`, and assessment runs in the job that staged. The exposure is
what a client or operator does to the folder before that.

**Fix.** The fallback stays, because its absence would block every client
without a manifest. What changes is disclosure:
- `collect_from_directory` adds a caveat to any manifest-less folder that
  holds evidence. It reaches `result.warnings`, and so the report's
  "Assessment caveats" and the dashboard card.
- `docs/ingestion-contract.md` says how undated evidence is dated and what
  breaks it.

**For Bill.** Every report built from a folder without a manifest, including
the dry run on the sample evidence, now carries this caveat. It is accurate.
Whether to push clients towards manifests is a commercial call.

**Validation.** A new test fails first and passes now. Two more confirm a
manifest-dated folder and an empty folder stay silent. Four existing tests
that pinned the complete warning list for manifest-less folders now compare
the list less this one note, so each still checks everything it did. The
copied-folder assessment carries the caveat in `assessment.json` and in
`report.html`. `scripts/end_to_end.py` passes. `sh scripts/gates.sh`:
every gate green except white-label, which fails only on the foreign
`sage-demo.json` (§14).
