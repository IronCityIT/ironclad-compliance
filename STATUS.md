# STATUS — Ironclad Compliance productization

**Branch:** `productize/ironclad-compliance` · **Updated:** 2026-09-06
**PR [#4](https://github.com/IronCityIT/ironclad-compliance/pull/4) is open. CI green.**
**Scope posture: REVIEW ONLY. Nothing merged. Nothing deployed.**

`ironclad-compliance` is not listed in any tier in `CLAUDE.md`, and the fallback
rule is "treat as HANDS OFF and ask Bill". Asked, and directed to take the
REVIEW ONLY posture: build, run the gates, open a PR, stop there. No merge, no
deploy, no `workflow_dispatch` fired against a real client.

## Phase state

| Phase | State | Where |
|---|---|---|
| Read the existing code, reconcile findings | **DONE** | `PRODUCTIZE_NOTES.md` |
| Controls / evidence domain model | **DONE, tested** | `ironclad/model/` |
| Frameworks: NIST CSF 2.0, PCI DSS 4.0, HIPAA added | **DONE, validated** | `frameworks/` |
| Crosswalks, 94 mappings | **DONE, every edge verified against real controls** | `frameworks/crosswalks/` |
| Ingestion contract v1.0 | **DONE, tested** | `ironclad/ingest/`, `docs/ingestion-contract.md` |
| Modular capabilities + registry | **DONE, tested** | `ironclad/modules/`, `ironclad/registry.py` |
| Remediation planning | **DONE, tested** | `ironclad/model/remediation.py` |
| Exceptions / risk acceptance | **DONE, tested** | `ironclad/model/exception.py` |
| Audit trail (hash-chained) | **DONE, tested** | `ironclad/model/audit.py` |
| Reports, exports, auditor package | **DONE, tested** | `ironclad/report/` |
| Assessment types actually shaping the deliverable | **DONE, tested** | `ironclad/report/views.py` |
| Standards-vs-ICIT-policy disclosure | **DONE, tested** | `ironclad/method.py` |
| Tenancy, RBAC, service API | **DONE, tested** | `ironclad/model/tenant.py`, `ironclad/api/` |
| GitHub workflows | **DONE; `ci.yml` green on this branch, the other two not executed** | `.github/workflows/` |
| Jenkins pipeline | **DONE, not executed on an agent** | `Jenkinsfile` |
| Cloud Functions | **DONE, decisions tested, not deployed** | `functions/`, `functions/test/` |
| Firestore rules | **DONE, emulator-tested, not deployed** | `firestore.rules`, `tests/rules/` |
| Dashboard | **DONE, rendering tested, not deployed** | `dashboard/public/`, `dashboard/test/` |

## Gate results

Run on this branch, this machine, 2026-09-06.

| Gate | Command | Result |
|---|---|---|
| Format | `ruff format --check .` | **PASS** — 63 files |
| Lint | `ruff check .` | **PASS** |
| Typecheck | `mypy` | **PASS** — 61 source files |
| Test | `pytest --cov=ironclad` | **PASS** — 367 passed, 91% coverage |
| Cloud Functions | `npm --prefix functions test` | **PASS** — 44 passed |
| Dashboard | `npm --prefix dashboard test` | **PASS** — 38 passed |
| Firestore rules | `npm --prefix tests/rules test` | **PASS** — 53 passed against the emulator |
| Artifacts | `python scripts/validate_artifacts.py` | **PASS** — 13/13 |
| Catalog | `python tools/build_catalog.py --check` | **PASS** — committed catalog current |
| Build | `python -m build` | **PASS** — sdist + wheel |
| Security — dependencies | `pip-audit -r requirements*.txt` | **PASS** — no known vulnerabilities |
| Security — secret literals | CI shell check | **PASS** — no credential-shaped literals |
| Security — white-label | CI shell check | **PASS** — no tool names on a client surface |
| Security — static analysis | `bandit` | **PASS in CI** — see below |

`ci.yml` had no security gate at all when this branch started, despite
`CLAUDE.md` listing one and the Jenkins pipeline running it. It has one now, and
all four checks are green.

`bandit` cannot run on this machine — it will not install into an
externally-managed Python (PEP 668) — so its first real run was in CI, and it
**found a genuine defect**: `scripts/store_results.py` passed an
operator-supplied endpoint to `urllib.request.urlopen`, which honours `file://`.
A mistyped or tampered endpoint would have read a local file and reported it as
an HTTP response. Rewritten onto `http.client`, which speaks only HTTP, so the
risk is structurally absent rather than checked. That rewrite also caught a
second bug: the old code inferred success from "no exception raised", so a 204 or
a 302 from a misconfigured ingest would have been recorded as stored.

`pip-audit` is scoped to `requirements.txt` and `requirements-dev.txt` rather
than the whole environment — more correct, since it audits what this repository
declares, and it is also what made it runnable here, where an unrelated
locally-installed package had been aborting the whole-environment scan.

## CI

Green on `productize/ironclad-compliance` as of run
[34066964922](https://github.com/IronCityIT/ironclad-compliance/actions/runs/34066964922)
and on PR #4 as of run
[34066968364](https://github.com/IronCityIT/ironclad-compliance/actions/runs/34066968364):
Quality gates (3.10) ✅ · Quality gates (3.12) ✅ · Security gate ✅

`ci.yml` now also runs a **Cloud Functions** job. `functions/` previously had no
gate but `node --check`, and no tests at all, while carrying the code that
decides which tenant a write lands in.

## What is proven, and how

**Proven by execution on this machine:**

- An end-to-end assessment: ingest a directory → 6 capabilities → scored
  assessment → remediation plan → HTML report → auditor package. Run repeatedly
  against real evidence files.
- All four frameworks load, validate, and produce keywords for every control.
- All 94 crosswalk edges point at controls that actually exist in both
  frameworks — checked by a test, not by eye.
- The consensus-engine merge path across all three states: a valid base64
  payload, an empty one (the engine's documented failure output), and garbage.
  Run by extracting the workflow step verbatim from the YAML and executing it.
- `scripts/validate_artifacts.py` rejects a prepended byte, a missing trailing
  newline, and a truncated document.
- Determinism: the same inputs produce the same readiness score across runs.
- Degradation: a capability that raises mid-run is recorded as failed, named in
  the report's caveats, and the rest of the assessment still completes.
- The three assessment types produce three different documents from one
  unchanged assessment: same evidence, identical 24.0% readiness and identical
  stored control set; 33 controls listed in the full report, 28 in the gap
  analysis, none in the readiness summary; both abridged reports state what they
  left out. The auditor package exported from the gap-only run carries all 33
  controls in `control-register.csv` and a verified audit chain.
- `ironclad report --view full` re-issues a stored gap-only assessment as the
  complete report without re-running anything.
- Every control id in all four shipped frameworks (126 of them) is usable as a
  stored document id — checked, not assumed, and a framework carrying one that
  is not now fails validation with the control named, rather than losing that
  control at storage time behind a 200.
- `firestore.rules` executed against the Firestore emulator, both directions:
  a tenant reads its own record and an auditor sees the evidence index, while a
  tenant cannot reach another tenant's documents by any of seven paths, cannot
  list the client collection, and no role can write anywhere. 53 cases.
  Verified by mutation rather than by a green tick: replacing `ownsTenant` with
  `return true` fails 17 of them, so the suite is checking the partition rather
  than agreeing with it.
- Every field the dashboard takes from a record is escaped before it reaches the
  page — asserted field by field over every render path, not read for. Two were
  not: the "N of M evidence items are out of date" banner and the framework
  option's control count. Both were counts, which is why nobody looked at them,
  and neither is guaranteed to be a number — `storeAssessmentResults` copies
  `body.summary` verbatim and `catalog.json` is fetched over the network. A
  crafted record put script into a client's compliance dashboard. Both fixed.
- The report and the stored record both state, rule by rule, whether a bar came
  from the framework or from Iron City — generated from the constants the engine
  applies, so the disclosure cannot describe a rule that changed in the code.
- The tenant slug is byte-identical between `ironclad.ids.slugify` and
  `functions/core.js::toClientId` over a shared table of 21 cases, including
  traversal and reserved-name inputs. A disagreement there writes a client's
  results to a document their dashboard does not read.

**Not proven — needs a GitHub runner:**

`ci.yml` runs green on this branch. The two *product* workflows have never
executed. Their YAML parses and the framework
choices are checked against the loader by a test, but no run has fetched
evidence from GCS, called `consensus-engine`, or posted to the ingest function.
The consensus contract fix is the highest-value untested path: it is the reason
this branch exists, and CI on the PR is the first time it runs for real.

**Not proven — needs a Jenkins agent:**

`Jenkinsfile` is syntactically balanced and its gate commands are the same ones
run by hand above, but the pipeline has not run on an agent. The two credential
ids it binds (`ironclad-store-results-url`, `ironclad-ingest-api-key`) do not
exist yet.

**Not proven — needs GCP:**

Nothing is deployed. The Cloud Functions have never *run* and the dashboard has
never been served against a live project.

`firestore.rules` is no longer in this list: it is executed against the emulator
by `tests/rules`, as its own CI job. What remains unproven there is the pairing
with `functions/exchange.js` — the rules are tested against the claims that
function is supposed to mint, and the minting itself still needs a live Auth0
token to prove end to end. The claim shapes it produces are unit-tested; the
round trip is not.

What is now proven about the functions is their decisions, not their execution:
`functions/core.js` holds the tenant slug, the document-id check, the ingest
authorization and the evidence-path check, with no firebase imports, and
`functions/test` covers every branch. Three defects it found and fixed:

1. **The ingest failed open.** An unset `INGEST_API_KEY` was treated as "open by
   config", so a deploy that never bound the secret would have left an
   unauthenticated endpoint able to create or overwrite an assessment in *any*
   tenant — the `client_id` comes from the request body. A missing key now
   refuses every write (503) instead of accepting anyone's.
2. **The evidence-path check was a containment test.** `gs://bucket/acme/../beta/`
   contains `/acme/` and so passed, pointing a run at another tenant's evidence
   while filing the result under the caller's. The prefix is now checked
   structurally: the client id must be the first object segment and no segment
   may be empty or relative.
3. **Payload-supplied ids went into Firestore paths unchecked.** An
   `assessment_id`, remediation `item_id` or audit `event_id` containing `/`
   addressed a different collection — a path `firestore.rules` does not match,
   so the record would have been written where nothing can read it. Ids are now
   checked; the assessment id is refused rather than rewritten, because a
   sanitized substitute silently splits a re-run into a second record.

## Blocked

**`GITHUB_DISPATCH_TOKEN` is not provisioned.** `functions/trigger.js` needs a
GitHub token with `actions:write` on `IronCityIT/ironclad-compliance` to start
an assessment from the dashboard. It is not on the approved ICIT secret list, so
no value was invented — the function references the name and will not deploy
until the secret exists in Secret Manager (us-east5). Everything else works
without it; only the dashboard's "Start assessment" button depends on it.

## Exact next command

The branch is pushed and PR #4 is open with CI green. What remains needs
something this machine does not have.

```sh
# 1. review the PR
gh pr view 4 -R IronCityIT/ironclad-compliance --web

# 2. dry-run the assessment workflow against a throwaway client before
#    anything touches a real one. NOT run: firing it needs the GCS evidence
#    bucket and the ingest secrets, and it is a real dispatch, which the
#    REVIEW ONLY posture does not cover.
gh workflow run "Compliance Assessment" \
  -R IronCityIT/ironclad-compliance \
  -f client_id="icit-internal" \
  -f framework=soc2 \
  -f evidence_path=gs://ironclad-evidence/icit-internal/

# 3. the rules suite, if you want to see it locally (CI runs it every push)
npm --prefix tests/rules ci && npm --prefix tests/rules test
```

## Open decisions

1. **Merge and deploy?** This branch stops at the PR under the REVIEW ONLY
   posture. Moving `ironclad-compliance` to IN SCOPE in `CLAUDE.md` is the
   decision that unblocks merge and deploy, and it is not one to make silently.
2. **Provision `GITHUB_DISPATCH_TOKEN`?** Without it the dashboard renders and
   reads results but cannot start an assessment.
3. **Provision `STORE_RESULTS_URL` and `INGEST_API_KEY`?** `store_results.py`
   prints the record instead of posting when the endpoint is unset, so the
   pipeline runs without them — it just does not publish.
4. **Is the corroboration rule right for the business?** Two independent items
   before a control reads as met is an auditor's bar, and it will make early
   client reports look worse than the tools they are replacing. That is
   deliberate, but it is a commercial call, not a technical one.
5. **The freshness windows are ICIT policy, not standard.** 90 days for an
   access review, 365 for a policy, 30 for a scan. They are the numbers most
   likely to need arguing with a real auditor. They live in one dict —
   `ironclad/model/evidence.py::VALIDITY_DAYS`. Every report and every stored
   record now carries a *Basis of assessment* block that says so explicitly,
   rule by rule, generated from the constants the engine applies
   (`ironclad/method.py`). The decision is still open; what is no longer open is
   whether a client can tell which bars are ours.
6. **The legacy `scripts/*.py` are now thin wrappers.** They keep the flags the
   old workflow passed. If nothing outside this repo calls them, they can go.

## Note on the old scripts

`scripts/assess_controls.py`, `generate_report.py`, `check_framework_updates.py`
and `store_results.py` all still exist and still take the arguments they always
took. Their logic moved into the package; the files are wrappers. Nothing that
called them before needs to change.
