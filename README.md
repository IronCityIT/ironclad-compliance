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

ironclad exception request --policy policy.json --actor alice --role contributor \
  --control CC1.2 --justification "…" --expires-in-days 90
ironclad exception approve --policy policy.json --actor bob \
  --role compliance_manager --id ex-…
ironclad exception list    --policy policy.json --actor carol --role auditor

ironclad store health                     # can the configured store be written to?
ironclad store publish --input out/assessment.json
ironclad store list --client acme-corp

ironclad compare --from q3/assessment.json --to q4/assessment.json
ironclad compare --client acme-corp        # the two most recent, from the store

ironclad evidence stage --client acme-corp --out evidence/
```

`assess` writes three files:

| File | What it is |
|---|---|
| `assessment.json` | the complete machine record |
| `findings.b64` | base64 findings, the shape `consensus-engine` takes |
| `report.html` | the client-facing deliverable |

## What gets issued

`--assessment-type` chooses the deliverable. It never changes what is assessed:
every control is judged and the whole record is stored whichever type you pick,
because you cannot know which controls are gaps without judging them all, and
the readiness score is only reproducible from the complete register.

| Type | The report contains |
|---|---|
| `full` | every control, the remediation plan, the framework crosswalk |
| `gap-only` | only the controls with outstanding work, plus the plan |
| `readiness` | the position and the outstanding work, no control register |

An abridged report states what it left out, in the report. A gap analysis that
silently drops the passing controls is indistinguishable from a catastrophic
result. Accepted risks stay in a gap analysis — the control is still not met,
and the reader needs to see that somebody decided it.

`ironclad report --input assessment.json --view gap-only` re-issues a stored
assessment as a different deliverable without re-running anything. The auditor
package's CSVs are never abridged: the report inside it is the deliverable as
issued, but `control-register.csv` always carries every control.

The three types are defined once, in `ironclad/report/views.py`. The CLI's
choices, the service API's validation and the dashboard's dropdown all derive
from it.

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

### Whose rule is it

Both rules above are **Iron City policy, not the standard's**. No framework
requires two corroborating documents, and none sets a 90-day window on an access
review. Every report carries a *Basis of assessment* table saying, rule by rule,
whether it came from the framework, from Iron City, or from the client's own
policy file — and the stored record carries the same block, so an auditor
reading the machine record years later does not need the report beside it.

The table is generated from the constants the engine actually applies
(`ironclad/method.py`), so a bar that changes in the code cannot keep its old
description in the report. Naming our bars as ours is what makes them arguable,
which is the point: a client who wants to debate the 90-day window can find the
number, see whose rule it is, and change it in one place
(`ironclad/model/evidence.py::VALIDITY_DAYS`).

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

`ironclad exception request|approve|revoke|list` drives that workflow against a
tenant policy file, so nobody has to hand-write one. Each step runs through the
same service an API surface would call, so the permission check and the
separation-of-duties rule hold identically, and each step is appended to a
hash-chained trail beside the policy (`policy.json.audit.json`) — the ledger is
not kept in the margin of the document it describes. The acceptance lands in
`policy.json`, which is exactly what the next `ironclad assess --policy` reads.

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

npm --prefix functions run lint       # Cloud Functions syntax
npm --prefix functions test           # Cloud Functions decisions
npm --prefix dashboard test           # dashboard rendering and escaping
npm --prefix tests/rules test         # firestore.rules, against the emulator
```

The Cloud Functions' decisions — tenant slugs, document ids, whether an ingest
is authorized, whether an evidence path belongs to the caller — live in
`functions/core.js`, which imports nothing. The functions themselves open a
Firestore connection at require time, so anything left inside them could only be
tested against a live project. `functions/test` runs on the runtime's own test
runner with no install step.

The dashboard's rendering is tested the same way. Everything on that surface
builds HTML by string concatenation from data that arrived out of Firestore, so
escaping is the entire defence, and it is asserted field by field rather than
read for.

`firestore.rules` is executed rather than reviewed. `tests/rules` starts the
Firestore emulator, seeds two tenants with the rules suspended — so a seeding
mistake cannot be mistaken for a rule that permits a write — and then drives the
real client SDK as a signed-in user of each. It is the only gate that needs an
installed toolchain (`npm --prefix tests/rules ci`, plus a JVM for the
emulator), which is why it is its own CI job.

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
| `STORE_RESULTS_URL`, `INGEST_API_KEY` | the ingest Cloud Function — **required**: with no key configured the endpoint refuses every write rather than accepting unauthenticated ones |
| `GITHUB_DISPATCH_TOKEN` | dashboard-initiated assessments — **not yet provisioned**, see `PRODUCTIZE_NOTES.md` |

