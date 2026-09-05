# STATUS — Ironclad Compliance productization

**Branch:** `productize/ironclad-compliance` · **Updated:** 2026-09-05
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
| Tenancy, RBAC, service API | **DONE, tested** | `ironclad/model/tenant.py`, `ironclad/api/` |
| GitHub workflows | **DONE; `ci.yml` green on this branch, the other two not executed** | `.github/workflows/` |
| Jenkins pipeline | **DONE, not executed on an agent** | `Jenkinsfile` |
| Cloud Functions | **DONE, not deployed** | `functions/` |
| Firestore rules | **DONE, not deployed, not emulator-tested** | `firestore.rules` |
| Dashboard | **DONE, not deployed** | `dashboard/public/` |

## Gate results

Run on this branch, this machine, 2026-09-05.

| Gate | Command | Result |
|---|---|---|
| Format | `ruff format --check .` | **PASS** — 54 files |
| Lint | `ruff check .` | **PASS** |
| Typecheck | `mypy` | **PASS** — 53 source files |
| Test | `pytest --cov=ironclad` | **PASS** — 237 passed, 90% coverage |
| Artifacts | `python scripts/validate_artifacts.py` | **PASS** — 13/13 |
| Build | `python -m build` | **PASS** — sdist + wheel |
| Security — dependencies | `pip-audit -r requirements*.txt` | **PASS** — no known vulnerabilities |
| Security — secret literals | CI shell check | **PASS** — no credential-shaped literals |
| Security — white-label | CI shell check | **PASS** — no tool names on a client surface |
| Security — static analysis | `bandit` | **NOT RUN — see below** |

Three of the four security checks run here and pass. `pip-audit` is scoped to
`requirements.txt` and `requirements-dev.txt` rather than the whole environment,
which is both more correct — it audits what this repository declares — and what
made it runnable on this machine, where an unrelated locally-installed package
had been aborting the whole-environment scan.

**`bandit` did not run and is not being reported as green.** It will not install
into this externally-managed Python (PEP 668). That is a fault of the machine,
not of this repository, and it is also not evidence that this repository is
clean. The Jenkins pipeline reports exactly this state as UNAVAILABLE and marks
the build unstable rather than passing it silently, and `ci.yml` runs it in a
clean container — so the PR check is the first real bandit result.

A manual review stands in its place: report rendering escapes every interpolated
value; workflow inputs reach shell through the environment rather than string
interpolation; the one `urllib` call takes an operator-supplied endpoint from a
secret, never from user input.

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

**Not proven — needs a GitHub runner:**

The two workflows have never executed. Their YAML parses and the framework
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

Nothing is deployed. `firestore.rules` has never been exercised against the
emulator, the Cloud Functions have never run, and the dashboard has never been
served. The rules' role-gating of the evidence index and audit trail depends on
`functions/exchange.js` minting a `roles` claim, and that pairing is untested.

## Blocked

**`GITHUB_DISPATCH_TOKEN` is not provisioned.** `functions/trigger.js` needs a
GitHub token with `actions:write` on `IronCityIT/ironclad-compliance` to start
an assessment from the dashboard. It is not on the approved ICIT secret list, so
no value was invented — the function references the name and will not deploy
until the secret exists in Secret Manager (us-east5). Everything else works
without it; only the dashboard's "Start assessment" button depends on it.

## Exact next command

```sh
git checkout productize/ironclad-compliance

# 1. push and open the PR (not yet done — awaiting the go-ahead)
git push -u origin productize/ironclad-compliance

# 2. watch CI, which is the first real run of the consensus contract fix
gh run watch -R IronCityIT/ironclad-compliance

# 3. dry-run the assessment workflow against a throwaway client before
#    anything touches a real one
gh workflow run "Compliance Assessment" \
  -R IronCityIT/ironclad-compliance \
  -f client_id="icit-internal" \
  -f framework=soc2 \
  -f evidence_path=gs://ironclad-evidence/icit-internal/
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
   `ironclad/model/evidence.py::VALIDITY_DAYS`.
6. **The legacy `scripts/*.py` are now thin wrappers.** They keep the flags the
   old workflow passed. If nothing outside this repo calls them, they can go.

## Note on the old scripts

`scripts/assess_controls.py`, `generate_report.py`, `check_framework_updates.py`
and `store_results.py` all still exist and still take the arguments they always
took. Their logic moved into the package; the files are wrappers. Nothing that
called them before needs to change.
