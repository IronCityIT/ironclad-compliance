# Ironclad Compliance — developer handoff

**Written:** 2026-09-07 · **Branch:** `productize/ironclad-compliance` ·
**Open PR:** [#4](https://github.com/IronCityIT/ironclad-compliance/pull/4) ·
**Head at writing:** `26d0867`

This document is meant to be portable: someone with this file, the repository and
no other context should be able to pick the product up. It is written for a
successor, not for a reviewer.

## How to read the labels

Every claim carries one:

| Label | Means |
|---|---|
| **VERIFIED** | Observed in this repository or executed and its output seen. The evidence is named. |
| **TARGET** | The architecture we are moving to. Not built, not deployed. |
| **UNKNOWN** | Not established. Written down as unknown rather than guessed. |

Nothing here is inferred from a document written by someone else and repeated as
fact. Where the only source is another document, it says so.

---

## 1. Purpose

**VERIFIED.** Ironclad Compliance assesses a client's evidence against a
compliance framework and produces the deliverables a compliance programme runs
on: a scored readiness position, a control-by-control register, a prioritised
remediation plan with target dates, and an auditor evidence package.

It is an *evidence engine*, not a scanner. It reads documents the client already
has — policies, access reviews, scan output, meeting minutes — decides which
controls they support, and says what is missing. Four frameworks ship, with
crosswalks between them so a client evidences a control once.

What it deliberately does not do: invent controls, move a score with AI
commentary, or accept a risk on a client's behalf.

---

## 2. Current implementation — VERIFIED

Everything in this section was executed on the build container, or is present in
the repository and covered by a test that runs in CI.

### 2.1 Shape

```
ironclad/          the engine. Python 3.10+, standard library only at its core
  model/           controls, evidence, assessment, remediation, exceptions, audit, tenancy
  modules/         seven capabilities, one per file, discovered by a registry
  frameworks/      loader, crosswalks, quarterly update checker
  ingest/          the versioned evidence contract, collectors, extractors
  report/          HTML render, exports, auditor package, per-type views
  api/             request/response schemas, ComplianceService, PolicyStore
  method.py        which bars are the framework's and which are Iron City's
  cli.py           every surface drives the engine through here
frameworks/        four framework definitions + crosswalks, as JSON
functions/         Cloud Functions — SEE SECTION 4, these are being retired
dashboard/         static dashboard — SEE SECTION 4, its backend is being retired
tests/             390 Python tests
scripts/, tools/   pipeline wrappers and generators
```

Line counts: engine ~3,200; total Python under test 2,563 statements at 91%
coverage.

### 2.2 Capabilities

Seven, selected individually (`--modules a,b,c`) or by group (`--group deep`).
The registry is the single catalog behind the CLI and the dashboard, so a
selection maps 1:1 on both.

| capability | quick | standard | deep |
|---|:-:|:-:|:-:|
| `evidence_inventory` | ● | ● | ● |
| `control_mapping` | ● | ● | ● |
| `exception_review` | | ● | ● |
| `freshness_check` | | ● | ● |
| `remediation_plan` | | ● | ● |
| `scope_review` | | ● | ● |
| `crosswalk_coverage` | | | ● |

### 2.3 Frameworks

| alias | framework | controls |
|---|---|---|
| `soc2` | SOC 2 Trust Service Criteria 2017 | 33 |
| `nist-csf` | NIST Cybersecurity Framework 2.0 | 43 |
| `pci-dss` | PCI Data Security Standard 4.0 | 27 |
| `hipaa` | HIPAA Security Rule 45 CFR 164 Subpart C | 23 |

94 crosswalk edges. Every edge is checked by a test to point at a control that
exists in both frameworks.

### 2.4 What has been executed, and the evidence

| Claim | Evidence |
|---|---|
| End-to-end assessment: ingest a directory → 7 capabilities → scored assessment → remediation plan → HTML report → auditor package | Run repeatedly on the build container against real evidence files; last run `acme-corp-soc2-tsc-20260907004327` |
| Assessment type shapes the deliverable without changing the assessment | Three runs, same evidence: identical 24.0% readiness and identical stored controls; 33 / 28 / 0 controls listed in full / gap-only / readiness |
| Risk-acceptance workflow end to end | request → self-approval refused → viewer refused → approved → next assessment moved CC1.2 from `gap` to `accepted_risk`, readiness 24.0% → 25.3%, 28 → 27 remediation items |
| `firestore.rules` enforces tenant isolation | 53 cases against the Firestore emulator, and a mutation check: replacing `ownsTenant` with `return true` fails 17 of them |
| Cloud Function decisions | 44 node tests over `functions/core.js` |
| Dashboard escaping | 38 node tests, field by field over every render path |
| Tenant slug identical in Python and JavaScript | 21-case table run through both implementations |
| All 126 shipped control ids are usable as document ids | Test over all four frameworks |

### 2.5 Gates, and their last results

Run on the build container 2026-09-07 at `26d0867`, and in CI on every push.

| Gate | Command | Result |
|---|---|---|
| Format | `ruff format --check .` | PASS — 65 files |
| Lint | `ruff check .` | PASS |
| Typecheck | `mypy` | PASS — 63 source files |
| Test | `pytest` | PASS — 390 passed, 91% coverage |
| Cloud Functions | `npm --prefix functions test` | PASS — 44 passed |
| Dashboard | `npm --prefix dashboard test` | PASS — 38 passed |
| Firestore rules | `npm --prefix tests/rules test` | PASS — 53 passed against the emulator |
| Artifacts | `python scripts/validate_artifacts.py` | PASS — 13/13 |
| Catalog | `python tools/build_catalog.py --check` | PASS |
| Build | `python -m build` | PASS in CI |
| Security | `pip-audit`, `bandit`, secret-literal scan, white-label scan | PASS in CI |

CI run [34070268095](https://github.com/IronCityIT/ironclad-compliance/actions/runs/34070268095):
Quality gates (3.10) ✅ · Quality gates (3.12) ✅ · Cloud Functions and dashboard ✅ ·
Firestore rules ✅ · Security gate ✅

---

## 3. Target architecture — TARGET

Directed 2026-09-07: **Firebase, Firestore, Firebase Hosting and GCP product
storage are retired from the target architecture.** They are not to be preserved
or extended.

```
GitHub Actions                     execution and orchestration
  └─ consensus-engine (workflow_call)          AI analysis, unchanged
  └─ publish step
       └─ ICIT NAS-backed service
            ├─ MariaDB          relational state: assessments, controls,
            │                   remediation, exceptions, audit, tenants
            └─ NAS volume       object/artifact files: reports, evidence
                                references, auditor packages
```

Properties that must survive the migration, each of which exists today and is
tested:

- **Tenant isolation.** Every row carries a tenant id; no query path crosses it.
- **RBAC.** Five roles, permissions in one matrix, separation of duties on risk
  acceptance.
- **Auditability.** Hash-chained trail; altering an event breaks every digest
  after it.
- **Secrets hygiene.** Referenced by name, never by value, never committed.
- **Fail-closed.** A missing key refuses writes; a missing tenant refuses reads.
- **Backups and recovery.** See §13.

### 3.1 What is known about the target substrate

| Fact | Label | Evidence |
|---|---|---|
| `qnap-nas-01` is at 192.168.1.177, on-premises QNAP | VERIFIED (from `ICIT-Infrastructure/hosts/qnap-nas-01/README.md`) | that document |
| **MariaDB 10.5.8 is listening on 192.168.1.177:3306** and reachable from this build container | **VERIFIED 2026-09-07** | TCP connect succeeded; the server handshake banner reads `5.5.5-10.5.8-MariaDB-log` |
| Credentials for that MariaDB | **UNKNOWN** | none available; nothing was attempted beyond reading the unauthenticated handshake |
| Whether a database/schema for this product exists there | **UNKNOWN** | cannot be determined without a credential |
| SSH to `qnap-nas-01` | **BLOCKED** | `ICIT-Infrastructure` records `Permission denied (publickey,password,keyboard-interactive)` for both `admin` and `root`, host NOT CAPTURED. Not retried here. |
| The NAS runs Container Station, Passbolt, restic→Backblaze backups | Reported by `ICIT-Infrastructure`, **not independently verified** | that document |
| How `api.ironcityit.com` reaches an RFC1918 host | **UNKNOWN** | `ICIT-Infrastructure` records this as unresolved |
| MariaDB 10.5 series is past upstream EOL (June 2025) | VERIFIED from the banner version; upgrade path **UNKNOWN** | banner reads 10.5.8 |

### 3.2 The reachability problem — the central open question

**GitHub-hosted runners cannot reach 192.168.1.177.** It is RFC1918. This
repository has **no self-hosted runner registered** — VERIFIED:
`gh api repos/IronCityIT/ironclad-compliance/actions/runners` returns
`{"total_count":0,"runners":[]}`, and the org-level endpoint returns 404 for
this token.

So a GitHub Actions job cannot write to NAS MariaDB today. One of these has to
be true before the target architecture works, and **which one is a decision, not
a fact I can establish**:

1. **A self-hosted runner on the LAN.** The publish job runs `runs-on:
   self-hosted`, reaches MariaDB directly, and no database port is exposed
   publicly. Most secure; needs a runner host and its maintenance.
2. **A published HTTP ingest in front of MariaDB.** GitHub-hosted runners POST
   to a tunnelled endpoint, as they do today for the Cloud Function. Keeps the
   current job shape; requires the endpoint be authenticated and fail-closed,
   and puts a service on the public internet.
3. **Artifacts only, with a NAS-side poller.** The workflow uploads the
   assessment as a run artifact; something on the NAS pulls and loads it.
   Nothing inbound; adds a moving part and a delay.

Option 1 is the one that preserves the properties in §3 with the least new
attack surface. **It is not chosen — that is Bill's call**, and §16 records it as
the top blocker.

---

## 4. Firebase and GCP references — full classification

Every reference in the repository, and what should happen to it. **No file in
this section has been deleted or migrated yet** — this release is the inventory,
not the removal.

### 4.1 Target-state components to be replaced

| Path | What it is | Disposition |
|---|---|---|
| `functions/index.js` | `storeAssessmentResults` — the ingest that writes Firestore | **REPLACE** with a MariaDB writer behind the chosen transport (§3.2). Its *decisions* (`functions/core.js`) are storage-agnostic and should be carried over. |
| `functions/exchange.js` | Auth0 → Firebase custom token bridge, mints `client_id` and `roles` claims | **REPLACE.** Whatever replaces Firestore needs its own session/claim mechanism. Auth0 itself is not retired; the *Firebase* half is. |
| `functions/trigger.js` | Dashboard → GitHub `workflow_dispatch` | **KEEP THE BEHAVIOUR, MOVE THE HOST.** Dispatching a workflow is target-state; being a Cloud Function is not. Its tenant checks (`checkEvidencePath`) are storage-agnostic. |
| `firestore.rules` | Multi-tenant read rules | **REPLACE** with tenant-scoped SQL access: a per-tenant credential or a query layer that cannot emit a cross-tenant query. The 53 emulator cases are the specification of what the replacement must enforce. |
| `firebase.json`, `.firebaserc` | Firebase project and hosting config | **REMOVE** when hosting moves. Still referenced by the rules test harness today. |
| `dashboard/public/config.js` | Injects Firebase web config at deploy time | **REPLACE** the `firebase` block; the `auth0` block stays. |
| `dashboard/public/auth.js` | Firebase Auth + Firestore live queries | **REPLACE** the data layer. `app.js` — all rendering — is already backend-agnostic and needs no change. |
| `.github/workflows/compliance-assessment.yml` | Fetches evidence with `gcloud storage cp`; publishes to the Cloud Function | **MIGRATE** both ends: evidence from a NAS volume, results to MariaDB. |
| `scripts/store_results.py` | POSTs the result to the ingest endpoint | **MIGRATE.** Transport-agnostic in shape; the endpoint changes. |

### 4.2 Storage-agnostic — keep, and correct the comments

These carry the *word* Firestore in a comment or docstring but no Firebase
dependency. They work unchanged against MariaDB.

| Path | Why it is fine |
|---|---|
| `ironclad/ids.py` | Slug and document-id rules. The constraints (path-safe, no `/`, length-bounded) are good identifier hygiene for any store. Comments name Firestore and should be reworded. |
| `ironclad/model/tenant.py` | RBAC and `Principal.from_claims`. Claim *names* are Auth0's, which is not retired. Docstring names Firebase. |
| `ironclad/engine.py`, `ironclad/api/service.py`, `ironclad/api/schemas.py` | Docstrings reference the Cloud Function as the sink. The code has no cloud dependency: `Store` is a Protocol, and `PolicyStore` already implements it against the filesystem. |
| `functions/core.js` | Deliberately dependency-free: slugs, id checks, ingest authorization, evidence-path checks. **This is the piece to carry into whatever replaces the function.** |
| `ironclad/ingest/contract.py`, `collectors.py` | `gs://` appears only as an example URI. The contract already accepts any URI scheme and stores references, not bytes. |

### 4.3 Test and documentation references

`tests/rules/`, `functions/test/`, `dashboard/test/`, `README.md`,
`STATUS.md`, `PRODUCTIZE_NOTES.md`, `docs/ingestion-contract.md` describe or
exercise the current implementation. They stay accurate until the thing they
describe is migrated, and they move with it.

### 4.4 A conflict worth surfacing

`ICIT-Infrastructure/ARCHITECTURE.md` (read 2026-09-07) still documents the
Firebase/Firestore pattern as **the** ICIT standard product pattern, with
"Firestore is the store of record" stated as a rule holding across every
product. That repository is HANDS OFF under `CLAUDE.md` and was not modified.

**This is a live contradiction between the estate's architecture document and the
direction given for this product.** Until it is resolved, a reader of that
document will build the retired pattern. Flagged, not resolved — resolving it
means editing a HANDS OFF repository.

---

## 5. Data model — VERIFIED

The engine's model is already relational in shape, which is what makes the
MariaDB target a re-hosting rather than a redesign.

| Entity | Key | Notes |
|---|---|---|
| **Tenant** | `tenant_id` (slug) | Slug rules identical in Python and JS |
| **Framework** | `framework.id` + `version` | Ships as JSON, not client data |
| **Control** | `framework_id` + `control_id` | Points of focus, common evidence, family weight |
| **EvidenceArtifact** | `artifact_id` = `ev-<hash>` | Reference + SHA-256; **never the bytes** |
| **EvidenceLink** | artifact ↔ control | Method, relevance, who linked it |
| **Assessment** | `assessment_id` = `<tenant>-<framework>-<UTC stamp>` | Deterministic: a re-run addresses the same record |
| **ControlAssessment** | assessment + control | Status, rationale, points covered, confidence, weight |
| **RemediationItem** | `item_id` | Severity, priority, owner, due date, evidence gap |
| **RiskException** | `exception_id` = `ex-<hash>` | State machine; separation of duties |
| **ScopeExclusion** | tenant + control | Justification, approver, review date |
| **AuditEvent** | `event_id`, `prev_hash`, `hash` | Hash-chained per tenant |

Control statuses: `compliant`, `partial`, `gap`, `accepted_risk`,
`not_applicable`, `pending`.

**Migration note.** The audit chain is the one entity where a naive table hurts:
its integrity depends on insertion order and on `prev_hash` matching the previous
row's `hash`. In MariaDB it wants an append-only table with a per-tenant sequence
and no UPDATE grant, and `verify()` must be run over it, not trusted.

**Evidence bytes never enter the database.** Today the engine stores a URI and a
SHA-256. That must stay true: artifacts belong on the NAS volume, and the
database holds the index that proves which artifact supported which control when.

---

## 6. Execution flow — VERIFIED

```
ironclad assess
  ingest        collect_from_directory → EvidenceSet (manifest or derived, checksummed)
  policy        load policy.json → scope exclusions, risk acceptances, owners
  registry      resolve --modules/--group into an ordered capability list
  run           each capability in order; one that raises is recorded as failed
                and named in the report, and the run continues
  score         weighted readiness from the verdicts alone
  emit          out/assessment.json, out/findings.b64, out/report.html
```

Exit codes: `0` success, `2` bad input or selection, `3` a capability failed
mid-run.

In the workflow, `findings.b64` goes to `consensus-engine` via `workflow_call`
(its input is base64 and it returns exactly one output, `consensus_b64`), the
result is folded back in, and the report and auditor package are rendered. The
AI commentary never moves the score.

---

## 7. Configuration

### 7.1 Secrets — BY NAME ONLY

No value for any of these appears in the repository, and CI fails on a
credential-shaped literal.

| Name | Used by | State |
|---|---|---|
| `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY` | passed through to `consensus-engine` | on the approved ICIT list |
| `GCP_SA_KEY` | evidence fetch from GCS | **retired with the GCP path** |
| `GCS_BUCKET` | report storage | **retired with the GCP path** |
| `STORE_RESULTS_URL` | ingest endpoint | **repoints at the new sink** |
| `INGEST_API_KEY` | ingest authentication | **required** — an unset key now refuses every write |
| `GITHUB_DISPATCH_TOKEN` | dashboard-initiated assessments | **NOT PROVISIONED**, not on the approved list |
| MariaDB credential | the target store | **DOES NOT EXIST YET.** Not on the approved ICIT secret list. Must be provisioned before any migration step can run. Name not invented here. |

### 7.2 Policy that is Iron City's, not the standard's

Both are disclosed in every report and stored record (`ironclad/method.py`):

- **Corroboration: 2 independent evidence items** before a control reads as met.
  No framework requires this.
- **Freshness windows:** 30 days (scan, log, backup, monitoring), 90 (review,
  access review, ticket), 180 (meeting minutes), 365 (policy, charter, training,
  penetration test, risk assessment), 365 default.
- **Family weighting** and **status credit** (accepted risk earns 0.5).

These live in `ironclad/model/evidence.py::VALIDITY_DAYS`,
`ironclad/model/control.py::FAMILY_WEIGHT`,
`ironclad/model/assessment.py::STATUS_CREDIT`,
`ironclad/modules/control_mapping.py::CORROBORATION_MIN`.

---

## 8. Access, authentication and RBAC — VERIFIED

Five roles. The matrix is in `ironclad/model/tenant.py` and is the only place
permissions are defined.

| Role | Reads position | Reads evidence index / audit | Requests acceptance | Approves | Runs assessment |
|---|:-:|:-:|:-:|:-:|:-:|
| `owner` | ● | ● | ● | ● | ● |
| `compliance_manager` | ● | ● | ● | ● | ● |
| `contributor` | ● | | ● | | |
| `auditor` | ● | ● | | | |
| `viewer` | ● | | | | |

Rules that hold in the model, so every surface inherits them:

- **A requester cannot approve their own risk acceptance.** VERIFIED at the CLI:
  exit 2, "alice requested this exception and may not approve it".
- **The pipeline cannot approve anything.** `SystemPrincipal` lacks
  `exception:approve`.
- **An unrecognised role is dropped, never guessed** — a typo in Auth0 must not
  become a grant.
- **A policy file cannot smuggle in an approval the workflow would refuse:** the
  loader replays the state machine rather than assigning the end state.

---

## 9. Security boundaries — VERIFIED

| Boundary | How it is enforced | Proof |
|---|---|---|
| Tenant isolation at the store | `firestore.rules` today; SQL tenant scoping in target | 53 emulator cases + a mutation check |
| Ingest authentication | Fail-closed: an unset key refuses every write (503) | `functions/test`, 44 cases |
| Evidence path belongs to the caller | Structural: client id must be the first path segment, no traversal | `functions/test` |
| Payload ids cannot steer a storage path | Checked, not sanitized, for the record identity | `functions/test` + `ironclad/ids.py` |
| Client-facing HTML escaping | Every record field escaped before rendering | `dashboard/test`, 38 cases |
| No secret literal in the repo | CI grep, hard failure | Security gate |
| No underlying tool named on a client surface | CI grep over report, dashboard, catalog | Security gate |
| Publish transport | `http.client` only — `file://` is structurally impossible | `tests/test_publish.py` |

Three of these were defects found and fixed on this branch, not properties that
were always true: the fail-open ingest, the traversable evidence path, and two
unescaped dashboard fields. See `PRODUCTIZE_NOTES.md` §8 and §9.

---

## 10. Network and deployment

**VERIFIED:** nothing from this repository is deployed anywhere. No Cloud
Function has ever run, no dashboard has ever been served, no database has ever
been written.

**VERIFIED:** the repository references `.github/workflows/deploy-functions.yml`
in `functions/package.json`, and **that workflow does not exist**. There is no
deploy automation in this repository at all.

**Posture:** REVIEW ONLY. `ironclad-compliance` appears in no tier in
`CLAUDE.md`; the fallback is HANDS OFF and ask. Asked, and directed to branch,
gate, open a PR and stop. Nothing is merged, nothing is deployed, and no
`workflow_dispatch` has been fired against a real client.

---

## 11. GitHub Actions — VERIFIED

| Workflow | Trigger | State |
|---|---|---|
| `ci.yml` | push, PR | **Green.** Five jobs: quality gates ×2 Python versions, Cloud Functions and dashboard, Firestore rules, security gate. |
| `compliance-assessment.yml` | `workflow_dispatch` | **Never executed.** YAML parses; framework choices are checked against the loader by a test. |
| `framework-updates.yml` | schedule + dispatch | Last run 2026-08-29 on `main`, success. |

`compliance-assessment.yml` calls `IronCityIT/consensus-engine` by
`workflow_call`. Its real contract — read from that repository, not assumed — is
`findings_json` as **base64** and exactly one output, `consensus_b64`. This
repository previously passed raw JSON and read two outputs that do not exist, so
every assessment it ever produced analysed nothing. Fixed on this branch; the
fix has still **never run for real**, because the workflow needs evidence
storage and secrets.

---

## 12. Storage and NAS — TARGET

| Concern | Target |
|---|---|
| Relational state | MariaDB on `qnap-nas-01`, one schema, every row tenant-scoped |
| Artifacts (reports, auditor packages) | NAS-backed volume, tenant-prefixed paths |
| Evidence | NAS-backed volume; the database holds references and SHA-256 only |
| Backups | restic → Backblaze already exists on the NAS per `ICIT-Infrastructure` (**not independently verified**); the new schema and volume must be added to it |

**Built and tested (stages 1–3):** `ironclad/store/` — the `ResultStore` port,
the row projection, `schema.sql`, `MariaDBResultStore`, `FileResultStore` for
the volume, and `ironclad store health|init|publish|list`. The MariaDB half runs
in CI against a MariaDB 10.5 service container, matching the NAS server version.

**Still open:** the transport (§3.2) and the artifact layout for reports and
auditor packages on the volume. The transport decision does not change any of
the above: a self-hosted runner, an ingest service and a NAS-side loader all
call `put_assessment` with the same rows.

---

## 13. Migration away from Firebase — TARGET, staged

No stage is destructive. Each is independently reviewable, and stages 1–3 need
no credential and no deployment.

| Stage | What | Needs | Safe now? |
|---|---|---|---|
| 0 | **This document.** Classify every reference; change no behaviour. | — | ✅ done |
| 1 | Persistence port: `ResultStore`, and `rows.py` projecting a result document onto tenant-scoped records. | — | ✅ **done** |
| 2 | `schema.sql` + `MariaDBResultStore`, tested in CI against a real MariaDB 10.5 service container. | — | ✅ **done** |
| 3 | The loader: `ironclad store publish`, idempotent on `assessment_id`, plus `FileResultStore` for the NAS volume. | — | ✅ **done** |
| 4 | Choose the transport (§3.2) and wire the workflow's publish step to it. | **decision + credential** | ⛔ blocked |
| 5 | Replace the dashboard's data layer; retire `functions/`, `firestore.rules`, `firebase.json`. | stage 4 | ⛔ blocked |
| 6 | Delete the Firebase surface and its tests once nothing reads them. | stage 5 | ⛔ blocked |

**Nothing is migrated destructively.** Firestore holds no data — nothing was
ever deployed — so there is no data migration, only a code migration. That is
the one piece of luck in this changeover and it should be used: the retirement
costs no client data.

---

## 14. Tests and gates

See §2.5 for results. To run everything on a fresh checkout:

```sh
pip install -r requirements-dev.txt
ruff format --check . && ruff check . && mypy && pytest
python scripts/validate_artifacts.py
python tools/build_catalog.py --check
npm --prefix functions test
npm --prefix dashboard test
npm --prefix tests/rules ci && npm --prefix tests/rules test   # needs a JVM
```

`bandit` will not install on this build container under PEP 668; it runs in CI,
where its first run found a real defect (`file://` reachable through the publish
endpoint). Do not conclude the security gate is green from a local run.

---

## 15. Enhancements and backlog

Ordered by value, non-blocked first.

1. **Persistence port + MariaDB implementation** (§13 stages 1–3).
2. **Trend comparison between assessments** — `ironclad compare --from --to`,
   readiness movement and which controls changed. The stored record already
   supports it; nothing consumes it yet.
3. **Evidence collection from a NAS volume** rather than `gs://`.
4. **`ComplianceService` HTTP surface** — the service is complete and now has one
   caller (the CLI); an authenticated HTTP surface would give the dashboard a
   backend that is not Firebase.
5. **Framework update checker → a PR that a human reviews**, rather than a
   notification.
6. **Coverage gaps:** `ironclad/policy.py` 86%, `freshness_check` 85%.
7. **Retire the legacy `scripts/*.py` wrappers** if nothing outside this
   repository calls them.

---

## 16. Known defects and blockers

### Blockers — each recorded once, with evidence

| # | Blocker | Evidence | Effect |
|---|---|---|---|
| B1 | **The transport to NAS MariaDB is undecided.** GitHub-hosted runners cannot reach RFC1918; no self-hosted runner is registered. | `gh api .../actions/runners` → `{"total_count":0,"runners":[]}` (2026-09-07) | Migration stages 4–6 cannot start. Stages 1–3 can. |
| B2 | **No MariaDB credential.** 3306 answers; nothing can authenticate. | Handshake banner read; no credential attempted | Stage 2 needs a test database; stage 4 needs a real one. Name not invented. |
| B3 | **`qnap-nas-01` has no SSH credential.** Host NOT CAPTURED. | `ICIT-Infrastructure/hosts/qnap-nas-01/README.md`: `Permission denied (publickey,password,keyboard-interactive)` | Nothing can be provisioned or inspected on the NAS. |
| B4 | **`GITHUB_DISPATCH_TOKEN` is not provisioned** and is not on the approved ICIT secret list. | `CLAUDE.md` secret list; `functions/trigger.js` references it by name | Dashboard-initiated assessments cannot work, wherever the trigger is hosted. |
| B5 | **REVIEW ONLY posture.** | `CLAUDE.md` tiering; `STATUS.md` | No merge, no deploy, from this session. |
| B6 | **`ICIT-Infrastructure/ARCHITECTURE.md` still documents Firebase as the ICIT standard**, contradicting the direction for this product. That repo is HANDS OFF. | Read 2026-09-07 | A reader of the estate architecture will build the retired pattern. |

### Defects found and fixed on this branch

Recorded in full in `PRODUCTIZE_NOTES.md`. Summary: the consensus contract was
wrong in both directions; a failed evidence fetch produced a catastrophic client
report; the update checker could not return false; the ingest failed open; the
evidence-path check was traversable; payload ids could steer a storage path; two
dashboard fields were unescaped; the assessment type was ignored; the
risk-acceptance workflow was unreachable.

### Open questions that are decisions, not defects

1. **Corroboration at two items** will make early client reports look worse than
   the tools they replace. Deliberate; commercial call.
2. **The freshness windows are ours**, and are the numbers most likely to need
   defending with a real auditor.
3. **Merge and deploy?** Moving this repo to IN SCOPE in `CLAUDE.md` is the
   decision that unblocks it.

---

## 17. Operational runbooks

**Nothing is deployed, so no production runbook can be written honestly yet.**
What follows is what exists.

### Run an assessment locally

```sh
python -m ironclad.cli assess --client "Acme Corp" --framework soc2 \
  --evidence-dir evidence/ --group deep --policy policy.json --out out/
python -m ironclad.cli export --input out/assessment.json --format package --out out/package/
```

### Record a risk acceptance

```sh
ironclad exception request --policy policy.json --actor alice --role contributor \
  --control CC1.2 --justification "…" --expires-in-days 90
ironclad exception approve --policy policy.json --actor bob \
  --role compliance_manager --id ex-…
```
A second person must approve. The trail is `policy.json.audit.json`, hash-chained.

### Verify an auditor package

`package.json` records the chain head. Re-verify by checking each event's
`prev_hash` against the previous event's `hash`; any edit breaks every digest
after it. Evidence bytes are not in the package — verify an artifact by its
SHA-256 against `evidence-index.csv`.

### When a capability fails mid-run

Exit code 3. The assessment still completes, the failure is named in the report's
caveats and in `failed_modules`. That is deliberate: a partial assessment with a
named failure is worth more than nothing, and hiding it would be worse than
either.

---

## 18. Rollback and disaster recovery

**Code:** every change is a PR onto `main`; rollback is `git revert`. Nothing is
force-pushed. VERIFIED — 16 commits on the branch, no force pushes.

**Data:** there is none. Nothing is deployed and nothing is stored. **This is the
cheapest moment in the product's life to change its storage architecture**, and
it will not come again.

**TARGET, once MariaDB is live:**

- The schema must be in the NAS restic → Backblaze set before the first real
  write, not after.
- Restore must be tested by restoring, not by believing the backup ran.
- The audit chain gives a free integrity check on any restore: `verify()` over
  the restored trail either passes end to end or names the first broken event.
- Retention: `ICIT-Infrastructure/RETENTION.md` exists and was **not read in
  detail** for this document. Read it before designing retention here.

---

## 19. Provenance

Everything in §2 was executed on this build container or read from this
repository at `26d0867`. CI evidence is linked by run id. §3.1 facts about the
NAS come from two sources, separated: a live TCP probe from this container
(MariaDB banner), and `ICIT-Infrastructure` documents, which are cited as
documents rather than restated as verified fact.

The build container: Ubuntu 24.04 on kernel 5.10.60-qnap, hostname
`dd2032e4524d` — a Container Station container on the QNAP, with LAN access to
192.168.1.177. No `docker`, `mysql` or `psql` client is installed.

**What this document does not know**, restated so it is not mistaken for
completeness: MariaDB credentials, whether a schema exists, how
`api.ironcityit.com` reaches the NAS, the QNAP's filesystem layout, and whether
any other ICIT product has already migrated off Firebase.