GCP region is **us-east5 (Columbus)** throughout. Auth0 tenant is
`dev-ws5377dam2tnlv5g.us.auth0.com`, using Organizations for tenant SSO.

## Where evidence comes from

Evidence lives on a NAS-backed volume, one prefix per tenant:
`<root>/<client_id>/`. `ironclad evidence stage` copies a tenant's own prefix
into a working directory and refuses anything that resolves outside it — a
traversal, a path-shaped client id that would normalise into a *different*
valid tenant, or a symlink planted inside one tenant's tree pointing at
another's. The check is structural: resolved path against resolved root, not a
string comparison.

It also refuses an empty prefix. A fetch that silently produces nothing makes
the assessment report every control as a gap, which reads to a client as a
catastrophic result rather than a broken fetch — this pipeline has made exactly
that mistake before.

Set `IRONCLAD_EVIDENCE_ROOT`, or pass `--root`. The workflow falls back to the
retired GCS path when no volume is configured, and fails outright when neither
is.

## What changed since last time

A compliance programme is a trend, not a snapshot. `ironclad compare` reports
what moved between two assessments: readiness, which controls improved or
regressed, which remediation items closed and which opened.

Three rules keep a trend from flattering a client by accident:

- **A control scoped out is not a control fixed.** Moving to `not_applicable`
  leaves the readiness denominator and lifts the score, which looks exactly like
  progress. It is reported as a scope change, in its own list.
- **Accepting a risk is a decision, not a fix.** `partial` → `accepted_risk`
  does not appear in the improved list.
- **A framework version change is not a trend.** The control set moved
  underneath the comparison, and the comparison says so rather than quietly
  producing a number.

Controls present in only one of the two runs are named, never dropped — a
control that disappears is either a scope change or a defect, and omitting it
hides which.

## Where a result comes to rest

Firebase, Firestore and GCP product storage are **retired from the target
architecture**. Persistent state moves to NAS-backed MariaDB, with artifact
files on a NAS volume; GitHub Actions stays the orchestration layer.
`HANDOFF.md` classifies every remaining reference and stages the migration.

`ironclad store` is the seam. One target string chooses the backend:

| Target | Store |
|---|---|
| `/srv/ironclad` or `file:///srv/ironclad` | a NAS-backed volume |
| `mysql://user:pw@host/db` or `mariadb://…` | MariaDB |

Pass it as `--to`, or set `IRONCLAD_STORE`. **Prefer the environment**: a DSN
carries a password, and a command line ends up in a process list, a shell
history and a CI log. Nothing in this product ever prints a DSN — errors name
`user@host:port/database` and nothing else.

Both backends write the same rows (`ironclad/store/rows.py`), and one test suite
asserts the same four properties against both: every row tenant-scoped, storing
twice leaves one record, the audit trail append-only and still chained on the
way out, and a store that cannot be written to says so before a pipeline
commits to publishing. The MariaDB half runs in CI against a real **MariaDB
10.5** service container — the version actually running on the NAS — not against
a mock.

`ironclad store init` applies `ironclad/store/schema.sql`, and is safe to re-run.
The driver (`PyMySQL`) is an optional extra: an assessment needs no database to
run, only to publish.

`scripts/end_to_end.py --store <target>` runs the whole product against a store
— the sample evidence in `examples/evidence/`, a real assessment, the
deliverables, a publish and a read back — and exits non-zero naming the step
that disagreed. Run it against a volume or a database on the day it is
provisioned, before a client's result goes near it. CI runs it against both on
every push.

## Where the rest is written down

| Document | What it carries |
|---|---|
| [`HANDOFF.md`](HANDOFF.md) | The portable developer handoff: current verified state, target architecture, migration off Firebase, blockers, runbooks. Start here. |
| [`STATUS.md`](STATUS.md) | Phase state, gate results, what is proven and how |
| [`PRODUCTIZE_NOTES.md`](PRODUCTIZE_NOTES.md) | The code review, the decisions, and every defect found |
| [`docs/ingestion-contract.md`](docs/ingestion-contract.md) | The evidence contract, versioned |
| [`docs/control-mapping.md`](docs/control-mapping.md) | The crosswalk, generated from the mapping files |

## Licence

Proprietary — Iron City IT Advisors.
