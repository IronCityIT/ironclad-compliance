# STATUS — Ironclad Compliance productization

> **Architecture change, 2026-09-07.** Firebase, Firestore, Firebase Hosting and
> GCP product storage are **retired from the target architecture**. GitHub
> Actions stays the orchestration layer; persistent state moves to NAS-backed
> MariaDB and NAS volumes. The Firebase components described below are the
> *current implementation*, not the target. `HANDOFF.md` classifies every
> reference and stages the migration; nothing is migrated or deleted yet.

**Branch:** `productize/ironclad-compliance` · **Updated:** 2026-09-27
**PR [#4](https://github.com/IronCityIT/ironclad-compliance/pull/4) is open. CI green at `c93c84e` (run 36304978752, `pull_request`; the duplicate `push` run 36304976714 was cancelled): all six jobs, pytest 1234 passed / 57 skipped on 3.10 and 3.12 (the 6 access-change cases among them), persistence 236. Green before that at `cfc6fbe` (run 36304211252, `pull_request`; the duplicate `push` run 36304209042 was cancelled): all six jobs, pytest 1228 passed / 57 skipped on 3.10 and 3.12 (the 9 offboarding-revocation cases among them), persistence 236. Green before that at `22af04a` (run 36303657549, `pull_request`; the duplicate `push` run 36303655153 was cancelled): all six jobs, pytest 1219 passed / 57 skipped on 3.10 and 3.12 (the 5 no-expiry and outlasts-assurance cases among them), persistence 236. Green before that at `441f740` (run 36302969029, `pull_request`; the duplicate `push` run 36302966658 was cancelled): all six jobs, pytest 1214 passed / 57 skipped on 3.10 and 3.12 (the 9 register-held issue cases among them), persistence 236. Green before that at `314cfc3` (run 36302226951, `pull_request`; the duplicate `push` run 36302224776 was cancelled): all six jobs, pytest 1205 passed / 57 skipped on 3.10 and 3.12 (the 6 retiring-ends-access cases among them), persistence 236. Green before that at `7b806b6` (run 36301537432, `pull_request`; the duplicate `push` run 36301534746 was cancelled): all six jobs, pytest 1199 passed / 57 skipped on 3.10 and 3.12 (the 7 workspace-refusal cases among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Green before that at `855337f` (run 36300691285, `pull_request`; the duplicate `push` run 36300688865 was cancelled): all six jobs, pytest 1192 passed / 57 skipped on 3.10 and 3.12 (the 10 access-log rotation cases among them, the late-writer case on its Linux branch), persistence 236, dashboard 102/102, Firestore rules 91/91. Red before that at `02be93e` (run 36300536001, one rotation test's expected wording; see the rotation entry). Green before that at `27306de` (run 36299568259, `pull_request`; the duplicate `push` run 36299565239 was cancelled): all six jobs, pytest 1182 passed / 57 skipped on 3.10 and 3.12 (the 7 review-continuity cases among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Green before that at `fdc6786` (run 36298761935, `pull_request`; the duplicate `push` run 36298759806 was cancelled): all six jobs, pytest 1175 passed / 57 skipped on 3.10 and 3.12 (the 21 access-review packet cases among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Red before that at `1879e07` (run 36298643936, mypy on the new test file; see the access-review entry). Green before that at `ce81a73` (run 36298046071): pytest 1154 passed / 57 skipped, persistence 236. Green before that at `4da9dae` (run 36297903426, `pull_request`; the duplicate `push` run 36297900660 was cancelled): all six jobs, pytest 1154 passed / 57 skipped on 3.10 and 3.12 (the 28 partner-access runs among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Green before that at `ccf46ca` (run 36296832072, `pull_request`; the duplicate `push` run 36296828496 was cancelled): all six jobs, pytest 1126 passed / 57 skipped on 3.10 and 3.12 (the register-export cases among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Green before that at `4527dd7` (run 36295538844, `pull_request`; the duplicate `push` run 36295536975 was cancelled): all six jobs, pytest 1114 passed / 55 skipped on 3.10 and 3.12 (the 17 log- and ledger-anchor cases among them), persistence 224. Green before that at `e3a2578` (run 36294982171, `pull_request`; the duplicate `push` run 36294979185 was cancelled): all six jobs, pytest 1097 passed / 55 skipped on 3.10 and 3.12 (the 17 grant-ledger cases among them), persistence 224. Green before that at `1df0174` (run 36294215258, `pull_request`; the duplicate `push` run 36294212520 was cancelled): all six jobs, pytest 1080 passed / 55 skipped on 3.10 and 3.12 (the 25 issue/revoke cases among them), the MariaDB persistence suite 224 passed. Green before that at `815c205` (run 36293169254): pytest 1055 passed / 55 skipped (the 7 usage-review cases among them), persistence 224. Green before that at `2e0c73b` (run 36292544236): pytest 1048 passed / 55 skipped (the 25 service-token cases among them), persistence 224. Green before that at `47f9041` (run 36291511505): pytest 1023 passed / 55 skipped (the 19 access-log cases among them), the MariaDB persistence suite 224 passed with none skipped. Green before that at `12cfef7` (run 36290114408): 1004 passed, persistence 224 (the register seal and the history row rewritten in place among them), dashboard 101/101, Firestore rules 91/91. Green before that at `58321de` (run 36288773882), 986 passed, persistence 205. Green before that at `0de87dd` (run 36287629428), 974 passed, persistence 192. Green before that at `298b2e0` (run 36286525753), 943 passed, persistence 161. Green before that at `a11a6ed` (run 36285596781) and `b159632` (run 36284444931), all six jobs, dashboard 100/100 and Firestore rules 91/91 against the emulator (unchanged by the review-queue and export passes; 88 before the edit/history pass, 78 before change history); green on every commit of 2026-09-16, 2026-09-17 and 2026-09-23. The product workflow has run four times as a dry run — see "Dry runs".**
**Scope posture: REVIEW ONLY. Nothing merged. Nothing deployed.**

> **The working tree is clean as of 2026-09-26** (checked with `git status`).
> The uncommitted 2026-09-10 dashboard/`tenants/`/`automation/` work described
> in `PRODUCTIZE_NOTES.md` §14 is no longer present; `tenants/sage-spine/seed.json`
> was committed in `791f510` and `sh scripts/check_white_label.sh` passes on the
> tree as it stands.

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
| Remediation planning | **DONE, tested; an open item keeps its first-raised and target dates across assessments, so overdue is real (§16.35)** | `ironclad/model/remediation.py` |
| Exceptions / risk acceptance | **DONE, tested** | `ironclad/model/exception.py` |
| Audit trail (hash-chained) | **DONE, tested** | `ironclad/model/audit.py` |
| Reports, exports, auditor package | **DONE, tested** | `ironclad/report/` |
| Assessment types actually shaping the deliverable | **DONE, tested** | `ironclad/report/views.py` |
| Standards-vs-ICIT-policy disclosure | **DONE, tested** | `ironclad/method.py` |
| Tenancy, RBAC, service API | **DONE, tested** | `ironclad/model/tenant.py`, `ironclad/api/` |
| HTTP surface — `ironclad serve` | **DONE, tested against a real socket; not deployed** | `ironclad/api/http.py`, `docs/http-api.md` |
| GitHub workflows | **DONE; `ci.yml` green; `compliance-assessment.yml` executed twice as a dry run, report stage proven, AI job red on the engine's output size (consensus-engine PR #6)** | `.github/workflows/` |
| Jenkins pipeline | **DONE; passes the declarative linter; executed on a throwaway controller with the Docker agent substituted — every runnable gate green, `persistence` UNAVAILABLE as designed; the assessment mode published to a volume store through an `ironclad-store` credential (§16.26–16.28)** | `Jenkinsfile` |
| Persistence seam (NAS volume + MariaDB) | **DONE, tested against a real MariaDB 10.5 in CI and 10.11 on this machine; the trend reads out of both stores** | `ironclad/store/` |
| Evidence from a NAS volume | **DONE, tested** | `ironclad/evidence_root.py` |
| Trend comparison between assessments | **DONE, tested; reaches the client report from both pipelines when a store is configured (§16.30)** | `ironclad/compare.py` |
| End-to-end round trip | **DONE, green in CI against MariaDB and a volume** | `scripts/end_to_end.py` |
| Cloud Functions | **BEING RETIRED** — decisions tested, never deployed | `functions/`, `functions/test/` |
| Firestore rules | **DONE, emulator-tested, not deployed** | `firestore.rules`, `tests/rules/` |
| Dashboard | **DONE, rendering tested, not deployed; the `ironclad serve` read path is built and tested against a real server, and is not wired in until B6 (§16.39)** | `dashboard/public/`, `dashboard/test/` |

## Partner & integration oversight — Sage Spine tenant workspace

`791f510` added a tenant-scoped register of partners and integrations
(`dashboard/public/oversight.html`, `firestore.rules`), seeded for Sage Spine.
It is the **only browser-writable path** in the tenant tree. As committed, the
rules checked tenant, role, authorship and timestamps, and nothing about the
record itself: any contributor or owner could write an arbitrary field (a place
to park PHI nobody reviews), any string as a risk rating or BAA status, any
size of text, a non-ISO date.

Closed on 2026-09-26:

- **Schema enforced at the data layer.** `validOversightShape()` fixes the
  field list (`hasOnly`), requires the governance fields, closes the vocabulary
  of `status`, `risk`, `agreement_status`, `baa_status`, `data_access` and
  `data_flow_direction`, requires ISO `YYYY-MM-DD` (or empty) dates, and bounds
  every text field. Applied to create **and** update, so a merge cannot smuggle
  a field in later. The two collections now share one create and one update
  predicate instead of two copies.
- **Emulator tests added** (`tests/rules/rules.test.js`): ten malformed records
  refused, a missing required field refused, an unknown field smuggled in by
  update refused, a complete valid record accepted, a contributor correcting
  notes accepted, and an approver rating a contributor's proposal accepted —
  the update path had no positive test before.
- **Page, seed and rules held to one vocabulary** without an emulator
  (`dashboard/test/oversight.test.js`): every `<select>` option, every field the
  page writes and its defaults, and every Sage seed record are checked against
  the lists parsed out of `firestore.rules`. Mutation-checked: adding an
  `Approved` risk option to the page fails the test by name.
- **The page's vocabulary now matches the seed's**: `Under review` for
  agreement/BAA status and `Retired` for the lifecycle (records are retired, not
  deleted). Three `Loading…` strings rendered as `Loadingâ€¦` (UTF-8 read as
  cp1252 on commit); now `&hellip;`.

**Change history, 2026-09-26 (second pass).** Every register write now carries
a `revision` and must, in the same batch, create `history/{revision}` holding an
exact copy of the record as written — `updated_by`/`updated_at` say who and
when, adjacent revisions say what. Enforced in `firestore.rules`, not trusted to
the page: a create or update without its entry is refused, the entry must equal
the record's post-write state, be filed under that revision and be written by
that caller in that request; entries cannot be updated or deleted; a revision
cannot be skipped. Because `history/{n}` can be created once, two editors
working from the same revision cannot both land — the second is refused rather
than silently overwriting the first. Records seeded before history existed take
revision 1 on their first edit. Tenant members read history; other tenants do
not. Ten new emulator cases cover this; the existing oversight cases now write
through the same batched path, so the schema refusals stay meaningful.

The page now files each new record with its revision-1 entry in one batch and
shows the revision on each card. It also had a latent bug: the form was reset
through `e.currentTarget` after the save was awaited, when that is already
`null`, so a successful save would have been reported as an error. Fixed and
held by a test; both new dashboard tests were mutation-checked (dropping the
history write, and reverting the reset, each fail by name).

**Edit and history in the page, 2026-09-26 (third pass).** Every card now has
**History** (any tenant member) and **Edit** (owner, compliance manager,
contributor). History lists revisions newest first with who, when (UTC) and a
field-by-field "from → to" against the previous revision; where the previous
revision is missing it says so and shows the record as saved rather than
inventing a diff. Edit reopens the record in the form and saves the next
revision with its history entry in one batch: the creation stamp is kept,
fields the form did not change carry over, and a contributor's governance
fields (status, risk, agreement, BAA) stay exactly as stored even if a tampered
form submits them. A save refused because someone else saved first is
explained as a stale form. The form gained the four stored fields it could not
show (port/protocol, network exposure, assurance, certificate expiry), an
`Unknown`/`Not recorded` choice so an existing value is never silently blanked,
and `maxlength` on every text field matching the bound in `firestore.rules`.

The logic is in `dashboard/public/oversight-core.js`, free of Firebase, so it
is tested directly: 16 cases in `dashboard/test/oversight.test.js` (was 7),
including a field-list equality with `oversightFields()`, a maxlength-per-rule
check, and escaping of every stored value in cards and history. Five mutations
(dropping the contributor governance guard, unescaping `data-id`, re-stamping
`created_at`, an off-by-one on a seeded record's revision, a notes maxlength
above the rule) each fail a test by name. Three emulator cases now drive the
page's own `buildRecord` rather than a hand-built write: contributor proposes →
owner rates → contributor edits notes (the rating stands); two editors on one
revision (the second is refused); a contributor edits a Sage Spine seed record
(revision 1, seed fields carried). No JDK here, so those three are proven only
in CI — and pass there: 91/91 in run 36283015277. Local evidence: `npm --prefix dashboard test` 79/80 (70/71 before; the one
failure is the same environmental `api.test.js`); `node --check` on the rules
suite; white-label and secret-literal gates pass.

**Review queue, 2026-09-26 (fourth pass).** The register recorded BAA status,
review dates and assurance expiry and nothing read them back: a reviewer had to
open every card to find PHI moving without a BAA. The page now opens with
**Needs attention**, derived only from stored fields by `attentionFindings()` in
`oversight-core.js`. High: PHI access without an executed BAA (whatever else the
BAA status says, `Not required` included); a BAA marked executed with no
execution date or document reference; a review overdue; assurance expired.
Notice: review or assurance due within 30 days; no review date; risk unrated;
data access unknown. Retired records are excluded. It is recomputed from both
kinds on every snapshot with the current UTC date. No write path, rule or schema
changed. Against the Sage Spine seed as committed, all six records (three
partners, three integrations) come up high for a missing BAA — true of the seed,
and the reason this exists. Seven new cases in `dashboard/test/oversight.test.js`
(fixed date, window boundaries both sides, escaping, the seed); four mutations
(exempting `Not required` from the BAA check, an off-by-one at the window edge,
dropping the Retired exclusion, unescaping the record name) each fail a test by
name. Local evidence: `npm --prefix dashboard test` 86/87 (the one failure is the
same environmental `api.test.js`); `node --check` on the page; white-label and
secret-literal gates pass.

**Register export, 2026-09-26 (fifth pass).** An auditor inventorying business
associates, or Sage staff working the queue offline, had to copy cards by hand.
The workspace now has **Download register (CSV)**, open to every tenant member
(it holds only what they can already read). `registerCsv()` in
`oversight-core.js` writes one row per record of both kinds — `record_type`,
`id`, every field in `oversightFields()`, then `attention_level` and the
review-queue findings — sorted by kind then name, with retired records kept
(the export is the inventory, not the queue) and timestamps as ISO UTC. RFC 4180
quoting with CRLF rows; any cell starting `=`, `+`, `-`, `@`, tab or CR is
prefixed with `'` so contributor-typed text is never evaluated as a spreadsheet
formula (OWASP CSV injection). The file is named
`oversight-register-<tenant>-<date>.csv` with the tenant id reduced to
`[A-Za-z0-9_-]`, and the button stays disabled until both kinds have loaded, so
a download is never half the register. No write path, rule or schema changed.
Five new cases in `dashboard/test/oversight.test.js`, parsed back with a small
RFC 4180 reader rather than compared as bytes; five mutations (dropping the
formula guard, dropping CR/LF from the quoting trigger, writing an unreadable
stamp as `Invalid Date`, un-excluding retired records from the queue, enabling
the button before both kinds load) each fail a test by name. Local evidence:
`npm --prefix dashboard test` 91/92 (the one failure is the same environmental
`api.test.js`, which spawns `python3`); `node --check` on the page and core;
white-label, secret-literal and `git diff --check` gates pass. In CI (run
36284444931) the dashboard suite is 100/100, `api.test.js` included.

**The register off Firebase, 2026-09-26 (sixth pass).** Everything above was
enforced only by `firestore.rules`, on the path the architecture retires, and
`HANDOFF.md` recorded what the replacement owed: the same checks and an
immutable per-record change log written in the same transaction as the record.
That replacement now exists on the target stores. `ironclad/oversight.py` is the
rules' create/update predicates as Python: closed fields, closed vocabularies,
ISO dates, bounded text; a contributor proposes unrated and cannot move a
rating; readers and other tenants cannot write; stamps (`tenant_id`,
`revision`, `created_*`, `updated_*`) come from the server and a caller who
supplies one is refused. Both stores gained `put_oversight` / `get_oversight` /
`list_oversight` / `oversight_history` / `verify_oversight`:

- **Volume**: each revision is a file `oversight/<kind>/<id>/<n>.json`, created
  with an exclusive hard link, so the history *is* the record — there is no
  moment one exists without the other, and a second writer at the same
  revision is refused (including one that passed the revision check just
  before the first landed).
- **MariaDB** (`ironclad/store/oversight_schema.sql`, applied by `store init`):
  the history row (key: tenant, kind, record, revision) and the record row move
  in one transaction; the record moves only from the revision before, so a
  skipped or stale revision rolls both back. No trigger enforces append-only —
  the NAS server runs with binary logging, where creating one needs SUPER; the
  production grant must be SELECT/INSERT only on `oversight_history`
  (`HANDOFF.md`).
- `verify_oversight` re-checks a record's history: revisions 1..n with no gap,
  one tenant, one creation stamp, and the record equal to its last entry.
- `load_seed` loads `tenants/sage-spine/seed.json` as an approver's revision-1
  entries, idempotently (a second load skips all six).

The Python vocabularies are parsed out of `firestore.rules` and asserted equal,
so the two cannot drift while both exist. 72 cases in `tests/test_oversight.py`:
53 run locally (policy, rules parity, Sage seed, volume contract), 19 are the
MariaDB contract and run in CI (`ci.yml`'s persistence job and the Jenkins persistence gate now run `tests/test_oversight.py` beside `tests/test_store.py`; before this, those cases would have been skipped there too). Seven mutations each fail a test by name
(contributor moves a rating, volume allows a skipped revision, volume overwrites
a taken revision, the store trusts the record, verify ignores the creation
stamp, a vocabulary drifts from the rules, a caller forges a stamp); the
overwrite mutation first survived, and the race test was added for it.

Found on the way: **the wheel shipped no `.sql` file**, and `ironclad/store/rows.py`
reads `schema.sql` at import, so `ironclad.store` could not be imported from an
installed wheel. `pyproject.toml` now declares the package data; a wheel built
and installed into a clean venv imports `ironclad.store` and has both files.

Local evidence (Windows 11, Python 3.12 venv): `pytest` 469 passed, 46 skipped,
and the same 16 failures + 10 collection errors as the untouched tree
(`fcntl`, symlinks — compared set for set); ruff format/lint pass; mypy clean
but for the known Windows-only `fcntl` in `policy_store.py`; `npm --prefix
dashboard test` 91/92 (the environmental `api.test.js`); white-label,
secret-literal, catalog and `git diff --check` gates pass.

**The register over `ironclad serve`, 2026-09-26 (seventh pass).** The target
stores held the register, but nothing could reach it over the network. There
are now five routes under `/api/v1/tenants/{t}/oversight/{partners|integrations}`:
list, create, read one, edit, and history with its verification verdict
(`ironclad/api/http.py`, `docs/http-api.md`). They are backed by the same
`ironclad.oversight` policy and `put_oversight` step as the stores, so the
rules' refusals are now HTTP statuses:

- another tenant, or a viewer/auditor writing: 403;
- a stamp in the body, or a record outside the schema: 400, with every problem
  named;
- a contributor setting or moving a rating: 403;
- an edit from a stale revision: 409, and nothing is written;
- an unknown record: 404;
- a store without the register: 503.

An edit must carry `base_revision`, so a stale form is refused rather than
applied on top of a change the caller never saw. `oversight.save` now settles
tenant and role **before** it reads the record, and a missing record raises
`RecordNotFoundError`. Before this, a writer from another tenant got
"does not exist" for an unknown id and an authorization refusal for a real one,
which told them which ids existed.

Tests: 11 HTTP cases in `tests/test_http.py::TestOversightRegister`, on a real
socket, and one store-contract case in `tests/test_oversight.py`, run on the
volume locally and on MariaDB in CI. Five mutations each fail a test by name:

- dropping the early authorization in `save`;
- mapping a stale revision to 400;
- making `base_revision` optional;
- reporting a missing record as 400;
- accepting unknown body keys.

Local evidence (Windows 11, Python 3.12 venv): `ironclad.api` imports `fcntl`,
so `tests/test_http.py` was run with a no-op `fcntl` stub. Result: 186 tests,
164 passed, 20 skipped (MariaDB), and 2 failures. The same 2 fail on the
untouched tree under the same stub (the 20-writer lock test needs a real lock,
and the `serve` subprocess test gets no stub). The unstubbed run is CI's.
ruff format and lint pass; mypy reports only the known Windows `fcntl`
errors; `git diff --check` is clean.
In CI (run 36286525753), unstubbed: 943 passed on 3.10 and 3.12, and the
MariaDB persistence job 161 passed, which includes the new store-contract case
on MariaDB.

**The review queue on the target stack, 2026-09-26 (eighth pass).** The
*Needs attention* queue (fourth pass) existed only in the browser, computed
over Firestore snapshots, so it would have been lost with the path the
architecture retires. Anything not holding a browser session (a Sage staff
service token, a scheduled BAA sweep, an auditor's pull) could not ask what
needed review. `attention_findings()` and `attention_queue()` in
`ironclad/oversight.py` are the dashboard's `attentionFindings()` as Python,
and `GET /api/v1/tenants/{t}/oversight/attention?as_of=YYYY-MM-DD` serves the
queue across both registers. Any tenant member may read it, and it holds nothing
they cannot already read. Another tenant gets 403, and a date that is not a
calendar day gets 400. With no `as_of` it is today in UTC. Items come high first,
then by name, with `records`/`high` counts. No write path, rule or schema
changed.

The two implementations are held to **one table of 20 cases**,
`tests/fixtures/oversight-attention.json`, message for message and in order.
It was written by hand as a specification and run against the existing JS
first, which passed unchanged, so the spec describes shipped behaviour.
`dashboard/test/oversight.test.js` and `tests/test_oversight.py` both read it,
and the Python side also parses `ATTENTION_WINDOW_DAYS` out of
`oversight-core.js`. Two store-contract cases (both kinds, high first, clean
records absent, tenant isolation) run on the volume locally and on MariaDB in
CI. Two HTTP cases run on a real socket, and cover the `as_of` shift that turns
a governed record overdue and the route not being shadowed by `{kind}`. Six
mutations each fail a test by name: exempting `Not required` from the BAA check,
a window off by one, dropping the Retired exclusion, notices sorted first,
the queue skipping the reader check, and findings left unsorted.

Local evidence (Windows 11, Python 3.12 venv): `tests/test_oversight.py` and
`tests/test_http.py` under the no-op `fcntl` stub: 196 passed, 22 skipped (MariaDB), and 1 failure, the 20-writer lock test, which fails the same way on the untouched tree because it needs a real lock. A seventh mutation, registering the queue route after `{kind}` so `attention` reads as a register name, fails both HTTP cases; ruff format and
lint pass; mypy reports only the known Windows `fcntl` errors in
`policy_store.py`; `npm --prefix dashboard test` 92/93 (the one failure is the
environmental `api.test.js`); white-label, secret-literal and `git diff
--check` gates pass.

**Integrity sweep and a command line, 2026-09-26 (ninth pass).** Two gaps
were left on the target stack. `verify_oversight` checked one record at a
time, only over HTTP, and only for records the caller already knew; and
nothing that holds no browser session (a scheduled BAA sweep, an auditor with
store access, whoever loads the Sage seed into a new store) had a way in:
`load_seed` existed as a function with no entry point. Now:

- `verify_register()` in `ironclad/oversight.py` re-checks every record of
  both kinds and returns `records`, `broken`, `verified` and one verdict per
  record. It walks a new store method, `oversight_ids()`, which on MariaDB is
  the **union** of the record table and the history table. A record row
  deleted from under its history (a business associate dropped from the
  inventory without a trace) was invisible to every list and to `/history`,
  which needs the id; the sweep reports it as `history exists for a record
  that does not`. On a volume the history is the record, so the two are the
  same set.
- `GET /api/v1/tenants/{t}/oversight/verification` serves the sweep to any
  tenant member; another tenant gets 403, and a POST there is 404, as for
  `attention`. Registered before `{kind}`.
- `ironclad oversight load-seed | verify | attention` (`ironclad/cli.py`), each
  run as an asserted `--actor` with `--role`s through the same policy, so a
  contributor loading the rated seed and an actor with no role are refused
  (exit 2). `verify` exits 4 on any broken record; `attention --fail-on
  high|any` exits 4 when the queue holds such a finding. Exit 4 is new and
  means "the register needs looking at", distinct from 2, "the job is wrong".
  The runbook is `HANDOFF.md` §17.

Known limit, written down rather than hidden (`docs/http-api.md`): on a volume,
deleting a record's latest revision file rolls the record back to the one
before with a whole history, and no check inside the volume can see it.
Anchoring the head revision somewhere else is the fix; the tenth pass (below)
builds it.

Tests: 13 new functions, 15 runs across the two stores. Two store-contract cases (every record of both kinds verified
after an edit; the sweep refuses another tenant and is empty for its own) run
on the volume locally and on MariaDB in CI; one volume case (an entry
rewritten to name another tenant is named in the sweep); one MariaDB case (the
deleted record row is found through its history); two HTTP cases on a real
socket; seven CLI cases on a volume. Six mutations each fail a test by name:
the sweep always verified, the sweep without the reader check, the sweep
truncating what it walks, `verify` always exiting 0, `--fail-on any` ignored,
and the route registered after `{kind}`. Walking only listed records instead
of `oversight_ids()` is indistinguishable on a volume; the MariaDB case that
catches it runs in CI only (no MariaDB on this machine today).

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub as before):
`tests/test_oversight.py` + `tests/test_http.py` 208 passed, 25 skipped
(MariaDB), 1 failed: the 20-writer lock test, unchanged from the untouched
tree (196 passed, 22 skipped, same failure). ruff format and lint pass; mypy
reports only the known Windows `fcntl` errors in `policy_store.py`.
In CI (run 36288773882): 986 passed on 3.10 and 3.12, and the MariaDB
persistence job 205 passed, 0 skipped, so the three MariaDB cases this pass
added ran against a real server and passed.

**A seal kept outside the store, 2026-09-26 (tenth pass).** The sweep checks
each history against itself, and two tamperings pass it. The first is a past
entry rewritten in place. Revision 2 of a record is the approver's rating; set
its `risk` to `Low` on a volume, or `UPDATE` a MariaDB history row (possible
until the production grant is SELECT/INSERT only), and the revision, tenant,
creation stamp and latest entry all still check out. Who rated what, and when,
is exactly what a HIPAA reviewer relies on. The second is the known limit
above: a latest revision deleted on a volume. Both are now caught, by tests
that first assert `verify` passes and then that the seal does not:

- `seal_register()` in `ironclad/oversight.py` returns, per record, the
  SHA-256 of each history entry (sorted-key compact JSON), plus one `digest`
  over the tenant and every entry. Who sealed and when are left out of the
  digest, so an unchanged register seals to the same one. It walks
  `oversight_ids()` like the sweep. Any tenant member may take one.
- `compare_seals(earlier, later)` requires the later seal to extend the
  earlier one. A record gone, a revision removed, or a sealed entry that now
  hashes differently is broken, with `broken_at` the first revision that
  differs. New revisions and new records are reported and are not broken.
  Both seals must match their own digest and be of one tenant, or the
  comparison is refused.
- `GET /api/v1/tenants/{t}/oversight/seal` serves it to any tenant member.
  Another tenant gets 403 and a POST is 404; it is registered before `{kind}`.
- `ironclad oversight seal`, `ironclad oversight verify --seal FILE` (exit 4 if
  the store no longer extends the seal), and `ironclad oversight compare-seals
  --earlier A --later B`, which needs no store. That last one is for an
  auditor who takes seals over HTTP and holds no store credential. A seal file
  that is unreadable, of another tenant, or edited since it was taken is exit 2.
  The runbook is `HANDOFF.md` §17.

No write path, stored field, rule or schema changed. A seal is only as good as
where it is kept; the docs say so and name the places (auditor workpapers, a CI
artifact), and the digest is the line to record elsewhere.

Tests: 21 new cases across both files. Two store-contract cases (a later seal
extends an earlier one across edits and a new record; the seal is the tenant's
own) run on the volume locally and on MariaDB in CI. Three volume cases: a
rewrite in place, a deleted latest revision, and a record removed whole, each
passing `verify` and failing the seal. One MariaDB case: a history row
`UPDATE`d in place. Eight cases check the seal itself without a store: key
order, a seal compared with itself, an edited seal, a dropped record, four
malformed shapes. Two HTTP cases
run on a real socket, and three are CLI cases. Seven mutations each fail a
test by name: comparison ignoring a changed entry, comparison ignoring removed
revisions, the digest self-check skipped, the seal skipping the reader check,
comparison across tenants allowed, `verify --seal` exiting 0 on a broken seal,
and the route registered after `{kind}`.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub as before):
`tests/test_oversight.py` + `tests/test_http.py` 226 passed, 28 skipped
(MariaDB), 1 failed: the 20-writer lock test, unchanged from the untouched
tree (208 passed, 25 skipped, same failure). Whole suite: 1059 run, 10 failed,
every one also failing on the untouched tree (Windows `fcntl`, symlinks, CRLF),
which failed 11. ruff format and lint pass; mypy reports only the known Windows
`fcntl` errors in `policy_store.py`; white-label, secret-literal and `git diff
--check` gates pass. In CI (run 36290114408): 1004 passed on 3.10 and 3.12, and
the MariaDB persistence job 224 passed, 0 skipped, so the three MariaDB seal
cases ran against a real server.

**An access log for `ironclad serve`, 2026-09-26 (eleventh pass).** The
register's history says who changed a record, and nothing said who *read*
one, or who was *refused*. A partner's token probing another tenant's register
left `GET ... 403` on stderr with no name attached. HIPAA's audit-controls
standard (164.312(b)) asks for a record of activity, reads and refusals
included, before Sage staff and integration partners hold tokens.
`ironclad serve --access-log FILE` (`ironclad/api/access_log.py`) now appends
one JSON line per API request, before the answer is sent. Each line holds the
UTC time, the token's user and tenant (`null` for no recognised token), the
method, the path and the status. Never the query string, the body or any
header. Health checks and static files are not recorded.

- **Hash-chained** like the policy audit trail: `seq`, the previous line's
  digest and its own, so an edited, deleted, reordered or renumbered line
  breaks the chain. `ironclad access-log verify FILE` prints the entries, the
  first broken line and the head digest; it exits 4 if the chain is broken
  and 2 if the file is unreadable.
- **Fail closed.** The server re-checks the file at start and refuses a
  broken one (exit 2), rather than burying the break under new lines. If a
  line cannot be written, the caller gets 503 and nothing else. A write that
  already landed stays landed, and the register history names its author.
- One lock across handler threads, and `fsync` per line. One server per
  file. Rotation is: stop the server, move the file, start it again.

No route, stored field, rule or schema changed. Runbook: `HANDOFF.md` §17,
"Who used the register, and who was refused". Reference: `docs/http-api.md`,
"Access log".

Tests: 19 new cases. Fourteen in `tests/test_access_log.py` cover the chain:
written and reopened, a 403 turned into a 200, a line removed, a line removed
and renumbered with its hash recomputed, wrong keys, a line cut off mid-write,
20 concurrent writers and the verify command. Five in
`tests/test_http.py::TestAccessLog` run on a real socket: a create, a read, a
cross-tenant 403 named `mallory@beta.example`/`beta`, an anonymous 401 and a
404, each one attributed line; no query, body or token in the file; health
and static not logged; an unrecordable answer withheld as 503; `serve`
refusing a broken log. Seven mutations each fail a test by name:

- the principal not carried to the log;
- health logged;
- the answer sent unrecorded;
- the query string logged;
- the chain link unchecked;
- a broken log opened;
- the digest unchecked.

A first run of the "broken log opened" mutation hung, because `serve` started
for real. The test now fails fast if serving begins.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): the whole
suite ran 1078 tests: 1013 passed, 55 skipped, 10 failed. The same 10 fail on
the untouched tree (1059 run, 994 passed), compared set for set. ruff format
and lint pass; mypy reports only the known Windows `fcntl` errors in
`policy_store.py`; white-label, secret-literal and `git diff --check` gates
pass.

