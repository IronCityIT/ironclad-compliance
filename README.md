# Ironclad Compliance

**The Iron City compliance evidence engine.** Ingest a client's evidence, map it
to a framework's controls, score readiness, and produce the remediation plan and
the auditor package — with the crosswalks that let one evidence set answer four
frameworks.

```
                      evidence manifest (contract v1.0)
                                   │
                                   ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  ironclad assess                                              │
   │                                                               │
   │   evidence_inventory ─ what arrived, what expired             │
   │   control_mapping    ─ evidence → controls → verdicts         │
   │   exception_review   ─ apply and expire risk acceptances      │
   │   freshness_check    ─ what regresses before the next audit   │
   │   crosswalk_coverage ─ project onto the other frameworks      │
   │   remediation_plan   ─ prioritised, dated work                │
   └───────────────────────────────────────────────────────────────┘
                                   │
              findings (base64) ───┴─── assessment.json + report.html
                     │                            │
                     ▼                            ▼
    IronCityIT/consensus-engine        storeAssessmentResults
      (workflow_call, AI analysis)      (Cloud Function, us-east5)
                     │                            │
                     └────── consensus_b64 ───────┤
                                                  ▼
                                    Firestore, partitioned by client_id
                                                  │
                                                  ▼
                                    Firebase dashboard, Auth0 SSO
```

## Frameworks

| Framework | Version | Controls | Status |
|---|---|---|---|
| SOC 2 Trust Service Criteria | 2017 | 33 | Active |
| NIST Cybersecurity Framework | 2.0 | 43 | Active |
| PCI Data Security Standard | 4.0 | 27 | Active |
| HIPAA Security Rule | 45 CFR 164 Subpart C | 23 | Active |

94 crosswalk mappings connect them. A SOC 2 assessment already addresses **96%**
of the HIPAA Security Rule, **82%** of PCI DSS 4.0 and **67%** of NIST CSF 2.0 —
so a client evidences a control once and sees where they stand everywhere.

```sh
ironclad crosswalk --from soc2 --to hipaa
```

## Quick start

The engine core is standard-library only. Nothing to install to run an
assessment against text evidence.

```sh
ironclad list-modules                    # the capability catalog
ironclad list-frameworks                 # what is available to assess against

ironclad assess \
  --client "Acme Corp" \
  --framework soc2 \
  --evidence-dir evidence/ \
  --group deep \
  --out out/

ironclad export --input out/assessment.json --format package --out out/package/
```

`assess` writes three files:

| File | What it is |
|---|---|
| `assessment.json` | the complete machine record |
| `findings.b64` | base64 findings, the shape `consensus-engine` takes |
| `report.html` | the client-facing readiness report |

Reading PDF, DOCX or XLSX evidence needs `pip install PyPDF2 python-docx openpyxl`.
Without them those items are catalogued and reported as unreadable rather than
silently ignored.

## Capabilities

Each capability is one file in `ironclad/modules/`. Run a named group, or pick
capabilities individually — `--modules` pulls in whatever a capability depends
on, so a selection is never quietly incomplete.

| Capability | `quick` | `standard` | `deep` |
|---|:-:|:-:|:-:|
| `evidence_inventory` — catalogue evidence, flag missing and expired | ● | ● | ● |
| `control_mapping` — map evidence to controls, set verdicts | ● | ● | ● |
| `exception_review` — apply and expire risk acceptances | | ● | ● |
| `freshness_check` — controls whose evidence is ageing out | | ● | ● |
| `remediation_plan` — prioritised, dated work | | ● | ● |
| `scope_review` — apply scoping determinations, flag stale ones | | ● | ● |
| `crosswalk_coverage` — project onto other frameworks | | | ● |

`registry.catalog()` is the single source: the CLI's `--list-modules`, the
dashboard's checkboxes and the group presets all read it, so a selection in the
UI maps 1:1 onto `--modules`.

## How a verdict is reached

| Verdict | When |
|---|---|
| **Met** | two or more current items support the control, covering ≥75% of its points of focus |
| **Partially met** | evidence exists but is uncorroborated, expired, or covers too few points |
| **Not met** | no submitted evidence matches |
| **Risk accepted** | an approved, unexpired acceptance covers the control |
| **Not applicable** | scoped out; excluded from the score entirely |

Two rules do most of the work:

**One document is a claim; two is corroboration.** A single supporting item
never produces a pass, because that is the bar an auditor applies.

**Evidence expires.** A currency window is derived from the evidence class — 90
days for an access review, a year for a policy, 30 for a scan — and evidence
outside its window does not support a control. A manifest can override the
window per item.

The readiness score is a weighted percentage computed from the verdicts alone.
Control families carrying more breach risk (access control, incident response,
technical safeguards) weigh more. **AI commentary never moves the score** — it
is carried alongside as advisory text, so the number is reproducible from the
control register.

## Evidence ingestion

Evidence arrives under a versioned contract. `docs/ingestion-contract.md` is the
specification; `ironclad validate --manifest` checks a manifest and reports every
fault at once.

A directory with no manifest still works: one is derived and every file
checksummed, so re-submitting the same evidence under a new path is recognised
as the same evidence rather than counted twice.

## Tenant policy

`policy.json` beside the evidence — or `--policy` — carries the three
client-specific decisions an assessment must honour:

| | |
|---|---|
| **Scope exclusions** | controls that do not apply, with a written reason, a named approver and a review date |
| **Risk acceptances** | see below |
| **Owners** | who the remediation work goes to; `"CC6.*"` assigns a whole family |

