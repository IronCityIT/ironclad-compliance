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