**Service tokens that end, and an access review, 2026-09-26 (twelfth pass).**
The access log names who used the register; nothing bounded how long they
could. A token-file entry granted access for ever, so a partner whose contract
ended kept a working token until someone remembered the file, and listing who
held access to the Sage Spine workspace meant reading raw JSON. HIPAA's
termination procedures and access review (164.308(a)(3)(ii)(C), (a)(4)) want
both. `ironclad/api/tokens.py` and `TokenFileAuthenticator` now:

- honour an optional `expires_at` (`YYYY-MM-DD`): the token works through that
  UTC day and is 401 from the next, with no restart, since the file is re-read
  per request. An expiry that is not a calendar date refuses the token; a typo
  must not become access that never ends. Entries without one behave as before.
- refuse a digest listed in two entries instead of serving whichever came
  first (two grants for one token, e.g. two tenants, and picking one is a guess).
- compare digests as bytes. Every entry is now scanned, and a stored value
  that is not ASCII would have made `hmac.compare_digest` raise for every
  caller; it now just fails to match.

`ironclad tokens review FILE [--as-of D] [--fail-on high|any]` is the access
review: per entry the user, tenant, recognised roles, expiry and a state
(`active`, `expiring` within 30 days, `expired`, `refused`). High: an expired
entry still in the file, a bad expiry, a duplicate digest, no or unslugged
tenant, unknown or no roles, a malformed digest, no `user_id` (the access log
could not name the caller). Notice: no expiry, or expiring soon. It reads
digests only and prints a 12-character prefix. Exit 4 when tripped, 2 when the
file or `--as-of` is unreadable. Runbook: `HANDOFF.md` §17, "Grant, renew and
review a service token"; reference: `docs/http-api.md`.