Scoping a control out removes it from the readiness denominator, which makes it
the cheapest way to make a failing control disappear. So it is held to the same
bar as an acceptance: no justification or no approver, no exclusion. Every
determination is written to the audit trail, and three things are reported
rather than silently honoured — an exclusion past its review date, one falling
due, and one where the evidence supports the control anyway.

Spec in `docs/ingestion-contract.md`.

## Risk acceptance

An exception is how a client says "we know, here is why, here is who signed, and
until when". Three rules are enforced in the model, not the UI:

1. **A second person approves.** The requester cannot approve their own.
2. **It expires.** 90 days by default, 365 maximum. An open-ended acceptance is
   an unfixed gap with paperwork.
3. **A lapse reopens the gap immediately** — at the next assessment, not at the
   next review meeting.

These are enforced by replaying the approval workflow, so a hand-written
`policy.json` cannot assert an approval the workflow would refuse — a
self-approval fails `ironclad validate --policy`, not at assessment time.

## The audit trail

Every assessment, approval, expiry and revocation is appended to a hash-chained
log. Each event carries the digest of the one before it, so editing, removing or
reordering an event breaks every digest after it and `verify()` names where. The
exported package records the chain head.

## Exports

```sh
ironclad export --input out/assessment.json --format package --out package/
```

| File | Audience |
|---|---|
| `report.html` | the client |
| `control-register.csv` | the compliance team's working spreadsheet |
| `remediation-plan.csv` | the work queue, in priority order |
| `evidence-index.csv` | the auditor: which item supported which control |
| `audit-trail.csv` | the auditor: what happened and when |
| `assessment.json` | machine record |
| `package.json` | manifest, including the audit chain head |

The package carries **references and checksums, never the evidence bytes**. The
artifacts stay in the client's own storage; `README.txt` in the package says so
explicitly, so nobody assumes otherwise.

## Multi-tenancy

Every record carries a `client_id`, and tenants are physically partitioned as
`clients/{client_id}/...` in Firestore. A principal is bound to one tenant, and
every service call checks tenant ownership *before* permission — so a
cross-tenant probe fails identically whether or not the caller holds the
permission, and cannot be used to discover that another tenant exists.

| Role | Reads | Evidence & audit | Runs assessments | Approves risk | Manages tenant |
|---|:-:|:-:|:-:|:-:|:-:|
| `owner` | ● | ● | ● | ● | ● |
| `compliance_manager` | ● | ● | ● | ● | |
| `contributor` | ● | ● | | | |
| `auditor` | ● | ● | | | |
| `viewer` | ● | | | | |

An auditor reads everything and writes nothing — deliberately including no
`exception:approve`, since an auditor signing off on the risk they are auditing
is the conflict the role exists to prevent. The pipeline's own identity may run
assessments for any tenant and may never approve a risk acceptance: that is a
human decision.

## Pipelines

| Workflow | Trigger | What it does |
|---|---|---|
| `compliance-assessment.yml` | dispatch | fetch evidence, assess, AI consensus, report, publish |
| `framework-updates.yml` | quarterly | watch the official sources, open a PR on a real change |
| `ci.yml` | push / PR | the quality gates, on Python 3.10 and 3.12 |
| `Jenkinsfile` | Jenkins | the same gates, plus a client assessment runner |

Both gate pipelines run format, lint, typecheck, test, artifact validation,
build and security. Jenkins runs every gate even after one fails, so one build
reports every problem rather than one at a time.

```sh
gh workflow run "Compliance Assessment" \
  -R IronCityIT/ironclad-compliance \
  -f client_id="Acme Corp" \
  -f framework=soc2 \
  -f evidence_path=gs://ironclad-evidence/acme-corp/
```

## Development

```sh
pip install -r requirements-dev.txt

ruff format --check .                 # format
ruff check .                          # lint
mypy                                  # typecheck
pytest --cov=ironclad                 # test
python scripts/validate_artifacts.py  # JSON/YAML commit gate
python tools/build_catalog.py         # regenerate the dashboard catalog
```

### Adding a capability

Add one file to `ironclad/modules/` with a `name`, a client-safe `description`,
its `groups`, anything it `requires`, and a `run()`. Then
`python tools/build_catalog.py`. Nothing else changes — the CLI, the group
presets and the dashboard all read the registry.

### Adding a framework

Add `frameworks/<id>.json`, register it in `FRAMEWORK_ALIASES` and
`framework-versions.json`, add the workflow choice, and write the crosswalk in
`frameworks/crosswalks/`. `pytest` fails if any of those drift apart, and if a
crosswalk points at a control that does not exist.

## Configuration

Secrets are referenced by name and never held in this repository.

| Name | Used by |
|---|---|
| `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY` | passed through to `consensus-engine` |
| `GCP_SA_KEY` | evidence fetch |
| `GCS_BUCKET` | report storage |
| `STORE_RESULTS_URL`, `INGEST_API_KEY` | the ingest Cloud Function |
| `GITHUB_DISPATCH_TOKEN` | dashboard-initiated assessments — **not yet provisioned**, see `PRODUCTIZE_NOTES.md` |

GCP region is **us-east5 (Columbus)** throughout. Auth0 tenant is
`dev-ws5377dam2tnlv5g.us.auth0.com`, using Organizations for tenant SSO.

## Licence

Proprietary — Iron City IT Advisors.