No route, stored field, rule or schema changed; an existing token file serves
exactly as before unless it lists a digest twice.

Tests: 25 new cases. 18 in `tests/test_tokens.py`: expiry parsing, the last
day read in UTC (20:00 in New York on the 30th is past a token ending the 30th),
the authenticator following its clock across midnight, every review state and
finding, the 30-day window edges, the digest prefix, the CLI's exit codes, and
one case holding the review and the authenticator to the same verdict for
every entry. Seven in `tests/test_http.py::TestAuthentication` on a real
socket: an expiry moved into the past refuses the next request and nobody
else's; four malformed expiries refused; a duplicate digest refused; a
non-ASCII digest not breaking other tokens. Ten mutations each fail a test by
name: expiry ignored, a bad expiry read as none, a duplicate taking the first
entry, `compare_digest` back on `str`, the last day off by one, local time
instead of UTC, the warning window off by one, the review missing duplicates,
the full digest printed, `--fail-on any` ignoring notices.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): the whole
suite ran 1103 tests: 1038 passed, 55 skipped, 10 failed. The same 10 fail on
the untouched tree, compared set for set. ruff format and lint pass; mypy
reports only the known Windows `fcntl` errors in `policy_store.py`;
white-label, secret-literal and `git diff --check` gates pass.

**Who is using the access they hold, 2026-09-27 (thirteenth pass).** The token
review said who *holds* access; the access log said who *used* it; nothing put
the two together, so dormant partner access, the first thing an access review
removes (164.308(a)(4)(ii)(C)), could only be found by hand.
`ironclad tokens review FILE --access-log LOG [--dormant-days 90]` now verifies
the log (exit 4 and no review if it is not a whole chain), then gives each entry
`requests`, `refused` (403s) and `last_used`, matched on the user and tenant the
log names, counting only lines on or before `--as-of`. Notices: an active entry
with no request in the window (`dormant`; "since the log begins" when never
seen), and any 403 with its latest path — a role reaching past itself or a
partner's token pointed at another tenant. An expired entry's use is shown and
not called dormant (it is already high). `access_log.read_file` verifies and
parses in one read, so the review rests on exactly the lines verified. Without
`--access-log` the output is unchanged. No route, stored field, rule or token
file format changed. Also: `HANDOFF.md` §16 listed two blockers as B6; the
ICIT-Infrastructure one is now B7 (every other reference means the sign-in).

Tests: 7 new cases in `tests/test_tokens.py::TestReviewWithUsage`, on real
chained logs written by `AccessLog`: per-entry use and the log span; the
window edges both ways and `--dormant-days 0` refused; a never-used entry
tripping `--fail-on any` and not `high`; an edited log line refused with exit 4
and nothing on stdout; a missing log exit 2; no usage keys without a log; no
digest in the output. Four mutations each fail a test: the `--as-of` cut-off
removed, the window widened, the 403 notice dropped, an expired entry called
dormant (the last needed the lapsed entry's use moved outside the window — the
first version of the test let it survive).

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1110 tests,
1045 passed, 55 skipped, 10 failed; untouched HEAD `2e0c73b` in a worktree:
1038 passed, the same 10 failed, compared set for set. ruff format and lint
pass; mypy reports only the known Windows `fcntl` errors; white-label,
secret-literal and catalog gates pass. bandit is not installed here; CI runs it.

**Granting and removing access without hand-editing, 2026-09-27 (fourteenth
pass).** The review found what was wrong with a token file, and the only way
to write one was by hand: generate a token, pipe it to `hash-token`, paste the
digest into JSON on the server. Every high finding the review can report (no
expiry, a bad date, a duplicate, no tenant, an unknown role, no `user_id`) is
a hand edit gone wrong, and a partial write could be read by the running
server, which re-reads the file per request. Nothing recorded who granted
access. `ironclad tokens issue | revoke` (`ironclad/api/tokens.py`) now:

- **issue** generates the token (`secrets.token_urlsafe(32)`), prints it once
  on stdout and stores only its digest, with `issued_by` and `issued_at`. It
  refuses a grant with no end or more than `MAX_TERM_DAYS` (365, ours: one
  annual review) out, an expiry already past, an unknown role, a tenant that
  is not a tenant id, no user or no issuer, and a second entry for one user
  in one tenant. The access log names callers by user and tenant, so two
  entries for one pair could not be told apart. A renewal is revoke then
  issue, so the credential changes with the term.
- **revoke** removes one user's entry in a tenant, one entry by the digest
  prefix the review prints (at least 12 hex; an ambiguous prefix is refused),
  or every entry past its expiry (`--expired`, the review's "remove the
  entry"). An entry with an unreadable date is left for a person. Removing
  nothing is refused. It prints what it removed by prefix, with `revoked_by`.
- Both hold `<file>.lock`, created exclusively, for the whole
  read-modify-write, and replace the file with a fsynced temp file and
  `os.replace`, so the server reads the old file or the new one. Any refusal
  is exit 2 and the file is byte-for-byte unchanged.
- The review prints `issued_by`/`issued_at` for entries that have them.

No route, authenticator rule or stored field the server reads changed; the
two new keys are ignored by `TokenFileAuthenticator`. Runbook: `HANDOFF.md`
§17, "Grant, renew and review a service token"; reference: `docs/http-api.md`.

Tests: 25 new cases in `tests/test_tokens.py` (50 in the file). An issued
token authenticates as its user and tenant and its token is not in the file;
two issues never share a token; eight refusals leave the document unchanged;
the term edges (today, day 365, day 366); one entry per user per tenant; revoke
by user, by prefix (short and ambiguous refused), `--expired` (the bad date
kept and still high in the review), four selector refusals; a revoked token
refused at its next lookup while another still works; and four CLI cases (issue
then revoke with no temp or lock left behind, a refused edit leaving the
file's bytes, a held lock refusing an edit and being left alone, other keys
in the file kept). Seven mutations each fail a test by name: no maximum term,
no one-per-pair check, an ambiguous prefix allowed, the lock not exclusive,
`--expired` sweeping unreadable dates, the printed entry carrying its digest,
a past expiry allowed.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1135 tests,
1070 passed, 55 skipped, 10 failed; untouched HEAD `03136f9` in a worktree:
1110 tests, 1045 passed, the same 10 failed, compared set for set. ruff format
and lint pass; mypy reports only the known Windows `fcntl` errors;
white-label, secret-literal, catalog and `git diff --check` gates pass.
In CI (run 36294215258), unstubbed: 1080 passed, 55 skipped on 3.10 and 3.12,
bandit included in the security gate; persistence 224 passed.

**A ledger of every grant and revocation, 2026-09-27 (fifteenth pass).**
`issue` and `revoke` stopped hand edits going wrong, and nothing caught a hand
edit made anyway: an entry pasted into the file, or an issued one with its
expiry pushed out or `owner` added, looked exactly like an issued entry to the
server and to the review. And once `revoke` removed an entry, nothing on the
server said the grant had existed or who ended it; the runbook asked the
operator to keep stdout. HIPAA's access-authorization and termination
procedures (164.308(a)(4)(ii)(B)-(C), (a)(3)(ii)(C)) want both on record, in
a form that cannot quietly be rewritten (164.312(b)).
`ironclad/api/grant_ledger.py` now:

- **records** each issue and each removed entry as one chained JSON line in
  `tokens.json.ledger` (or `--ledger`): time, `as_of`, action, actor, user,
  tenant, roles, expiry and the entry's `sha256`, never the token. It is
  written under the token file's lock and fsynced **before** the token file is
  replaced, so no edit lands unrecorded; if the ledger cannot be written, the
  edit is refused and the file is byte-for-byte unchanged. A ledger that is not
  a whole chain refuses further edits. `issue` and `revoke` print `ledger_head`;
  `revoke` now refuses a blank `--actor`.
- **reconciles**: `ironclad tokens review FILE --ledger LEDGER` verifies the
  ledger (exit 4 and no review if broken), then flags as high an entry with no
  grant on record, one differing from its grant in user, tenant, roles or
  expiry, and one revoked and back in the file. A grant with neither an entry
  nor a revocation is a notice under `ledger.unrecorded`. Matching entries
  carry `granted_by`/`granted_at`. Without `--ledger` the review is unchanged.

The access-log chain check now takes its field set as a parameter, so both
logs share one verifier (`access_log.verify_lines`, `line_digest`,
`read_lines`); the access log's lines and digests are unchanged. No route,
authenticator rule or token-file field the server reads changed; the server
never reads the ledger. Runbook: `HANDOFF.md` §17, "Grant, renew and review a
service token"; reference: `docs/http-api.md`.

Tests: 17 new cases in `tests/test_grant_ledger.py`. Issue then revoke is
two chained lines naming both actors, with the digest and not the token;
`--expired` writes one line per entry; an explicit `--ledger` path works; a
ledger write that fails leaves the token file and ledger unchanged and no lock;
an edited ledger refuses the next issue; a blank revoking actor is refused.
For the review: issued entries carry their grant; a pasted `owner` entry is
high; expiry, roles and tenant each edited after the grant are high; a revoked
entry restored is high and names who revoked it; an entry removed by hand is a
notice (trips `any`, not `high`); a properly revoked entry is not unrecorded;
a ledger with its first line cut is exit 4; a missing one exit 2; no ledger, no
change. `tests/test_tokens.py` now expects the ledger beside the file. Seven
mutations each fail a test by name: the ledger written after the token file,
revocations ignored, expiry not compared, revoked grants counted as
unrecorded, a broken ledger appended to, a broken ledger reviewed, unrecorded
grants not counted as notices.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1152 tests,
1086 passed, 55 skipped, 11 failed; untouched HEAD `6094798` in a worktree:
1135 tests, 1070 passed, 10 failed. The extra one,
`test_store.py::TestTheVolume::test_two_tenants_may_use_the_same_assessment_id`,
was a Windows `os.replace` "Access is denied" while both suites ran at once.
It passes re-run alone on both trees, and otherwise the failed sets match. ruff format
and lint pass; mypy reports only the known Windows `fcntl` errors;
white-label, secret-literal, catalog and `git diff --check` gates pass. bandit
is not installed here; CI runs it.

**Anchors for the access log and the grant ledger, 2026-09-27 (sixteenth
pass).** Both logs told the operator to copy the head digest somewhere else,
and nothing could check a log against that copy. Three tamperings leave a
whole chain and passed every check: lines cut from the end (the last grants,
or the requests of the last hour), the file replaced by a new one (a server
restarted on an emptied access log starts a fresh chain; a deleted ledger is
recreated by the next `issue`), and a rewrite with every digest after it
recomputed. The review with `--ledger` cannot see a grant cut from the ledger's
end either; it only knows the lines that are left. Now:

- `access_log.anchor_of`, `parse_anchor` and `check_anchor`: an anchor is
  `N:DIGEST`, the last line's number and digest. A later file extends it if
  line N is still there with that digest, and since each digest covers the
  line before, that one line vouches for lines 1..N. Checked only on a whole
  chain; a broken one is already exit 4.
- `ironclad access-log verify FILE` prints `anchor`; `--anchor N:DIGEST` adds
  `extends` (`extended`, `reason`) and exits 4 if the file no longer extends
  it, 2 if the anchor is not `N:DIGEST`.
- `ironclad tokens verify-ledger LEDGER [--anchor N:DIGEST]` does the same for
  the grant ledger, through the same code with the ledger's field set (an
  access log given as a ledger is refused as "not a grant-ledger entry").
  `issue` and `revoke` print `ledger_anchor` beside `ledger_head`.

No route, stored field, token-file field or log line changed; the server reads
neither. Runbooks: `HANDOFF.md` §17, "Who used the register" and "Grant, renew
and review a service token"; reference: `docs/http-api.md`.

Tests: 17 new cases. Twelve in `tests/test_access_log.py::TestAnchor`: the
anchor is the last line and empty for an empty log; a grown log extends it
(also typed in capitals with a space); a cut tail verifies alone and fails the
anchor; a replaced log of the same length fails it; a 200 turned into a 403
with every digest recomputed verifies alone and fails it; a broken chain is
not held to it; six malformed anchors are exit 2 with nothing on stdout. Five
in `tests/test_grant_ledger.py::TestLedgerAnchor`: `issue`/`revoke` print
anchors a later ledger extends; a grant cut from the end; a ledger started
afresh; an access log is not a ledger; a missing ledger and a bad anchor are
exit 2. Seven mutations each fail a test by name: the digest comparison
dropped, the length check off by one, anchor line 0 accepted, the CLI ignoring
the anchor verdict, a broken chain held to the anchor, `verify-ledger` checking
with the access log's fields, the ledger anchor off by one.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1152 tests,
1086 passed, 55 skipped, 11 failed; untouched HEAD `6ccd1e1` in a worktree, run
after it and not alongside: 1135 tests, 1070 passed, 10 failed. The extra one is
again `test_store.py::TestTheVolume::test_two_tenants_may_use_the_same_assessment_id`
(a Windows `os.replace` "Access is denied"), which passed three times re-run
alone; otherwise the failed sets match. ruff format and lint pass; mypy reports
only the known Windows `fcntl` errors; white-label, secret-literal and `git diff
--check` gates pass. In CI (run 36295538844), unstubbed: 1114 passed, 55 skipped
on 3.10 and 3.12; persistence 224 passed.

**The register export on the target stack, 2026-09-27 (seventeenth pass).**
The fifth pass's *Download register (CSV)*, the business-associate inventory an
auditor asks for, existed only in the browser, over Firestore snapshots. It had
the same gap the review queue had before the eighth pass: nothing without a
browser session (an auditor with a service token, a quarterly job filing the
inventory) could take it, and it would have been lost with the path the
architecture retires. Now:

- `register_csv()` and `export_file_name()` in `ironclad/oversight.py` are the
  dashboard's `registerCsv()` and `exportFileName()` as Python: the same
  columns, partners then integrations each by name, retired records kept, the
  queue's findings per row, RFC 4180 with CRLF, and the same `'` guard on a
  cell a spreadsheet would evaluate (OWASP CSV injection).
- `export_register()` checks the reader and returns `filename`, a count per
  kind, the SHA-256 of the file's bytes and the file. The hash names exactly
  what was handed over.
- `GET /api/v1/tenants/{t}/oversight/export?as_of=` serves it to any tenant
  member inside the usual JSON envelope. Another tenant is 403, a bad date
  400, a POST 404. It is registered before `{kind}`.
- `ironclad oversight export --tenant T --actor A --role R --out FILE|DIR`
  writes the bytes as they are (CRLF kept on Windows) and prints the path,
  counts and hash, not the file. The runbook is `HANDOFF.md` §17; the
  reference is `docs/http-api.md`.

The two implementations are held to **one file byte for byte**,
`tests/fixtures/oversight-export.json`. The records in it were written by hand:
formula-led cells of every kind, a comma, quotes, a CRLF and a bare LF, a
retired record, and review and expiry dates on both sides of the 30-day edge.
The expected CSV was produced by the shipped JS. `dashboard/test/oversight.test.js`
and `tests/test_oversight.py` both read it. No write path, stored field, rule or
schema changed.

Tests: 12 new Python test functions (14 runs across the two stores) and 1 JS
case. Six unit cases: the shared file, a
read-back through `csv`, a bad date, three file names. Two store-contract cases
(the whole register with a retired record and a matching hash; the tenant's
own) run on the volume locally and on MariaDB in CI. Two HTTP cases run on a
real socket, and two CLI cases check the file named in a directory, its hash,
its CRLF rows and a stranger refused with nothing written. Eight mutations each
fail a test by name:

- the formula guard dropped;
- the reader check skipped;
- CR/LF left out of the quoting trigger;
- rows left unsorted;
- the route removed;
- the directory not named for tenant and date;
- a text-mode write;
- retired records given findings.

The CR/LF mutation first survived, because the fixture's only multi-line cell
also held a comma. A newline-only cell was added, and the mutation now fails.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1183 tests,
1116 passed, 57 skipped, 10 failed; untouched HEAD `5a4a4f2` in a worktree, run
after it and not alongside: 1169 tests, 1104 passed, 55 skipped, the same 10
failed, compared set for set. `npm --prefix dashboard test` 93/94 (the one
failure is the environmental `api.test.js`, which spawns `python3`). ruff format
and lint pass; mypy reports only the known Windows `fcntl` errors; white-label,
secret-literal and `git diff --check` gates pass. In CI (run 36296832072),
unstubbed: 1126 passed, 57 skipped on 3.10 and 3.12; persistence 236 passed,
so both store-contract export cases ran on MariaDB; dashboard 102/102, the
shared-file case included.

**Partner access held to the register, 2026-09-27.** A service token for an
integration partner now names the register record it acts for (`tokens issue
... --on-behalf-of partners/<id>` or `integrations/<id>`). The link is written
into the entry and onto its grant-ledger line, so an entry re-pointed or
unlinked by hand is high in `tokens review --ledger`. `ironclad oversight
access --tenant T --tokens FILE [--fail-on high|any]` holds every live entry in
the tenant to its record. It is high when the record is missing or retired,
handles PHI without an executed BAA, claims a BAA without evidence, or has a
lapsed review or assurance. It gives a notice for offboarding or a token that
outlasts the next review, and lists staff entries under `unlinked`. It reads
digests only and has no HTTP route. Against the committed Sage Spine seed,
every partner token is high for the missing BAA. That is the intended answer
until the BAAs are executed and recorded.
Tests: 21 functions (28 runs) in `tests/test_partner_access.py`. Four mutations
each fail a test by name: retired not checked, expired entries kept, the link
dropped from the ledger's granted fields, and the reader check skipped.
Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1211 tests,
57 skipped, 10 failed. Untouched HEAD `fa8a096` in a worktree, run after it,
failed the same 10, compared set for set. ruff format and lint pass. mypy
reports only the known Windows `fcntl` errors. The white-label, secret-literal
and `git diff --check` gates pass. Bandit is not installed locally, so CI's
security job is its gate. CI (run 36297903426) passed that gate and
the rest: pytest 1154 passed, 57 skipped on 3.10 and 3.12.

**The access review filed as one packet, 2026-09-27.** Each part of the
Sage Spine access review existed on its own: the register export, the review
queue, the history check and seal, `oversight access`, and `tokens review`
with use and grants. Run separately, that was six commands, six dates, and
nothing tying the outputs together. It also had a tenant problem: `tokens
review` reports every tenant in the file, so a Sage Spine review filed as it
stood would carry other clients' users. HIPAA wants the activity review, the
access review and their documentation kept (164.308(a)(1)(ii)(D), (a)(4),
164.316(b)). `ironclad/access_review.py` and two commands now:

- `ironclad oversight review-packet --tenant T --tokens FILE [--access-log
  LOG] [--ledger LEDGER] --out DIR [--fail-on high|any]` takes every part
  as of one date. It files them as a new directory,
  `access-review-<tenant>-<date>`, written to a temporary sibling and renamed,
  and never over an existing packet. `manifest.json` names each file's
  SHA-256 and size, the token file's SHA-256, the seal digest and both chains'
  anchors. Its `digest` covers the whole manifest.
- The token review runs on the whole file, so a digest shared with another
  tenant is still high. It is then cut to the tenant's entries, the tenant's
  own requests in the log span and the tenant's ledger lines and unrecorded
  grants. The only whole-file figures kept are the two anchors (`N:DIGEST`),
  which the operator records. A log or ledger that is not a whole chain is
  exit 4 with nothing written.
- `ironclad oversight verify-packet DIR [--digest D]` needs no store. It
  names each file as ok, changed or missing, and lists any file not in the
  packet. It checks the manifest against its own digest and, with `--digest`,
  against the line recorded at filing. A manifest rebuilt to fit edited files
  passes every other check, so that line is what catches it.

No route, stored field, rule, token-file field or log line changed. Runbook:
`HANDOFF.md` §17, "File the quarterly access review".

Tests: 21 new cases in `tests/test_access_review.py`, on the committed Sage
Spine seed:

- every file hashed in the manifest;
- the register file byte-equal to the export, with the seal named;
- the summary's counts: six queue highs and one partner high, as the seed says;
- the digest covering who and when, with only the seal changing between runs;
- a stranger, a bad hash and a bad date refused;
- no other tenant's name or user in any file, with requests and ledger lines
  counted per tenant;
- a digest shared across tenants still found, and only the tenant's
  unrecorded grants listed;
- broken chains refused;
- filing, and no overwrite;
- verification of each tampering: changed, missing and added files, a manifest
  edited without its digest, and one rebuilt to fit, caught only with
  `--digest`;
- five CLI runs: file then verify, then edit; the gate tripping after filing;
  a second packet for the day refused; a cut ledger filing nothing; bad input
  filing nothing.

Eight mutations each fail a test by name: the tenant filter dropped, the
unrecorded filter dropped, requests counted across tenants, added files
ignored, the recorded digest ignored, overwrite allowed, a broken chain
accepted, and the manifest's own digest ignored. Two survived the first run.
An added file was only ever tested alongside other problems, and the overwrite
test matched the operating system's rename error. Both tests were tightened
and both mutations now fail.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1232
tests, 1165 passed, 57 skipped, 10 failed. Untouched HEAD `ce81a73` in a
worktree, run after it: 1211 tests, 1144 passed, the same 10 failed, compared
set for set. ruff format and lint pass. mypy over the whole tree reports only
the known Windows `fcntl` errors. The white-label, secret-literal, catalog and
`git diff --check` gates pass. The first push, `1879e07`, was red in CI (run
36298643936): mypy flagged an unannotated tuple in the new test file. Locally,
mypy had been run on the two source files only, not the tree. It is fixed in
the next commit, and the whole tree is now checked locally before a push.

**Each access review held to the last, 2026-09-27.** A packet proved only
itself. Two kinds of change between reviews passed every check. The first is
a register history entry rewritten in place on a volume, which the sweep does
not see. The second is an access log or grant ledger deleted and restarted,
which is whole again on its own. The seal and anchors that would catch them
were in the previous packet, and nothing compared them. `review-packet
--previous DIR [--previous-digest D]` now does. It re-verifies the previous
packet, and refuses one that fails its check, is another tenant's, or is not
earlier (exit 2, nothing filed). It then files `continuity.json`, with three
parts:

- the previous seal compared with today's (`compare_seals`);
- the previous log anchor checked against today's log;
- the previous ledger anchor checked against today's ledger.

Anything rewritten, removed or cut is a high finding. An anchored chain not
supplied this time is `unchecked`, a notice. It is not passed. The manifest
names the previous packet's digest, so the packets form a chain.
`verify-packet --previous DIR` checks that link. Packets without
`continuity.json` still verify. No route, stored field, rule, token-file field
or log line changed. Runbook: `HANDOFF.md` §17.

Tests: 7 new cases in `tests/test_access_review.py` (28 in all):

- a clean quarter linked to the last;
- a history entry rewritten since, where the sweep passes and continuity is
  high;
- a log started afresh;
- an anchored log left out, which is unchecked and not passed;
- four refusals of the previous packet: wrong digest, same date, another
  tenant, tampered;
- `verify-packet --previous` catching an unlinked packet, a different
  previous packet, and a tampered previous packet;
- one CLI run: spring packet, then autumn against it, then a ledger restarted
  from scratch (exit 4 under `--fail-on high`), then a wrong previous digest
  (exit 2).

Nine mutations each fail a test by name:

- the register comparison ignored;
- unchecked counted as verified;
- the previous digest ignored;
- the date order not checked;
- the tenant not checked;
- the link not checked in `verify-packet`;
- broken not added to high;
- unchecked not added to notices;
- a left-out log passed silently.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1239
tests, 1172 passed, 57 skipped, 10 failed. Untouched HEAD `ca1bb29` in a
worktree, run after it: 1232 tests, the same 10 failed, compared set for set.
ruff format and lint pass on the tree. `mypy` (the CI invocation) reports only
the known Windows `fcntl` errors in `policy_store.py`. The white-label,
secret-literal, catalog and `git diff --check` gates pass. In CI (run
36299568259) all six jobs passed: pytest 1182 passed, 57 skipped on 3.10 and
3.12, and persistence 236.

**Rotating the access log without breaking the review, 2026-09-27.** The
runbook said to rotate the access log by stopping the server and moving the
file aside. The next file then started a fresh chain, and the next
`review-packet --previous` reported that as high ("lines were removed from the
end, or the file was replaced"), because a routine rotation and a log deleted
and restarted looked the same. There was no way to give the moved-aside file
back to the review, and `tokens review` could only count use in the current
file, so dormancy was judged on whatever was left after the last rotation.
Now:

- `ironclad access-log rotate LOG --to ARCHIVE --actor A` (`access_log.rotate`),
  run with the server stopped, makes the archive a hard link to the log. The
  link is exclusive, so an existing archive is refused and nothing moves. It
  then replaces the log with one **rotation line**
  (`seq`, `at`, `rotated_from`, `rotated_by`, `prev_hash`, `hash`) carrying the
  next line number and the archive's last digest. It prints the archive's
  anchor and the new one. A log that is not a whole chain is exit 4 and stays
  where it is, as evidence.
- The chain runs on across files. `verify_lines` accepts a rotation line as
  the first line of a file, starting there, and reports `first` and
  `continues` (the archive's anchor). Any other first line must still be
  line 1 from the genesis digest, so lines cut from the front are still
  broken. Anchors are numbered by the chain, not the file.
- `access-log verify`, `tokens review --access-log` and `oversight
  review-packet --access-log` take the archives and the current log, oldest
  first, and verify them as one chain (`access_log.read_files`). An archive
  left out of the middle, given twice or out of order breaks the chain where
  the files should join, and the break is named by file and line. Given the
  current file alone, an anchor from before the rotation is not passed: exit
  4, "give the archives". The packet's manifest records `continues` when the
  log it was given begins after a rotation.
- A server still appending during the rotation holds the old file, which is
  now the archive. Its lines land there, past the line the rotation line
  follows, and break the chain at the join, so they are found and not lost.
  (A copy-and-replace rotation would have sent them to an unlinked file.) If
  the log cannot be replaced, the archive link is removed and the log is as
  it was.
- The token review skips rotation lines when it counts requests.

No route, stored field, token-file field or request line changed. An
existing log verifies exactly as before, and the server reopens a rotated
log and carries on its numbering. Runbook: `HANDOFF.md` §17, "Who used the
register"; reference: `docs/http-api.md`, "Access log".

Tests: 10 new cases. Seven are in `tests/test_access_log.py::TestRotation`:

- the archive byte-equal to the log, the rotation line and anchors, the server
  carrying on the numbering, and the rotated file alone and rotated again;
- an anchor from before the rotation needing the archive;
- lines cut from the front still broken;
- a forged rotation line that fails the anchor;
- archives left out, out of order or repeated;
- a server still writing (on Linux the join breaks; on Windows the replace is
  refused and nothing moves);
- five refusals.

Two are in `tests/test_access_review.py`: continuity across a rotation with
the archive, and high without it; and a CLI packet from an archive and the
current log, refused when they are given backwards. One is in
`tests/test_tokens.py`: the review of a rotated log with its archive
identical to the review of the unrotated log, narrower without it, and
refused out of order. The verdict's shape gained `first` and `continues`,
and one existing assertion was updated for them. Eight mutations each fail a
test by name:

- a rotation line resetting the chain anywhere;
- an anchor from before the rotation not refused;
- anchors numbered by file line;
- a reopened rotated log renumbering from 1;
- a non-exclusive archive;
- rotation lines counted as requests;
- continuity checking only the last line;
- `tokens review` dropping the archives.

Two survived the first run. A rotated file was never anchored read alone, and
the rotation line was dated after the review's `as_of`, so counting it
changed nothing. Both tests were tightened, and both mutations now fail.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1249
tests, 1182 passed, 57 skipped, 10 failed. Untouched HEAD `2485ec8` in a
worktree, run after it: 1239 tests, 1172 passed, the same 10 failed, compared
set for set. On this machine the "server still writing" case takes the
Windows branch, where the replace is refused and nothing moves. The Linux
branch, where the join breaks, runs in CI. ruff format and lint pass on the
tree. `mypy` (the CI invocation) reports only the known Windows `fcntl` errors
in `policy_store.py`. The white-label, secret-literal and `git diff --check`
gates pass. No dashboard file changed.

The first push, `02be93e`, was red in CI (run 36300536001; the duplicate
`push` run 36300533780 was cancelled). Every job passed except pytest on 3.10
and 3.12, where 1 failed and 1191 passed: the "server still writing" case on
its Linux branch. The behaviour was right. The late line landed in the
archive, and the join broke with `access.log line 1: sequence 3 where 4 was
expected`. But the test expected "does not chain", and that branch cannot run
on this machine. The test now asserts that exact reason and that the late line
is the archive's last. In CI at `855337f` (run 36300691285) all six jobs
passed: pytest 1192 passed, 57 skipped on 3.10 and 3.12, persistence 236.

**Refusals on the workspace, seen by its tenant, 2026-09-27.** The access log
recorded a partner's token probing another tenant's register by name with its
403, and nothing read that back out for the tenant whose workspace it was.
`tokens review` counts 403s against the token that got them, so they reach
the *prober's* tenant, and a 401 (no recognised token) reaches nobody: its
line has no user to attribute. Sage's quarterly packet could not show that
anyone outside Sage had reached for Sage's workspace, which is what an
information-system activity review (164.308(a)(1)(ii)(D)) and security-incident
procedures ((a)(6)) look for first. Now:

- `access_log.refusals(entries, tenant, as_of)` groups every 401 and 403 on a
  path under `/api/v1/tenants/<tenant>/` (the segment percent-decoded, so
  `sage%2Dspine` counts), on or before `as_of` in UTC, by the user and tenant
  the line names. Groups are `other_tenant` (high), `unauthenticated` and
  `member` (notices), each with count, first and last, statuses and at most
  ten distinct paths plus a count of the rest, so a caller trying thousands
  of paths is one group. Rotation lines are skipped.
- `ironclad access-log refusals LOG... --tenant T [--as-of D] [--fail-on
  never|high|any]` verifies the log (archives first) and prints that with the
  anchor. It names every caller: the operator's view. Exit 4 under `--fail-on`
  or on a broken chain, 2 for an unreadable file, a tenant that is not a slug
  or a bad date.
- The review packet's `token-review.json` gains `refused_from_outside` when
  built with `--access-log`. Callers from other tenants are merged into one
  group with how many there were and not who; who holds another tenant's
  token is that tenant's business. Unauthenticated callers are the other
  group; the tenant's own members stay on their token-review entries. The
  summary gains the two request counts, and each non-empty group adds one high
  or one notice to the packet's totals.

No route, stored field, token-file field, access-log line or packet file
changed. `token-review.json` gains one key, so a packet filed before this
still verifies and still serves as `--previous`. Runbook: `HANDOFF.md` §17,
"Who used the register" and "File the quarterly access review"; reference:
`docs/http-api.md`, "Access log".

Tests: 7 new cases. Four in `tests/test_access_log.py::TestRefusals`: grouping,
ranking and levels; only this workspace up to the date (another tenant's, a
tenant whose name extends this one's, no workspace, an encoded segment, a line
after `as_of` in UTC, across a rotation); the path cap; and the command's exit
codes and refusals. Two in `tests/test_access_review.py::TestOneTenant`: the
packet carries the refusals with no other tenant's id or user anywhere in any
file, and adds one high and one notice; a quiet workspace files both groups
empty. One in `tests/test_http.py::TestAccessLog` on a real socket: another
tenant's token refused twice and an encoded unauthenticated probe found under
the probed tenant and not under the prober's, and the log module's tenant
prefix held to the server's. Eleven mutations each fail a test by name:

- the segment not decoded;
- another tenant's refusal as a notice;
- the date not applied;
- the path cap removed;
- members classed as another tenant;
- another tenant named in the packet;
- the packet's high not added;
- the packet's notice not added;
- a prefix match instead of the segment;
- rotation lines not skipped;
- `--fail-on high` tripping on notices.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1256
tests, 1189 passed, 57 skipped, 10 failed. Untouched HEAD `d5c8f69` in a
worktree, run after it: 1249 tests, 1182 passed, the same 10 failed, compared
set for set. ruff format and lint pass on the tree. `mypy` (the CI invocation)
reports only the known Windows `fcntl` errors in `policy_store.py`. The
white-label, secret-literal and `git diff --check` gates pass. No dashboard
file or rule changed. In CI at `7b806b6` (run 36301537432) all six jobs
passed: pytest 1199 passed, 57 skipped on 3.10 and 3.12, persistence 236.

**Retiring a partner ends its access, 2026-09-27.** `oversight access` found
a partner token whose register record was retired or missing, and only at the
next review: until someone ran `tokens revoke`, `ironclad serve` kept
answering it. Retiring a business associate in the register did not end the
associate's access, which is the termination step a HIPAA review looks for
(164.308(a)(3)(ii)(C), and the BAA's own termination terms). Now:

- `TokenFileAuthenticator` takes the store as `register`. A token entry with
  `on_behalf_of` is honoured only while the token's own tenant holds that
  record and it is not `Retired`. Otherwise every request is 403 naming the
  link (`partners/drchrono is retired in the register`), on the next request,
  with no restart. The refusal carries the principal, so the access log names
  the holder and `access-log refusals` lists them as a `member` still
  presenting it, instead of an anonymous 401.
- A link to another tenant's record is a record this tenant does not hold:
  refused. A link that is not `partners/<id>` or `integrations/<id>`
  authenticates nobody (401). A linked token with no register to check it
  against, or a store that cannot answer, is 503 and never honoured.
- `ironclad serve` passes its own store as the register. Staff tokens (no
  link) are unaffected.
- Deliberately not enforced: a missing BAA, a lapsed review or assurance, and
  `Offboarding`. They stay findings for the reviewers. Refusing on the BAA
  would cut off every seeded Sage partner, and that is Sage's call to make.

No route, stored field, token-file field, ledger line or access-log line
changed. Runbook: `HANDOFF.md` §17, "Grant, renew and review a service token"
(offboarding is `Offboarding`, then `Retired`, then `tokens revoke`).
Reference: `docs/http-api.md`, authentication.

Tests: 6 new cases in `tests/test_partner_access.py::TestRetiringEndsAccess`:

- retiring refuses the token by name, and a staff token still works;
- `Offboarding` and a missing BAA still serve;
- a missing record, another tenant's record and the wrong kind are each refused;
- no register fails closed as the operator's fault, and a hand-broken link authenticates nobody;
- on a real socket with the access log: 200, then retire, then 403 with the holder named and classed `member`;
- `serve` wires its own store as the register.

Seven mutations each fail a test by name:

- the retired check dropped;
- the missing-record check dropped;
- a linked token honoured with no register;
- a malformed link honoured;
- the principal not handed to the log;
- 401 instead of 403;
- `serve` not passing the store.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1262
tests, 1195 passed, 57 skipped, 10 failed. Untouched HEAD `c34967d` in a
worktree, run after it: 1256 tests, 1189 passed, the same 10 failed, compared
set for set. ruff format and lint pass. `mypy` (the CI invocation) reports
only the known Windows `fcntl` errors in `policy_store.py`. The white-label,
secret-literal and `git diff --check` gates pass. No dashboard file or rule
changed. In CI at `314cfc3` (run 36302226951) all six jobs passed: pytest
1205 passed, 57 skipped on 3.10 and 3.12, persistence 236.

**Granting access the register already withholds is refused, 2026-09-27.**
`tokens issue --on-behalf-of` checked only the link's form. A grant for a
partner the register had retired, or never held, was issued, written to the
token file and recorded on the grant ledger, and then refused by `serve` on
its first request: a grant nobody could use, on the record as approved
access. Now:

- `tokens issue` holds the link to the register before anything is written,
  by the rule `serve` applies (one function, `tokens.link_withdrawn`, used by
  both): the store named by the new `--register` (default `$IRONCLAD_STORE`)
  must hold the record in `--tenant`, and it must not be `Retired`. Otherwise
  exit 2 naming the reason (`partners/drchrono is retired in the register;
  `serve` would refuse this token`), and neither the token file nor the
  ledger is touched.
- Fail closed, as `serve` does: a linked issue with no register named, a
  store that does not hold the register, or one that cannot answer is
  refused rather than trusted.
- Unchanged: staff grants (no link) need no register; `Offboarding` and a
  missing BAA are still granted, since they are review findings rather than
  refusals; a malformed link is still refused by its form, without asking
  for a register.

No route, stored field, token-file field, ledger line or access-log line
changed. Runbook: `HANDOFF.md` §17, "Grant, renew and review a service token".
Reference: `docs/http-api.md`, authentication.

Tests: 9 new cases in `tests/test_partner_access.py::TestIssueHeldToTheRegister`
(a live record granted; the store variable as default; `Offboarding`
granted; retired refused; missing, another tenant's and wrong-kind records
refused; no register, a store without one and a store that fails each
refused; a malformed link named without asking for a register), each
refusal asserting nothing was written. The existing CLI cases that issue a
linked token now name the register. Six mutations each fail a test by name:
the check not called, retired honoured, missing record honoured, no register
trusted, store errors not wrapped, a malformed link sent to the register.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1271
tests, 1204 passed, 57 skipped, 10 failed. Untouched HEAD `fa7c867` in a
worktree, run after it: 1262 tests, 1195 passed, the same 10 failed, compared
set for set. ruff format and lint pass. `mypy` (the CI invocation) reports
only the known Windows `fcntl` errors in `policy_store.py`. The white-label,
secret-literal and `git diff --check` gates pass. No dashboard file or rule
changed. In CI at `441f740` (run 36302969029) all six jobs passed: pytest
1214 passed, 57 skipped on 3.10 and 3.12, persistence 236.

**A partner token with no end date, or one outlasting the assurance, 2026-09-27.**
`oversight access` reported a linked token with no `expires_at` as clean
when its record was in order, though that token outlasts every date the
register holds the partner to. `tokens issue` never writes one, so such an
entry was written by hand. It also said nothing when a token ran past the
partner's certificate/assurance expiry, only past its next review. Now:

- `no-expiry`, high: a linked, live entry with no `expires_at`. It is
  reported next to any register finding, not instead of one. Staff tokens
  without one stay under `unlinked`, where `tokens review` already gives a
  notice.
- `outlasts-assurance`, notice: the token runs past `cert_expiration_date`
  while that date is still ahead. It is the same rule as `outlasts-review`,
  which is unchanged. A token ending on the date does not outlast it, and a
  date already past stays `assurance-expired` (high).

The server's behaviour is unchanged: it still refuses only retired or missing
records. No route, stored field, token-file field, ledger line or access-log
line changed. The CLI help, `HANDOFF.md` §17 ("Grant, renew and review a
service token") and `docs/http-api.md` name both findings.

Tests: 5 new cases in `tests/test_partner_access.py::TestPartnerAccess`:

- outlasting the assurance is a notice;
- ending on the assurance date is clean;
- outlasting both dates names both;
- no expiry is high and leaves the staff token alone;
- no expiry is reported next to the BAA and missing-record findings.

The queue-notices case now issues its token to end before the record's
assurance date, so it still tests what it tested. Five mutations each fail a
test by name:

- the no-expiry check dropped;
- no-expiry made a notice;
- assurance not checked;
- a token ending on the date counted as outlasting it;
- a lapsed date counted as outlasting.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1276
tests, 1209 passed, 57 skipped, 10 failed. Untouched HEAD `ba6dc94` in a
worktree, run after it: 1271 tests, 1204 passed, the same 10 failed, compared
set for set. ruff format and lint pass. `mypy` (the CI invocation) reports
only the known Windows `fcntl` errors in `policy_store.py`. The white-label,
secret-literal and `git diff --check` gates pass. No dashboard file or rule
changed. In CI at `22af04a` (run 36303657549) all six jobs passed: pytest
1219 passed, 57 skipped on 3.10 and 3.12, persistence 236.

**Offboarding a partner revokes all of its access in one act, 2026-09-27.**
The runbook's last offboarding step was "`tokens revoke` the entry", but
`revoke` took only a user, a digest prefix or `--expired`. A partner with
several holders (an ops account and a named user, say) was revoked one
holder at a time, and a holder missed stayed in the file: refused by `serve`
once the record is retired, and still high in `oversight access`, on the
ledger as granted and never revoked. Now:

- `tokens revoke FILE --tenant T --on-behalf-of partners/<id>` (or
  `integrations/<id>`) removes every entry in `T` acting for that record,
  whoever holds it, expired entries included. Each removal is its own
  ledger line carrying the link, written before the file is replaced, as
  for every revocation.
- It does not consult the register. Cutting access off never waits on the
  store, and it works whatever the record's state (live, retired, deleted).
- Refused, with nothing written: a link without `--tenant`, a link together
  with `--user` or `--expired`, a malformed link, or a record no entry in
  the tenant acts for. The same record in another tenant is untouched.

No route, stored field, token-file field, ledger field or access-log line
changed. Runbook: `HANDOFF.md` §17, "Grant, renew and review a service
token". Reference: `docs/http-api.md`, authentication.

Tests: 9 new cases in `tests/test_partner_access.py::TestOffboardingRevokesByRecord`:

- every holder in the tenant goes, an expired one included, and nothing else
  (another partner, staff, the same link in another tenant);
- six refusals that remove nothing;
- the command, with the record already retired and no register named,
  removes both holders, writes one `revoke` line each with the link, and
  leaves a file the review calls clean;
- the command refusing a record nobody holds leaves the file byte-identical
  and writes no ledger.

Five mutations each fail a test by name:

- the tenant not checked;
- a link without a tenant allowed;
- the link's form not checked;
- `--tenant` read as a user selector;
- the CLI not passing the link.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1285
tests, 1218 passed, 57 skipped, 10 failed. Untouched HEAD `3b64a25` in a
worktree, run after it: 1276 tests, 1209 passed, the same 10 failed, compared
set for set. ruff format and lint pass. `mypy` (the CI invocation) reports
only the known Windows `fcntl` errors in `policy_store.py`. The white-label,
secret-literal and `git diff --check` gates pass. No dashboard file or rule
changed. In CI at `cfc6fbe` (run 36304211252) all six jobs passed: pytest
1228 passed, 57 skipped on 3.10 and 3.12, persistence 236.

**The quarterly packet lists what changed in the quarter, 2026-09-27.** The
packet filed who holds access on the review date, and only counted the
tenant's ledger lines. A partner granted in July and offboarded in August
(the one-act revocation above) was in no packet's entries, and nothing in the
packet said the grant or the removal had happened. HIPAA's access review
(164.308(a)(4)(ii)(C)) and termination procedures ((a)(3)(ii)(C)) ask about
that too. Now, with `--ledger`:

- `token-review.json` holds `ledger.changes`: each of the tenant's grants and
  revocations in the period, oldest first. Each shows who took it, the holder,
  roles, expiry, register link and digest prefix (never the digest).
- The period ends on the review date. Filed against the previous packet, it
  starts the day after that packet's date, so each change is in exactly one
  packet. A line is placed by the time it was written, not the `--as-of` its
  writer typed. A line whose time cannot be read is listed, not dropped.
- A grant whose issuer is its own holder is a notice: nobody else approved
  that access.
- The manifest summary carries `access_changes` (since, through, granted,
  revoked, self-granted).

Only the tenant's lines are listed. The existing isolation test fails too if
another tenant's line gets in. No route, stored field, token-file field,
ledger line or access-log line changed. No file was added to the packet, so
`verify-packet` and packets already filed are unaffected. The runbook in
`HANDOFF.md` §17 ("File the quarterly access review") and the CLI help
describe it.

Tests: 6 new cases in `tests/test_access_review.py::TestAccessChanges`:

- a partner granted and offboarded inside the period is listed, digest cut
  to its prefix;
- only the tenant, and nothing after the review date;
- filed against the last review, only the quarter since;
- a grant to oneself is a notice, matched without regard to case;
- a line whose time cannot be read is listed;
- without a ledger there is no list.

The CLI next-quarter case checks the period starts at the previous packet's
date. Seven mutations each fail a test by name:

- `since` ignored;
- `since` not passed;
- another tenant's lines kept;
- lines after the review date kept;
- a self-grant not counted;
- a self-grant compared case-sensitively;
- an unreadable time dropped.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1291
tests, 1224 passed, 57 skipped, 10 failed. Untouched HEAD `73482e2` in a
worktree, run after it: 1285 tests, 1218 passed, the same 10 failed, compared
set for set. ruff format and lint pass. `mypy` (the CI invocation) reports
only the known Windows `fcntl` errors in `policy_store.py`. The white-label,
secret-literal and `git diff --check` gates pass. No dashboard file or rule
changed. In CI at `c93c84e` (run 36304978752) all six jobs passed: pytest
1234 passed, 57 skipped on 3.10 and 3.12, persistence 236.

**The packet says what its counts refer to, 2026-09-27.** The manifest
summary gave `high: 7, notices: 1` and nothing else. To find the seven, a
reviewer searched six files, each counting its own way: the queue by record,
partner access by holder, the token review by entry, and each with extra
notices from the ledger, the refusals and continuity. Now:

- `summary.findings` holds a `high` and a `notices` list. There is one entry
  for each finding the summary counts, so `high` and `notices` are the
  lengths of these lists and cannot drift from them. Each entry names the
  file (`part`), what it is about (`subject`: a record, a holder and link, a
  token by user and digest prefix, a chain, or the merged refusals) and its
  `messages`.
- A token with a high finding and a notice is in both lists, each with its
  own messages, as `tokens review` counts it.
- Refusals from outside stay merged and unnamed. The index names no one the
  files do not already name.
- It is in the manifest, so the recorded digest covers it. `review-packet`
  prints it at filing.

No file was added to the packet, and every count is the same as before. The
existing count tests pass unchanged, so `verify-packet` and packets already
filed are unaffected. No route, stored field, token-file field, ledger line
or access-log line changed. The runbook in `HANDOFF.md` §17 ("File the
quarterly access review") and the CLI help describe it.

Tests: 6 new cases in `tests/test_access_review.py::TestTheFindingsIndex`:

- every count comes with what it counts, with the part and messages;
- a token with a high finding and a notice is in both lists;
- self-granted and unrecorded grants are listed;
- refusals from outside are listed without naming anyone;
- what changed since the last packet is listed, broken and unchecked;
- a register history that does not verify is listed.

The CLI filing case checks that the printed index matches the manifest's.
Eight mutations each fail a test by name:

- token notices dropped;
- unrecorded grants dropped;
- self-grants dropped;
- the outside levels swapped;
- an unchecked chain dropped;
- a failed sweep not listed;
- register continuity dropped;
- the index left out of the summary.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1297
tests, 1230 passed, 57 skipped, 10 failed. Untouched HEAD `c93c84e` in a
worktree, run after it: 1291 tests, 1224 passed, the same 10 failed, compared
set for set. ruff format and lint pass. `mypy` (the CI invocation) reports
only the known Windows `fcntl` errors in `policy_store.py`. The white-label,
secret-literal and `git diff --check` gates pass. No dashboard file or rule
changed. CI: pending at the time of writing.

Still open for this workspace: the page still writes Firestore. Pointing it at
these routes needs a browser sign-in to `ironclad serve` (B6). Loading the seed into the real NAS store needs B1–B3 and is out of
the REVIEW ONLY posture; into a volume it is `load_seed` and is tested.

Local evidence for the change-history pass, 2026-09-26: `npm --prefix dashboard
test` 70/71 (same environmental `api.test.js` failure as below); `node --check`
on the rules suite; white-label and secret-literal gates pass. The rules change
itself is proven only by the emulator job in CI — no JDK here — and it passed
there: 88/88 in run 36282209801, the ten history cases among them.

Local evidence, 2026-09-26 (Windows 11, Node 24, Python 3.12 venv):
`npm --prefix dashboard test` 68/69 — the one failure is `api.test.js`, which
spawns `python3` and fails identically on untouched `791f510`; ruff format and
lint pass; white-label and secret-literal gates pass; catalog current. The
emulator suite needs a JDK, which this machine does not have — it is proven in
CI. mypy/pytest/artifact failures locally are Windows-only (`fcntl`, symlinks,
CRLF checkout) and none touch changed files.

## Gate results

Run on this branch, this machine, 2026-09-06.

| Gate | Command | Result |
|---|---|---|
| Format | `ruff format --check .` | **PASS** — 90 files |
| Lint | `ruff check .` | **PASS** |
| Typecheck | `mypy` | **PASS** — 81 source files |
| Test | `pytest` | **PASS** — 844 passed, 30 skipped locally (2026-09-17; the extraction extras and MariaDB account for the skips, and both have now run locally too); 93% coverage at the last CI measurement |
| Cloud Functions | `npm --prefix functions test` | **PASS** — 44 passed |
| Dashboard | `npm --prefix dashboard test` | **PASS** — 60 passed (on the committed tree, 2026-09-23) |
| Firestore rules | `npm --prefix tests/rules test` | **PASS** — 88 passed against the emulator (CI run 36282209801, 2026-09-26) |
| Persistence | `pytest tests/test_store.py` | **PASS** — 70 passed in CI against MariaDB 10.5.29 |
| End-to-end | `scripts/end_to_end.py` | **PASS** in CI against MariaDB **and** a volume |
| Artifacts | `python scripts/validate_artifacts.py` | **PASS** — 13/13 |
| Catalog | `python tools/build_catalog.py --check` | **PASS** — committed catalog current |
| Build | `python -m build` | **PASS** — sdist + wheel |
| Security — dependencies | `pip-audit -r requirements*.txt` | **PASS** — no known vulnerabilities |
| Security — secret literals | `sh scripts/check_secret_literals.sh` | **PASS** — no credential-shaped literals; one script for CI, `gates.sh` and Jenkins since 2026-09-17 |
| Security — white-label | `sh scripts/check_white_label.sh` | **PASS on the committed tree; FAIL on the working tree** — see the note at the top |
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

Green on `productize/ironclad-compliance` at `c5d167a`, run
[35183274645](https://github.com/IronCityIT/ironclad-compliance/actions/runs/35183274645):
Quality gates (3.10) ✅ · Quality gates (3.12) ✅ · Cloud Functions and dashboard ✅ ·
Persistence and end-to-end ✅ · Firestore rules ✅ · Security gate ✅

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
- **Every permission refusal is exercised.** `api/service.py` 84% → 100%: a
  viewer running an assessment, an auditor running one, a contributor revoking
  an acceptance, a stranger reading another tenant's assessments, a viewer
  reading the exception register. A refusal that silently succeeded would be a
  viewer revoking a risk acceptance. Coverage across the engine is 93%.
- **A policy file that validates now also loads.** `ironclad validate --policy`
  accepted a rejected acceptance and `load_policy` then raised on it: the replay
  never submitted the exception, and the state machine correctly refuses
  draft → rejected. An expired one was not replayed at all and came out as a
  draft, silently discarding the status the file claimed. Every status a policy
  may carry — draft, pending, approved, rejected, revoked, expired — now
  validates and loads into that state. `policy.py` 86% → 97%.
- **A withdrawn decision does not make a failing control disappear.** Asserted
  end to end: with a rejected, revoked, expired, draft or still-pending
  acceptance on CC1.1, the control does not read as `accepted_risk`; with a live
  approval it does, so the negative tests are not passing because nothing works.
- **Evidence extraction, where a met control becomes a gap if it goes wrong.**
  `ironclad/ingest/extractors.py` was the least covered module in the engine at
  52% and the most consequential: a document that fails to extract produces no
  matched terms, so the control it supports reads as unevidenced. 92% in CI now,
  with the failure paths asserted individually — corrupt file, empty file,
  truncated zip behind a `.docx`, missing dependency, unsupported suffix, no
  suffix — each coming back as a named error with empty text rather than as an
  empty document.
- **The PDF reader is a maintained one.** PyPDF2 announces its own deprecation
  on import and no longer receives fixes; this parser reads documents a client
  uploads. `pypdf` is preferred, PyPDF2 still accepted.
- **The whole path agrees with itself.** `scripts/end_to_end.py` ingests the
  sample evidence, assesses it, renders the deliverables, publishes and reads
  the record back — against MariaDB and against a volume, in CI on every push.
  It checks the readiness a client reads is the readiness stored, the chain head
  matches, the queue is the tenant's own, and re-publishing leaves one record.
- **A trend that moves the right controls.** Adding a risk assessment and a
  change management policy to the sample evidence moved readiness 46.5% → 63.5%,
  improved 12 controls and closed 7 remediation items — and the controls that
  moved are CC3.1–CC3.4, CC8.1, CC9.1 and CC9.2, which are the ones those two
  documents actually evidence.
- **A tenant's evidence prefix cannot be escaped**: a traversal, a path-shaped
  client id that would normalise into a different valid tenant, a symlink on the
  prefix, and a symlink on a file inside it are each refused, and an empty
  prefix is refused rather than assessed as nothing.
- The persistence seam against a **real MariaDB 10.5.29** in CI: schema applied
  (7 statements), 70 store tests passed. Two defects it found on its first real
  run, both invisible to a mock — MariaDB truncates silently without a strict
  `sql_mode`, and remediation item ids being deterministic on (tenant, control)
  meant a client's *second* assessment collided with their first. Then a third,
  worse than either: the projection was truncating in Python before the database
  ever saw the value, on both backends. Nothing is truncated now; an over-long
  value is refused with its table, column and length named.
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

- **The HTTP surface, refusal by refusal, on a real socket.** `ironclad serve`
  gives the dashboard a backend that is not Firebase: 59 tests speak HTTP to a
  `ThreadingHTTPServer` on a loopback port, including the command run as a
  subprocess. Fail-closed without a token file (503, not open); a stranger's
  read and write are 403 and leave nothing on the policy volume; the body
  cannot redirect a write to another tenant or name a different requester;
  request → approve → revoke lands in `policy.json` with a chained trail. Four
  defects on the first run, recorded in `PRODUCTIZE_NOTES.md` §13 — the one
  that matters most: over HTTP, `requested_by` from the body would have let a
  manager approve their own acceptance.
- **The white-label gate now reads the surface, not a list.** It enumerated
  four files; a fifth in `dashboard/public/` was served and unread. One script
  scans the directories, in CI, `gates.sh` and Jenkins (which had no such
  check), and it is red on the working tree for exactly the reason it should
  be.

- **The evidence directory is a boundary (2026-09-16).** A tenant's own
  `manifest.json` could name `../other-client/policy.pdf` or `/etc/passwd`
  and the engine read it, matched it and linked it to the tenant's controls
  with the path on their record; staging confined the prefix but not what the
  prefix's manifest pointed at. Every local URI must now resolve inside the
  directory, symlinks are refused rather than followed, and `.DS_Store`,
  `.git/` and `__MACOSX` are not evidence. Reproduced, fixed, re-run:
  `PRODUCTIZE_NOTES.md` §16.1–16.2, 16.8.
- **A risk acceptance can be renewed (2026-09-16).** Request → approve →
  revoke → request again was a 500 over HTTP and the CLI alike: the policy
  file's one-per-control rule counted history, so a lapsed acceptance blocked
  the renewal the engine's own "lapsed" finding asks for — and nothing swept
  lapsed approvals on file. Replayed against the restarted server: the
  renewal lands `[revoked, pending_approval]`. Nine more inputs a browser
  would not send, a swapped `compare`, and non-JSON files to `report`,
  `export`, `compare` and `validate` each get a named refusal instead of a
  traceback or a coerced value. §16.4–16.9.

- **The scoring cannot be talked into a verdict (2026-09-17).** Three ways a
  tenant's own files moved the number, each tried and closed: a copy of a
  document counted as the corroborating second (one document now, by bytes
  or by text); a manifest's `collected_at: 2030` made a review fresh for
  years (pulled back to ingestion, named) and a `valid_until: 2099` was
  accepted silently (stands, disclosed); two remote URIs nobody read, each
  hinting every control id, scored **100%** (held at partial, named). A
  document that *is* the framework's wording still scores 100% — keyword
  matching cannot tell a quoting policy from a copy — and is now named as
  such in the caveats rather than believed quietly. §16.15–16.18.
- **The trend could not tell a decision from progress (2026-09-17).**
  Accepting every gap read as "11 improved, 27 remediation items closed";
  a quick-group run followed by a deep one read as "27 opened". Acceptance
  is a decision in either direction now, an item set aside by acceptance or
  scope is not closed, and a side that never planned remediation is named.
  The same pair reads "0 improved, 0 closed; 27 accepted as risk". §16.36.
- **Nothing could ever be overdue (2026-09-17).** Every run re-dated its
  remediation items to today, so a control outstanding for six months read
  "due in 30 days" in every report. With the previous assessment — which
  both pipelines now fetch — an open item keeps its first-raised and target
  dates, the caveats name the overdue controls and the report marks the rows.
  Proven on the throwaway controller: 27 items carried from the earlier
  stored plan, dates unchanged. §16.35.
- **The dashboard card says how far to trust the number (2026-09-17).**
  Every caveat the engine raises reached the report and the record and the
  card showed the bare figure; it now shows the scoped-out count, names a
  stage that did not complete, and lists the first three caveats. §16.34.
- **MariaDB, from this machine (2026-09-17).** Two more store defects the
  CI suite could not see: a record read back as the number 46.5 from the
  volume and the string "46.50" from MariaDB through the API's JSON; and
  two clients handing in the same `scan_id` — a standard dispatch input now
  — was an IntegrityError for the second on MariaDB and two records on the
  volume. Rows are normalised, the key is `(tenant_id, assessment_id)` with
  composite child keys, and contract tests on both stores hold them alike.
  Nothing initialised from the old schema exists outside CI and the scratch
  server. §16.32–16.33.
- **The trend reaches the report (2026-09-17).** The comparison existed and
  nothing in either pipeline fetched the previous assessment; now both do,
  from the store, and the auditor package carries the report as issued
  rather than a re-render that lost the section. MariaDB found to be
  installed here: 73 store tests and the round trip pass against 10.11,
  twenty concurrent publishes land clean, and `compare --client` now works
  against it. §16.29–16.31.
- **The Jenkins pipeline ran (2026-09-17).** On a throwaway controller in
  the scratchpad with only the Docker agent substituted: nine builds, every
  runnable gate green, the assessment mode publishing to a volume store
  through a credential. Found four defects the linter could not — a
  plugin-only cleanup step, gate accumulators that never reached `post`, a
  publish stage wired to the retired ingest alone, and the restore check
  reading a tenant's trail as one chain, which broke on the second
  assessment into any store used twice. §16.26–16.28.
- **Three pipelines, one set of gates (2026-09-17).** A parity test written
  to hold `ci.yml`, `gates.sh` and the Jenkinsfile together failed first
  against CI: the catalog check that keeps the dashboard's `catalog.json`
  equal to the registry ran everywhere but CI. It runs there now; the
  secrets check is a shared script rather than inline shell in one place;
  the Jenkins security gate matches CI's. §16.25.
- **What a file costs to open (2026-09-17).** With the extraction extras in
  a venv for the first time on this machine: a 0.57 MB `.docx` expanding to
  143 MB took 19 s and 545 MB to yield 20,000 characters — four of them and
  the assess job is out of memory. The zip's own table of contents is read
  first and a member past 50 MB is refused unopened; text files are read only
  as far as the clip; `pypdf` already refuses a stream bomb on its own. The
  models' advice is white-labelled at merge time, since it is the one text
  the gate cannot scan. consensus-engine PR #6 measured against the real
  artifact: 707 KB → 87 KB, folds clean. §16.22–16.24.
- **The record store under load (2026-09-17).** Twenty concurrent acceptance
  requests: fourteen answered 200, eight were on file, six read a half-written
  policy and got a 500. The policy store now holds a file lock across each
  write path and replaces both files atomically; replayed, 20 of 20 land and
  the audit chain holds. §16.21.
- **Also 2026-09-17:** `ironclad serve` closes a stalled connection after
  30 s instead of holding its thread forever; the auditor package carries a
  digest for every file and a `SHA256SUMS`; `store verify` lists every fault;
  the workflow speaks the standard `client_name`/`scan_id` inputs, proven by
  a third dry run. §16.10–16.14.

## Dry runs — the product workflow has now executed

`Compliance Assessment` gained a `dry_run` input: the synthetic sample
evidence, every stage, artifacts uploaded, nothing published, the assessment
id suffixed `-dry-run`. Dispatched twice on this branch against the throwaway
client "ICIT Dry Run", framework `soc2`. Full account in
`PRODUCTIZE_NOTES.md` §15.

| Run | prepare | assess | ai-consensus | report | What it proved |
|---|---|---|---|---|---|
| [34722216087](https://github.com/IronCityIT/ironclad-compliance/actions/runs/34722216087) | ✅ | ✅ 46.5% | ❌ 23 min | ✅ | The engine analysed all 57 findings — 14 of 15 models on every one — then the job failed at the **1 MB job-output cap** ("Maximum object size exceeded"). The report ran with `consensus: unavailable`. Reading the artifact it also uploaded showed the merge would have rejected the result anyway: a list, and field names the merge never read. |
| [34723682288](https://github.com/IronCityIT/ironclad-compliance/actions/runs/34723682288) | ✅ | ✅ 46.5% | ❌ 13 min | ✅ **`consensus status: ok analysed: 25 of 25`** | On the fixed workflow: 25 findings sent (one per control, gaps only, capped), the report job read the engine's **artifact** — 707 KB — merged it, rendered the report with the commentary block populated, exported the auditor package, validated the artifacts, published nowhere. The AI job is still red: 25 results are 0.9 MB base64 and the step output is counted alongside the job output. |
| [35170758865](https://github.com/IronCityIT/ironclad-compliance/actions/runs/35170758865) | ✅ | ✅ 46.5% | cancelled while queued | ✅ `consensus: unavailable` | 2026-09-17, dispatched with the **standard input names** `client_name` and `scan_id` (§16.14): the client resolved, the scan id became the assessment id with `-dry-run` suffixed, the report and package rendered, nothing published. The AI stage was cancelled deliberately — it proves nothing about input names and costs 13 minutes of model calls. |
| [35183541091](https://github.com/IronCityIT/ironclad-compliance/actions/runs/35183541091) | ✅ | ✅ 46.5% | cancelled while running | ✅ | 2026-09-17, after the report job learned to take the previous assessment from the assess job and to package the report as issued (§16.30–16.35): the absent `previous-assessment` artifact is tolerated, the report renders without a trend, the package carries the issued report, artifacts valid, nothing published. |

The red AI job is the engine's output size, not its analysis. Fixed at the
source in **[consensus-engine PR #6](https://github.com/IronCityIT/consensus-engine/pull/6)**
(REVIEW ONLY — opened, not merged): the output drops the model transcripts,
which were ~90% of the bytes; the artifact keeps them. Until it merges, the
report is right and the run summary says so — it reports the fold's outcome
and the AI job's status side by side.

Seen in both runs and belonging to the engine's owner: `gemini-flash` **403
Forbidden on all 82 calls** — `GEMINI_API_KEY` is rejected or the project
behind it is not enabled — and `gpt-oss-20b` returning no JSON on 27 of 82.

**Not proven — needs a GitHub runner:**

The evidence-staging and publishing steps of the product workflow — a real
tenant's evidence from a volume, a real store — are exactly the steps a dry
run skips, and they need the transport decision (HANDOFF §3.2). The framework
update checker workflow has not been dispatched from this branch.

**Partly proven — the Jenkins pipeline, on a throwaway controller (2026-09-17):**

`Jenkinsfile` passes the declarative linter and, with only its Docker agent
substituted by `agent any`, ran four builds on a Jenkins started in the
scratchpad: every gate green in order, the Firestore emulator and the node
suites included, `persistence` UNAVAILABLE without MariaDB and the build
UNSTABLE as designed. The runs found three defects in the file — a
plugin-only cleanup step, a description that was never set, and gate
accumulators that never reached `post` — and one in the store: the restore
check read a tenant's trail as one chain and broke on the second assessment
(§16.27). Not proven: the `python:3.11-slim` Docker agent, and ICIT's own
controller and plugin set. The two credential ids the assessment stage binds
(`ironclad-store-results-url`, `ironclad-ingest-api-key`) do not exist yet.

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

## Live evidence from `main`

**Correction to an earlier entry.** This previously recorded that the fixed
checker "reported `updates_found=false` for all four" across two live runs, as
evidence it does not false-positive. That was true and it was not the whole
story: it could not false-positive on three of the four because **it was seeing
nothing at all**. `meta` and `link` were in the extractor's skip set and both are
void — `<meta charset="utf-8">` has no closing tag — so the skip counter went up
on the first one in `<head>` and never came back down, discarding every text
node after it. SOC 2, PCI DSS and HIPAA were being fingerprinted as the empty
string, compared against the empty string, and reported unchanged with
confidence. NIST worked only because that page self-closes its meta tags.

Fixed, and the first working run found a real update — see below.

Applying the *original* rule to the same pages: it reports an update on NIST,
matching the word "latest", where the current rule reports unchanged. That
comparison stands; it is the reason PR #3 exists.

### The first working run found a real one: PCI DSS 4.0.1

With the extractor fixed, all four sources yield real text — 5,368 to 9,139
characters — and the checker immediately reported:

```
! PCI Data Security Standard: version_detected — The source advertises 4.0.1
  while this repository tracks 4.0.
```

**This is a true positive and an open product task.** `frameworks/pci-dss-4.0.json`
carries 27 controls against 4.0; the source publishes 4.0.1. The control text
has not been touched here — the checker never transcribes a regulator's wording
and neither does this session. Reading the published document and updating the
control set, the version in `framework-versions.json` and the affected
crosswalks is work for someone who can read the standard.

A second run against the recorded fingerprints reported `unchanged` for the
other three and the same version detection for PCI, so the result is stable
rather than a one-off.

```
framework                          old rule                       new rule
SOC 2 Trust Service Criteria       no update                      unchanged
NIST Cybersecurity Framework       UPDATE — matched 'latest'      unchanged
PCI Data Security Standard         no update                      unchanged
HIPAA Security Rule                no update                      unchanged
```


**PR #3 is an open false positive.** The quarterly framework checker on `main`
matched the word "latest" on three standards pages and reported all three as
updated — its own diff says `"details": "Found 'latest'"` for each. It also adds
`updates.json`, which `.gitignore` excludes. Both defects are fixed on this
branch; the finding is recorded as a comment on PR #3, which needs closing
rather than merging. Not closed here — that is Bill's call.

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
  -f client_name="icit-internal" \
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

That promise had nothing behind it until now — none of them had a test, and one
had stopped keeping it. **`assess_controls.py` had no `--policy` flag and did not
look for a policy beside the evidence**, so a client's scope exclusions and risk
acceptances were silently not applied: a control the client had formally
accepted came back as a gap. Fixed, and both entry points are now asserted to
reach identical verdicts and an identical readiness score over the same evidence
and policy. Its `--assessment-type` is constrained to the real set too; it used
to accept anything and fall back to the full view without a word.

`generate_report.py` and `check_framework_updates.py` were checked against the
engine and are faithful. `store_results.py` is the retired ingest path and goes
with `functions/`.
