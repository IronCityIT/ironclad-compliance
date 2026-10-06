# STATUS — Ironclad Compliance productization

> **Architecture change, 2026-09-07.** Firebase, Firestore, Firebase Hosting and
> GCP product storage are **retired from the target architecture**. GitHub
> Actions stays the orchestration layer; persistent state moves to NAS-backed
> MariaDB and NAS volumes. The Firebase components described below are the
> *current implementation*, not the target. `HANDOFF.md` classifies every
> reference and stages the migration; nothing is migrated or deleted yet.

**Branch:** `productize/ironclad-compliance` · **Updated:** 2026-10-06
**PR [#4](https://github.com/IronCityIT/ironclad-compliance/pull/4) is open. CI green at `963a0e0` (run 37483793265, `pull_request`; the duplicate `push` run 37483780341 also ran to completion, green, after the cancel returned HTTP 502), a STATUS-only commit. Green before that at `9b51ec8` (run 37483094514, `pull_request`; the duplicate `push` run 37483086366 was cancelled): all six jobs, pytest 1770 passed / 57 skipped on 3.10 and 3.12 (the control-new case among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `5d54788` (run 37480274665, `pull_request`; the duplicate `push` run 37480264290 was cancelled), a STATUS-only commit. Green before that at `c33cf00` (run 37479720179, `pull_request`; the duplicate `push` run 37479715352 was cancelled): all six jobs, pytest 1769 passed / 57 skipped on 3.10 and 3.12 (the first-planned case among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `2b48f30` (run 37475932563, `pull_request`), a STATUS-only commit. Green before that at `7294a1e` (run 37474988157, `pull_request`; the duplicate `push` run 37474977721 also ran to completion, green, before it could be cancelled): all six jobs, pytest 1768 passed / 57 skipped on 3.10 and 3.12 (the unplanned-remediation case among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `8603c38` (run 37471985600, `pull_request`), a STATUS-only commit. Green before that at `2cd32bf` (run 37471526870, `pull_request`; the duplicate `push` run 37471518420 was cancelled): all six jobs, pytest 1767 passed / 57 skipped on 3.10 and 3.12 (the control-gone case among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `af57bc0` (run 37468469600, `pull_request`), a STATUS-only commit. Green before that at `ed4ae22` (run 37468114223, `pull_request`; the duplicate `push` run 37468108959 was cancelled): all six jobs, pytest 1766 passed / 57 skipped on 3.10 and 3.12 (the met-control-accepted case among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `5857b14` (run 37392331446, `pull_request`), a STATUS-only commit. Green before that at `30a2d05` (run 37391953932, `pull_request`; the duplicate `push` run 37391947692 was cancelled): all six jobs, pytest 1765 passed / 57 skipped on 3.10 and 3.12 (the 9 coverage cases among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `8373959` (run 37160823081, `pull_request`), a STATUS-only commit. Green before that at `75e6694` (run 37160622941, `pull_request`; the duplicate `push` run 37160620882 was cancelled): all six jobs, pytest 1755 passed / 57 skipped on 3.10 and 3.12 (the 104 contract cases among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `3878395` (run 36572118011, `pull_request`), a STATUS-only commit. Green before that at `bb55e53` (run 36571709136, `pull_request`; the duplicate `push` run 36571702107 was cancelled): all six jobs, pytest 1651 passed / 57 skipped on 3.10 and 3.12 (the 65 route-table cases among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `f6fddec`, a STATUS-only commit. Green before that at `560d83a` (run 36506607757, `pull_request`; the duplicate `push` run 36506603473 was cancelled): all six jobs, pytest 1586 passed / 57 skipped on 3.10 and 3.12 (the 108 pipeline-command cases among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `700330c` (run 36504606343, `pull_request`), a STATUS-only commit. Green before that at `2dd7962` (run 36504361651, `pull_request`; the duplicate `push` run 36504358291 was cancelled): all six jobs, pytest 1478 passed / 57 skipped on 3.10 and 3.12 (the 106 documented-command cases among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `c4af49b` (run 36452255052, `pull_request`; the duplicate `push` run 36452248979 was cancelled), a STATUS-only commit. Green before that at `0474cd0` (run 36451793517, `pull_request`; the duplicate `push` run 36451788045 was cancelled): all six jobs, pytest 1372 passed / 57 skipped on 3.10 and 3.12 (the 10 assurance-horizon cases among them), persistence 339, dashboard 117/117, Firestore rules 96/96. Green before that at `ed7fcf7` (run 36360159305, `pull_request`), a STATUS-only commit. Green before that at `1ccac5c` (run 36359967726, `pull_request`; the duplicate `push` run 36359965725 was cancelled): all six jobs, pytest 1362 passed / 57 skipped on 3.10 and 3.12 (the 7 network-exposure cases among them), persistence 329, dashboard 116/116, Firestore rules 96/96. Green before that at `f558238` (run 36345014196, `pull_request`), a STATUS-only commit. Green before that at `91139bc` (run 36344766255, `pull_request`; the duplicate `push` run 36344763342 was cancelled): all six jobs, pytest 1355 passed / 57 skipped on 3.10 and 3.12 (the 6 technical-owner cases among them), persistence 322, dashboard 115/115, Firestore rules 96/96. Green before that at `3d696ba` (run 36331798250, `pull_request`), a STATUS-only commit. Green before that at `1774a38` (run 36331566705, `pull_request`; the duplicate `push` run 36331564392 was cancelled): all six jobs, pytest 1349 passed / 57 skipped on 3.10 and 3.12 (the 3 settled-data-access cases among them), persistence 316, dashboard 114/114, Firestore rules 96/96 (the 2 settled-data-access cases among them). Green before that at `a56fa4a` (run 36330793910, `pull_request`; the duplicate `push` run 36330791232 was cancelled), a STATUS-only commit. Green before that at `19afe65` (run 36330620304, `pull_request`; the duplicate `push` run 36330617691 was cancelled): all six jobs, pytest 1346 passed / 57 skipped on 3.10 and 3.12 (the 6 calendar-date cases among them), persistence 313, dashboard 113/113, Firestore rules 94/94 (the 3 month/day cases among them). Green before that at `c2352a9` (run 36329799176, `pull_request`; the duplicate `push` run 36329795930 was cancelled), a STATUS-only commit. Green before that at `6834f50` (run 36329619927, `pull_request`; the duplicate `push` run 36329617390 was cancelled): all six jobs, pytest 1340 passed / 57 skipped on 3.10 and 3.12 (the 9 phi-scope-contradicted cases among them), persistence 308, dashboard 113/113, Firestore rules 91/91. Green before that at `1a52359` (run 36329034131, `pull_request`; the duplicate `push` run 36329031749 was cancelled): all six jobs, pytest 1331 passed / 57 skipped on 3.10 and 3.12 (the 8 active-access-unknown cases among them), persistence 300. Green before that at `378c74b` (run 36328257014, `pull_request`; the duplicate `push` run 36328253595 was cancelled): all six jobs, pytest 1323 passed / 57 skipped on 3.10 and 3.12 (the 8 active-unrated cases among them), persistence 293, dashboard 111/111, Firestore rules 91/91. Green before that at `698f1e9` (run 36327268920, `pull_request`; the duplicate `push` run 36327266508 was cancelled): all six jobs, pytest 1315 passed / 57 skipped on 3.10 and 3.12 (the 6 baa-date-unexecuted cases among them), persistence 286, dashboard 110/110, Firestore rules 91/91. Green before that at `12ab5b5` (run 36326403959, `pull_request`; the duplicate `push` run 36326400977 was cancelled): all six jobs, pytest 1309 passed / 57 skipped on 3.10 and 3.12 (the 6 assurance-unnamed cases among them), persistence 280, dashboard 109/109, Firestore rules 91/91. Green before that at `44f5053` (run 36325380286, `pull_request`; the duplicate `push` run 36325376799 was cancelled): all six jobs, pytest 1303 passed / 57 skipped on 3.10 and 3.12 (the 2 duplicate-holder cases among them), persistence 274, dashboard 108/108, Firestore rules 91/91. Green before that at `7eab023` (run 36324535088, `pull_request`; the duplicate `push` run 36324532761 was cancelled): all six jobs, pytest 1301 passed / 57 skipped on 3.10 and 3.12 (the 7 review-horizon cases among them), persistence 274, dashboard 108/108, Firestore rules 91/91. Green before that at `5208b3b` (run 36323578375, `pull_request`; the duplicate `push` run 36323575899 was cancelled): all six jobs, pytest 1294 passed / 57 skipped on 3.10 and 3.12 (the 5 flow-unrecorded cases among them), persistence 267, dashboard 107/107, Firestore rules 91/91. Green before that at `b157eee` (run 36322532911, `pull_request`; the duplicate `push` run 36322530150 was cancelled): all six jobs, pytest 1289 passed / 57 skipped on 3.10 and 3.12 (the 14 agreement-not-executed cases among them), persistence 262, dashboard 106/106, Firestore rules 91/91. Green before that at `4860361` (run 36321594631, `pull_request`; the duplicate `push` run 36321592266 was cancelled): all six jobs, pytest 1275 passed / 57 skipped on 3.10 and 3.12 (the 12 approver-role cases among them), persistence 253. Green before that at `e60046b` (run 36320657897, `pull_request`; the duplicate `push` run 36320656007 was cancelled): all six jobs, pytest 1263 passed / 57 skipped on 3.10 and 3.12 (the 7 assurance-undated cases among them), persistence 253. Green before that at `85b9f05` (run 36319645389, `pull_request`; the duplicate `push` run 36319642415 was cancelled): all six jobs, pytest 1256 passed / 57 skipped on 3.10 and 3.12 (the 5 pending-record access cases among them), persistence 246. Green before that at `818afee` (run 36318787978): pytest 1251 passed / 57 skipped, persistence 246. Green before that at `b90f698` (run 36317342452, `pull_request`; the duplicate `push` run 36317339101 was cancelled): all six jobs, pytest 1240 passed / 57 skipped on 3.10 and 3.12 (the 6 findings-index cases among them), persistence 236. Green before that at `c93c84e` (run 36304978752, `pull_request`; the duplicate `push` run 36304976714 was cancelled): all six jobs, pytest 1234 passed / 57 skipped on 3.10 and 3.12 (the 6 access-change cases among them), persistence 236. Green before that at `cfc6fbe` (run 36304211252, `pull_request`; the duplicate `push` run 36304209042 was cancelled): all six jobs, pytest 1228 passed / 57 skipped on 3.10 and 3.12 (the 9 offboarding-revocation cases among them), persistence 236. Green before that at `22af04a` (run 36303657549, `pull_request`; the duplicate `push` run 36303655153 was cancelled): all six jobs, pytest 1219 passed / 57 skipped on 3.10 and 3.12 (the 5 no-expiry and outlasts-assurance cases among them), persistence 236. Green before that at `441f740` (run 36302969029, `pull_request`; the duplicate `push` run 36302966658 was cancelled): all six jobs, pytest 1214 passed / 57 skipped on 3.10 and 3.12 (the 9 register-held issue cases among them), persistence 236. Green before that at `314cfc3` (run 36302226951, `pull_request`; the duplicate `push` run 36302224776 was cancelled): all six jobs, pytest 1205 passed / 57 skipped on 3.10 and 3.12 (the 6 retiring-ends-access cases among them), persistence 236. Green before that at `7b806b6` (run 36301537432, `pull_request`; the duplicate `push` run 36301534746 was cancelled): all six jobs, pytest 1199 passed / 57 skipped on 3.10 and 3.12 (the 7 workspace-refusal cases among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Green before that at `855337f` (run 36300691285, `pull_request`; the duplicate `push` run 36300688865 was cancelled): all six jobs, pytest 1192 passed / 57 skipped on 3.10 and 3.12 (the 10 access-log rotation cases among them, the late-writer case on its Linux branch), persistence 236, dashboard 102/102, Firestore rules 91/91. Red before that at `02be93e` (run 36300536001, one rotation test's expected wording; see the rotation entry). Green before that at `27306de` (run 36299568259, `pull_request`; the duplicate `push` run 36299565239 was cancelled): all six jobs, pytest 1182 passed / 57 skipped on 3.10 and 3.12 (the 7 review-continuity cases among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Green before that at `fdc6786` (run 36298761935, `pull_request`; the duplicate `push` run 36298759806 was cancelled): all six jobs, pytest 1175 passed / 57 skipped on 3.10 and 3.12 (the 21 access-review packet cases among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Red before that at `1879e07` (run 36298643936, mypy on the new test file; see the access-review entry). Green before that at `ce81a73` (run 36298046071): pytest 1154 passed / 57 skipped, persistence 236. Green before that at `4da9dae` (run 36297903426, `pull_request`; the duplicate `push` run 36297900660 was cancelled): all six jobs, pytest 1154 passed / 57 skipped on 3.10 and 3.12 (the 28 partner-access runs among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Green before that at `ccf46ca` (run 36296832072, `pull_request`; the duplicate `push` run 36296828496 was cancelled): all six jobs, pytest 1126 passed / 57 skipped on 3.10 and 3.12 (the register-export cases among them), persistence 236, dashboard 102/102, Firestore rules 91/91. Green before that at `4527dd7` (run 36295538844, `pull_request`; the duplicate `push` run 36295536975 was cancelled): all six jobs, pytest 1114 passed / 55 skipped on 3.10 and 3.12 (the 17 log- and ledger-anchor cases among them), persistence 224. Green before that at `e3a2578` (run 36294982171, `pull_request`; the duplicate `push` run 36294979185 was cancelled): all six jobs, pytest 1097 passed / 55 skipped on 3.10 and 3.12 (the 17 grant-ledger cases among them), persistence 224. Green before that at `1df0174` (run 36294215258, `pull_request`; the duplicate `push` run 36294212520 was cancelled): all six jobs, pytest 1080 passed / 55 skipped on 3.10 and 3.12 (the 25 issue/revoke cases among them), the MariaDB persistence suite 224 passed. Green before that at `815c205` (run 36293169254): pytest 1055 passed / 55 skipped (the 7 usage-review cases among them), persistence 224. Green before that at `2e0c73b` (run 36292544236): pytest 1048 passed / 55 skipped (the 25 service-token cases among them), persistence 224. Green before that at `47f9041` (run 36291511505): pytest 1023 passed / 55 skipped (the 19 access-log cases among them), the MariaDB persistence suite 224 passed with none skipped. Green before that at `12cfef7` (run 36290114408): 1004 passed, persistence 224 (the register seal and the history row rewritten in place among them), dashboard 101/101, Firestore rules 91/91. Green before that at `58321de` (run 36288773882), 986 passed, persistence 205. Green before that at `0de87dd` (run 36287629428), 974 passed, persistence 192. Green before that at `298b2e0` (run 36286525753), 943 passed, persistence 161. Green before that at `a11a6ed` (run 36285596781) and `b159632` (run 36284444931), all six jobs, dashboard 100/100 and Firestore rules 91/91 against the emulator (unchanged by the review-queue and export passes; 88 before the edit/history pass, 78 before change history); green on every commit of 2026-09-16, 2026-09-17 and 2026-09-23. The product workflow has run four times as a dry run — see "Dry runs".**
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
changed. In CI at `b90f698` (run 36317342452) all six jobs passed: pytest
1240 passed, 57 skipped on 3.10 and 3.12, persistence 236.

**The review queue catches three more gaps, 2026-09-27.** Three kinds of
record got no finding in the queue (server and page alike):

- **A BAA marked `Executed` with a date after today.** It was typed ahead of
  signature, or it is a typo. It passed every check, so a partner whose BAA
  was not yet in effect read as governed. It also held a token that
  `oversight access` called clean.
- **PHI with no `phi_scope`.** Minimum necessary (164.502(b)) and the BAA's
  permitted uses (164.504(e)(2)) are judged against that scope. Nothing asked
  for it.
- **A record with no business owner.** Nobody at the client answers for the
  relationship.

Now:

- `baa-not-yet-effective` is **high**. It fires only when the status is
  `Executed` and the date is later than `as_of`. A BAA executed on the
  day itself is in effect. It is one of the `ACCESS_CODES`, so a partner
  token acting for such a record is high in `oversight access` and in the
  review packet.
- `phi-scope-missing` and `owner-unassigned` are **notices**. A blank value
  counts as none. No scope is only a notice when the record handles PHI.

Both implementations change together: `ironclad/oversight.py::attention_findings`
and `dashboard/public/oversight-core.js::attentionFindings`. They are held to
the shared table `tests/fixtures/oversight-attention.json`, which is 29 cases,
up from 20. Its base record now carries an owner and a scope. The export
golden `tests/fixtures/oversight-export.json` gains the owner notice on its
ownerless record.

What this says about Sage today: every seeded record has a PHI scope. The
three seeded integrations (DrChrono to PRIMO, PRIMO to Fuji MWL, OEC Storage
SCP) have no business owner. The queue now says so, and the packet's findings
index lists it. These are notices on records already high for the missing
BAA, so no packet count changes.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Packets already filed verify as before. Docs:
`docs/http-api.md` (the review queue, `oversight access`), the `oversight
access` CLI help, and the runbook in `HANDOFF.md` §17 ("Check the
partner/integration register without a browser").

New and changed tests:

- 9 new shared-table cases, run by both suites:
  - a BAA dated tomorrow, and one dated today;
  - a future date on a BAA that is not executed;
  - no scope, a blank scope, and no scope without PHI;
  - no owner, and a blank owner;
  - all three together.
- Two page cases.
- `test_partner_access.py::TestPartnerAccess::test_a_baa_dated_after_today_is_high`.
- `test_oversight.py::TestTheReviewQueue::test_the_sage_seed_names_its_integrations_as_ownerless_and_scopes_all_phi`.
- Two expectations updated for the owner notice:
  - the packet index's messages for DrChrono to PRIMO;
  - the HTTP queue's governed record, which now records an owner and scope.

Six mutations each fail a test by name:

- the code dropped from `ACCESS_CODES`;
- `>` weakened to `>=`;
- the scope not stripped;
- the owner check dropped;
- the page's future-date check dropped;
- the page's scope check applied without PHI.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1308
tests, 1240 passed, 57 skipped, 11 failed. Untouched HEAD `e31e680` in a
worktree, run after it: 1297 tests, 1230 passed, 10 failed. Compared set for
set, the one extra is
`test_http.py::TestTransport::test_an_oversize_body_is_413_and_ends_the_connection`,
a socket test this change does not touch; it passed three runs out of three
alone. ruff format and lint pass. `mypy` reports only the known Windows
`fcntl` errors in `policy_store.py`, the same four as HEAD. Dashboard
`node --test`: 96 tests, 95 passed. The one failure is the case that starts
a real `ironclad serve`, which fails on HEAD too (94 tests, 93 passed). The
white-label, secret-literal and `git diff --check` gates pass. The six
mutations above were each applied and reverted this run, and each failed
the named test. In CI at `818afee` (run 36318787978) all six jobs passed:
pytest 1251 passed, 57 skipped on 3.10 and 3.12, persistence 246.

**A partner token for a record still at `Pending information` is high,
2026-09-27.** `Pending information` is the status a contributor's proposal
starts at (`UNRATED`). A contributor can propose a partner or integration.
An operator could then issue a token acting for it, and `oversight access`
called that token clean unless the record also tripped a BAA or date check.
The partner was holding working access to a relationship nobody with
approval authority had reviewed. Nothing ever flagged it.

Now `ironclad/oversight.py::partner_access` raises `record-pending`
(**high**) for a live linked token whose record is at `Pending
information`. `Onboarding`, `Active` and `Under review` are past intake
and are not flagged. The review packet's partner-access section and its
`--fail-on high` gate pick it up through the same function. The server
does not refuse such a token (`link_withdrawn` still refuses only missing
and retired records). Like the BAA findings, this one goes to review.
No Sage seed record is at `Pending information`, so no count on the seed
changes.

No route, stored field, rule, vocabulary, token-file field, ledger line,
access-log line or page changed. Docs: `docs/http-api.md` (`oversight
access`), the `oversight access` CLI help, and `HANDOFF.md` §17 ("Grant,
renew and review a service token").

New tests (`tests/test_partner_access.py::TestPartnerAccess`):

- `test_a_relationship_still_pending_information_is_high`;
- `test_a_contributors_proposal_holding_a_token_is_high`: a real
  contributor save, which comes out at `Pending information`, and is high
  for the pending status and the missing BAA;
- `test_a_status_past_intake_is_not_pending`, for `Onboarding`, `Active`
  and `Under review`.

Two mutations each fail a test by name: the check disabled (both high
cases), and the check widened to `Onboarding` (that parameter).

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1313
tests, 1246 passed, 57 skipped, 10 failed. Untouched HEAD `dbc5c5f` in a
worktree: 1308 tests, 11 failed. Every failure here also fails on HEAD
(Windows-only: `fcntl`, symlinks, CRLF, the 20-writer lock). HEAD's extra
failure is the known
`test_http.py::TestTransport::test_an_oversize_body_is_413_and_ends_the_connection`
socket flake. ruff format and lint pass. `mypy` reports only the four
known Windows `fcntl` errors in `policy_store.py`. The white-label,
secret-literal and `git diff --check` gates pass. No dashboard file
changed. In CI at `85b9f05` (run 36319645389) all six jobs passed:
pytest 1256 passed, 57 skipped on 3.10 and 3.12, persistence 246.

**A High or Critical rating with no assurance expiry is a notice,
2026-09-27.** The review queue calls out an assurance that has lapsed
(`assurance-expired`) or is about to (`assurance-expiring`), and
`oversight access` calls out a token that runs past it
(`outlasts-assurance`). All three read `cert_expiration_date`. A record
with no date recorded tripped none of them, and the fixture said so on
purpose ("no assurance expiry recorded is not itself a finding"). That is
right for a Low-risk vendor. It is wrong for the relationships rated High
or Critical, which are the ones whose lapse most needs to show. All six
Sage seed records are rated High and none has an expiry, so every
assurance check was silent across the whole tenant.

Now `attention_findings()` (server) and `attentionFindings()` (page) raise
`assurance-undated` (**notice**) when the risk is in `ELEVATED_RISK`
(`High`, `Critical`) and `cert_expiration_date` is not an ISO date: "Rated
High with no certificate / assurance expiry recorded." A dated assurance
satisfies it. A lapsed one is reported as the lapse, not as undated.
`Low`, `Medium` and `Unrated` owe no date, so the existing "not itself a
finding" case keeps its meaning for the Low-rated base record. It is a
notice, not an `ACCESS_CODE`: a token is not called out for it, and
`--fail-on high` is unchanged. The six Sage seed records each gain it.
The export's attention column and the packet's findings index carry it
through the same function.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review queue) and
`HANDOFF.md` §17.

Tests:

- `tests/fixtures/oversight-attention.json`, the shared table: 5 new cases
  (34, up from 29). Medium with no date is clean, High with no date, Critical
  with a non-ISO date, High with a dated assurance is clean, and High with
  a lapsed assurance is `assurance-expired` only. Both sides must return
  each case exactly.
- `tests/test_oversight.py`: `ELEVATED_RISK` is inside the risk vocabulary
  and is the page's list, parsed from `oversight-core.js`; every High-rated
  Sage seed record without a date carries the notice.
- `dashboard/test/oversight.test.js`: the rule and its edges on the page.
- Two expectations moved with the rule. The packet's findings index now
  lists the notice (`test_access_review.py`). The HTTP queue test's
  "governed" High record gained a dated assurance, so it stays the clean
  control (`test_http.py`).

Four mutations each fail a named test: the check disabled on the server
(the two table cases and the seed test), and on the page (2 page tests);
`ELEVATED_RISK` widened to `Medium` on the server (the Medium case and the
parity test); the page's list narrowed to `High` (the parity test and the
page test).

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1320
tests, 1253 passed, 57 skipped, 10 failed. Untouched HEAD `1f7289f` in a
worktree: 1313 tests, 10 failed. The failure sets are identical
(Windows-only: `fcntl`, symlinks, CRLF, the 20-writer lock). Dashboard
`oversight.test.js` and `render.test.js`: 92/92 (`api.test.js` starts the
Python server and needs real `fcntl`, so it runs in CI). ruff format and
lint pass. `mypy --platform linux` passes. The white-label and
`git diff --check` gates pass. In CI at `e60046b` (run 36320657897) all six jobs
passed: pytest 1263 passed, 57 skipped on 3.10 and 3.12, persistence 253.

**A partner's token may not hold an approver role, 2026-09-27.** A token
linked to a register record (`on_behalf_of`) could be issued with `owner`
or `compliance_manager`. Those are the register's approvers
(`oversight.APPROVE_ROLES`): they set a record's status, risk and BAA
status. A partner holding one could mark its own BAA `Executed` or rate
its own relationship `Low`, and every check `oversight access` makes would
then read the record the partner wrote. Nothing refused it or reported it.

Now:

- `issue_token()` refuses a linked entry with a role in
  `PARTNER_WITHHELD_ROLES` (`owner`, `compliance_manager`). Nothing is
  written to the token file or the grant ledger. Staff entries (no link)
  may still hold either. `auditor`, `viewer` and `contributor` stay
  allowed.
- `tokens review` calls a hand-written linked entry with one **high**. It
  needs no register.
- `oversight access` raises `approver-role` (**high**) for it. The review
  packet and its `--fail-on high` gate carry it through the same function.
- `PARTNER_WITHHELD_ROLES` is tested to equal `APPROVE_ROLES`, so the two
  lists cannot drift apart.

The server does not refuse such a token on request. It still refuses
missing and retired records only. Adding this to its refusals would be a
change to live authentication, which is left for review. No route, stored
field, rule, vocabulary, page or ledger line format changed. Docs:
`docs/http-api.md` (`tokens issue`, `oversight access`) and `HANDOFF.md`
§17.

Tests (`tests/test_partner_access.py`, 12 new):

- Issue is refused for `owner`, for `compliance_manager`, and for either
  alongside `contributor`. Staff may still hold `owner`. A linked token
  may hold `auditor`, `viewer` or `contributor`. The parity test.
- The token review calls a hand-edited entry high and leaves staff clean.
- `oversight access` returns `approver-role` for each role, and leaves an
  unlinked staff owner under `unlinked`.
- The CLI `tokens issue --role owner --on-behalf-of` exits 2 and writes
  neither file.

Four mutations each fail a named test: the issue refusal disabled (the 3
issue cases and the CLI case), the review finding disabled (the review
case), the `oversight access` finding disabled (its 2 cases), and
`contributor` added to the withheld list (the parity test and 7 others).

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1332
tests, 1265 passed, 57 skipped, 10 failed. Untouched HEAD `25bd7e1` in a
worktree: 1320 tests, 10 failed. The failure sets are identical
(Windows-only: `fcntl`, symlinks, CRLF, the 20-writer lock). ruff format and
lint pass. `mypy --platform linux` passes. The white-label and
`git diff --check` gates pass. No dashboard file changed. In CI at `4860361`
(run 36321594631) all six jobs passed: pytest 1275 passed, 57 skipped on
3.10 and 3.12, persistence 253.

**An Active relationship with no executed agreement is high, 2026-09-27.**
`agreement_status` was validated against its vocabulary and shown as a chip,
and checked by nothing else. A relationship could be `Active` with its
agreement `Pending review`, `Under review` or `Required - pending`, live and
with no contract behind it, and the review queue, the export's attention
column, the packet's findings index and `oversight access` all said nothing.
The Sage seed has exactly this: DrChrono is `Active` with its agreement
`Under review`. Its missing BAA was already high, but executing the BAA alone
would have made it look clean.

Now `attention_findings()` (server) and `attentionFindings()` (page) raise
`agreement-not-executed` (**high**) when `status` is `Active` and
`agreement_status` is not in `AGREEMENT_SETTLED` (`Executed`, `Not
required`): "Active without an executed agreement (Agreement: Under
review)." `Not required` is an approver's ruling and settles it.
`Onboarding` and `Under review` records are not held to it: signing is what
onboarding is for, and a relationship under review is already being looked
at. It is an `ACCESS_CODE`, so a partner token for such a record is high in
`oversight access`, and the review packet and `--fail-on high` carry it
through the same function. Neither the server's request-time refusal
(missing or retired only) nor `tokens issue` changed.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review queue,
`oversight access`) and `HANDOFF.md` §17.

Tests (14 new):

- `tests/fixtures/oversight-attention.json`, the shared table: 7 new cases
  (41, up from 34). The base record gained `agreement_status: Executed`, so
  it stays the clean control. Under review, required and pending, and not
  recorded are high. Not required is clean. Onboarding and under review are
  not this finding. With the BAA also missing, the BAA is listed first.
- `tests/test_oversight.py`: `AGREEMENT_SETTLED` is inside the agreement
  vocabulary and is the page's list, parsed from `oversight-core.js`. Of
  the Sage seed, DrChrono alone carries the finding.
- `tests/test_partner_access.py`: a token for the seeded DrChrono reads
  `phi-without-baa`, then `agreement-not-executed`. An Active partner with
  each unsigned state is high. `Not required` is clean.
- `dashboard/test/oversight.test.js`: the rule and its edges on the page.
  Its `clean` record gained `agreement_status: Executed`.

Two mutations each fail named tests. With the check disabled on the server,
9 fail: the four positive table cases, the seed test, and the four
`oversight access` cases. With it disabled on the page, 2 page tests fail:
the new rule test and the shared table.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1346
tests, 1279 passed, 57 skipped, 10 failed. Untouched HEAD `2d8899e` in a
worktree: 1332 tests, 10 failed. The failure sets are identical
(Windows-only: `fcntl`, symlinks, CRLF, the 20-writer lock). Dashboard
`oversight.test.js` and `render.test.js`: 93/93. ruff format and lint
pass. `mypy --platform linux` passes. The white-label, secret-literal and
`git diff --check` gates pass. In CI at `b157eee` (run 36322532911) all six
jobs passed: pytest 1289 passed, 57 skipped on 3.10 and 3.12, persistence
262, dashboard 106/106, Firestore rules 91/91.

**PHI with no data flow direction recorded is a notice, 2026-09-27.**
`data_flow_direction` was validated against its vocabulary and allowed empty,
and nothing asked for it. A record could handle PHI and not say whether the
PHI leaves the practice, arrives, or both. That is the question transmission
security (45 CFR 164.312(e)) and the risk analysis are assessed on. The
review queue said nothing. The Sage seed has three of these: DrChrono, PRIMO
and Fujifilm are all PHI partners with no direction. The three integrations
each record theirs.

Now `attention_findings()` (server) and `attentionFindings()` (page) raise
`phi-flow-unrecorded` (**notice**) when `data_access` is `PHI` and
`data_flow_direction` is blank or absent: "Handles PHI with no data flow
direction recorded." It sits after `phi-scope-missing`. It is not an
`ACCESS_CODE`, so `oversight access` and `--fail-on high` are unchanged. The
export's attention column and the packet's findings index carry it through
the same function.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review queue) and
`HANDOFF.md` §17.

Tests (5 new pytest, 1 new page test):

- `tests/fixtures/oversight-attention.json`, the shared table: 4 new cases
  (45, up from 41). The base record gained `data_flow_direction:
  Bidirectional`, so it stays the clean control. Blank and cleared are the
  notice. Non-PHI owes no direction. With scope and direction both missing,
  the scope is listed first.
- `tests/test_oversight.py`: of the Sage seed, exactly the three partners
  carry the finding.
- `tests/test_http.py`: the review-queue test's governed record gained a
  direction. Without it, it now carries the notice, and the first full run
  failed on it. That is the only test outside the shared table that changed.
- `dashboard/test/oversight.test.js`: the rule and its edges, each of the four
  directions clean. Its `clean` record gained a direction.

Two mutations each fail named tests. With the check replaced by `pass` on
the server, 4 fail: the three positive table cases and the seed test. With
the line removed on the page, 2 page tests fail: the new rule test and the
shared table.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub):
1351
tests, 1284 passed, 57 skipped, 10 failed. Untouched HEAD `d930754` in a
worktree: 1346 tests, 10 failed. The failure sets are identical
(Windows-only: `fcntl`, symlinks, CRLF, the 20-writer lock). Dashboard `oversight.test.js` and `render.test.js`: 94/94.
ruff format and lint pass. `mypy --platform linux` passes. The white-label
gate passes. bandit is not installed in the local venv. CI installs its own.
In CI at `5208b3b` (run 36323578375) all six jobs passed: pytest 1294
passed, 57 skipped on 3.10 and 3.12, persistence 267, dashboard 107/107,
Firestore rules 91/91.

**A review scheduled more than a year out is a notice, 2026-09-27.**
`review_due` was checked for overdue, due soon and missing, and never for
how far ahead it was. A contributor could set it to 2099-12-31 and the record
would never again read as `review-overdue`: the queue, the export, the
packet's findings index and `oversight access` would all stay quiet for as
long as the date said. It was the one date on the record that cleared a
finding by being moved further away.

Now `attention_findings()` (server) and `attentionFindings()` (page) raise
`review-too-distant` (**notice**) when `review_due` is later than `as_of`
plus `REVIEW_HORIZON_DAYS` (365): "Review scheduled 2099-12-31, more than
365 days out." The last day of the horizon is clean. The horizon is ICIT
policy (the register is reviewed at least yearly, as a policy is), not a
standard, and the constant says so on both sides. It is a notice, not an
`ACCESS_CODE`: the date is not yet wrong, only unfalsifiable, so
`oversight access` and `--fail-on high` are unchanged. Retired records are
left out, as for every finding. No Sage seed record carries it (its reviews
are due 2026-10-31 and 2026-12-31).

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review queue) and
`HANDOFF.md` §17.

Tests (7 new pytest, 1 new page test):

- `tests/fixtures/oversight-attention.json`, the shared table: 5 new cases
  (50, up from 45), and a `review_horizon_days` key beside `window_days`.
  The last day of the horizon is clean; one day past it and 2099 are the
  notice; a distant review is listed before an assurance notice; a retired
  record with a distant review needs nothing.
- `tests/test_oversight.py`: the horizon is the page's, parsed from
  `oversight-core.js`, and the table's; no Sage seed record is past it.
- `dashboard/test/oversight.test.js`: the horizon and its edges on the page,
  and the table's horizon is the page's.

Two mutations each fail named tests. With the check disabled on the server,
3 fail: the three positive table cases. With it disabled on the page, 2 page
tests fail: the new horizon test and the shared table.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1358
tests, 1291 passed, 57 skipped, 10 failed. Untouched HEAD `d3111b6` in a
worktree: 1351 tests, 10 failed. The failure sets are identical
(Windows-only: `fcntl`, symlinks, CRLF, the 20-writer lock). Dashboard
`oversight.test.js` and `render.test.js`: 95/95. ruff format and lint pass.
`mypy --platform linux` passes. The white-label gate and `git diff --check`
pass. bandit is not installed in the local venv; CI installs its own. In CI
at `7eab023` (run 36324535088) all six jobs passed: pytest 1301 passed, 57
skipped on 3.10 and 3.12, persistence 274, dashboard 108/108, Firestore rules
91/91.

**Two token entries for one user in one tenant are each high, 2026-09-27.**
`tokens issue` refuses a second entry for a user who already holds one in the
tenant, because the access log names a caller by user and tenant, never by
token: two entries for one pair could not be told apart in an access review.
`tokens review` did not hold the file to the same rule. A second entry for a
Sage partner's user, written by hand, reviewed clean, and with
`--access-log` both entries were credited with the same requests, so the
review could not say which credential was in use or which to revoke.

Now `review_tokens()` counts entries per (user, tenant) and gives each
member of a pair a **high** finding: "first@sage.example holds 2 entries for
sage-spine; the access log names callers by user and tenant, so their
requests cannot be told apart: revoke all but one". The entries stay
`active`: the tokens still authenticate, so the finding is about
attribution, not a broken entry, and `--fail-on high` trips on it. One user
in two tenants is two grants and is not a finding. Entries with no
`user_id` are already high for that and are not counted as one holder.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review) and
`HANDOFF.md` (the `tokens review` section).

Tests (2 new pytest, `tests/test_tokens.py::TestReview`): a hand-written
pair is high on both entries and stays active, while one user in two tenants
is clean; blank users are not paired. One mutation (the check disabled)
fails the pair test.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1360
tests, 1293 passed, 57 skipped, 10 failed. Untouched HEAD `53dc875` in a
worktree: 1358 tests, 10 failed. The failure sets are identical
(Windows-only: `fcntl`, symlinks, CRLF, the 20-writer lock). ruff format and
lint pass. `mypy --platform linux` passes. The white-label gate and
`git diff --check` pass. bandit is not installed in the local venv; CI
installs its own. In CI at `44f5053` (run 36325380286) all six jobs passed:
pytest 1303 passed, 57 skipped on 3.10 and 3.12, persistence 274, dashboard
108/108, Firestore rules 91/91.

**An assurance expiry with no assurance named is a notice, 2026-09-27.**
`cert_expiration_date` drove `assurance-expired`, `assurance-expiring`, a
token's `outlasts-assurance` and (by its absence) `assurance-undated`. None
of them asked what the date belonged to. A record could carry an expiry with
`assurance` blank, and it reviewed clean. A reviewer then had no report,
letter or certificate to check the date against, and anyone could type an
expiry to clear `assurance-undated` on a High or Critical record. The
export's own golden fixture had one: its EHR feed integration dated an
assurance to 2026-10-28 and named none, and it exported without a word.

Now `attention_findings()` (server) and `attentionFindings()` (page) raise
`assurance-unnamed` (**notice**) when `cert_expiration_date` is an ISO date
and `assurance` is blank, whitespace or absent: "Certificate / assurance
expiry 2027-06-30 recorded with no assurance named." It follows the expiry
checks, so a lapsed unnamed assurance lists the lapse (high) first. An
unreadable expiry is not a recorded one and owes no name. It is not an
`ACCESS_CODE`, so `oversight access` and `--fail-on high` are unchanged. The
export's attention column and the packet's findings index carry it through
the same function. No Sage seed record carries it: each names its pending
assurance and dates none.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review queue) and
`HANDOFF.md` §17.

Tests (6 new pytest, 1 new page test):

- `tests/fixtures/oversight-attention.json`, the shared table: 5 new cases
  (55, up from 50). The base record gained `assurance`, so it stays the
  clean control. Blank, cleared and whitespace are the notice. No expiry and
  no name is clean. A lapsed unnamed assurance is the lapse, then the name.
- `tests/fixtures/oversight-export.json`: the EHR feed row's attention
  column gains the notice. The page and the server are both held to it.
- `tests/test_oversight.py`: no Sage seed record carries it. Dating a seed
  partner's named assurance stays clean; blanking the name raises it.
- `tests/test_http.py`: the review-queue test's governed record gained an
  `assurance`. It is the only test outside the shared tables that changed.
- `dashboard/test/oversight.test.js`: the rule and its edges on the page.
  Its `clean` record gained an `assurance`.

Two mutations each fail named tests. With the check disabled on the server,
6 fail: the four positive table cases, the seed test and the export table.
With it disabled on the page, 3 page tests fail: the new rule test, the
review-queue table and the export table.

Local evidence (Windows 11, Python 3.12 venv, no-op `fcntl` stub): 1366
tests, 1299 passed, 57 skipped, 10 failed. Untouched HEAD `9430a77` in a
worktree: 1360 tests, 10 failed. The failure sets are identical
(Windows-only: `fcntl`, symlinks, CRLF, the 20-writer lock). Dashboard
`oversight.test.js` and `render.test.js`: 96/96. ruff format and lint pass.
`mypy --platform linux` passes. The white-label gate and `git diff --check`
pass. bandit is not installed in the local venv; CI installs its own. In CI
at `12ab5b5` (run 36326403959) all six jobs passed: pytest 1309 passed, 57
skipped on 3.10 and 3.12, persistence 280, dashboard 109/109, Firestore rules
91/91.

**A BAA execution date on a BAA not marked executed is a notice, 2026-09-27.**
`baa_execution_date` was only read when `baa_status` was `Executed` (for
`baa-evidence-missing` and `baa-not-yet-effective`). On any other status it
was ignored. A record could say its BAA was `Under review`, `Not required`
or blank and still carry an execution date, and it reviewed with no word
about the date. A reviewer or auditor reading the register or its export
takes a date as a signature. The status says there is none. One of the two
is wrong, and nothing pointed at either. For an operational-only record with
`Not required`, the record reviewed clean.

Now `attention_findings()` (server) and `attentionFindings()` (page) raise
`baa-date-unexecuted` (**notice**) when `baa_execution_date` is an ISO date
and `baa_status` is anything but `Executed`: "BAA execution date 2025-01-15
recorded but BAA status is Under review." On a PHI record it follows
`phi-without-baa` (high). A document reference alone is not held to it: a
draft under review has one. An unreadable date is not a recorded one. It is
not an `ACCESS_CODE`, so `oversight access` and `--fail-on high` are
unchanged. The export's attention column and the packet's findings index
carry it through the same function. No Sage seed record carries it: no seed
BAA is executed, and none is dated.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review queue) and
`HANDOFF.md` §17.

Tests (6 new pytest, 1 new page test):

- `tests/fixtures/oversight-attention.json`, the shared table: 5 new cases
  (60, up from 55). Under review, not required and no status recorded each
  raise it. A document reference alone and an unreadable date do not. The
  existing "future date on a BAA not marked executed" case now expects the
  notice after `phi-without-baa` (it had asserted the date was ignored).
  Seven cases that flip the base record's executed BAA to another status
  now also clear its execution date, so each stays about what its name
  says.
- `tests/test_oversight.py`: no Sage seed record carries it. Dating a seed
  partner's unexecuted BAA raises it; marking that BAA executed clears it.
- `dashboard/test/oversight.test.js`: the rule and its edges on the page,
  for every non-executed status. Three existing page tests that model an
  unexecuted BAA from `clean` now clear its date.

Two mutations each fail named tests. With the check disabled on the server,
5 fail: the four positive table cases and the seed test. With it disabled on
the page, 2 page tests fail: the new rule test and the review-queue table.

Local gates on Windows, 2026-09-27: pytest 1372 collected, 57 skipped, 10
failed. The 10 are the known Windows-only set (fcntl, symlinks, CRLF, the
20-writer lock test), and all 10 fail the same way on untouched `c23f329`.
None is in `tests/test_oversight.py`. Page tests (`oversight.test.js`,
`render.test.js`) 97/97. `mypy --platform linux` clean, `ruff check` and
`ruff format --check` clean, `scripts/check_white_label.sh` passes. Both
mutations were re-run this session and fail exactly the tests named above.
CI green at `698f1e9` (run 36327268920, `pull_request`; the duplicate `push`
run 36327266508 was cancelled): all six jobs, pytest 1315 passed, 57 skipped
on 3.10 and 3.12, persistence 286, dashboard 110/110, Firestore rules 91/91.

**An Active relationship never risk-rated is high, 2026-09-27.** An
unrated risk was a `risk-unrated` notice whatever the status. `Active` is an
approver's decision, so an `Active` record at `Unrated` is a live
relationship nobody assessed. The rating is also what decides whether the
record owes a dated assurance (`assurance-undated` fires only on High or
Critical), so an unrated live relationship escaped that check too, and a
partner token acting for it reviewed clean in `oversight access`.

Now `attention_findings()` (server) and `attentionFindings()` (page) raise
`active-unrated` (**high**) when `status` is `Active` and `risk` is
`Unrated` or blank: "Active with risk not yet rated." It takes the place of
the `risk-unrated` notice on that record, and follows
`agreement-not-executed` when both apply. Records not yet `Active`
(Pending information, Onboarding, Under review, Offboarding) keep the
notice; retired records need no attention. It is an `ACCESS_CODE`, like
every other high review-queue finding, so a partner token for such a record
is high in `oversight access` and fails `--fail-on high`. The export's
attention column and the packet's findings index carry it through the same
function. No Sage seed record carries it: DrChrono, the seed's one `Active`
record, is rated High.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review queue and
`oversight access`) and `HANDOFF.md` §17.

Tests (8 new pytest, 1 new page test):

- `tests/fixtures/oversight-attention.json`, the shared table: 6 new cases
  (66, up from 60). Unrated and cleared risk on an `Active` record raise
  it. Onboarding and Pending information keep the notice. Retired is
  clean. Agreement and rating both missing list the agreement first. Two
  existing cases that model an unrated record from the `Active` base now set
  `Under review`, so each still tests the notice its name says.
- `tests/test_oversight.py`: no Sage seed record carries it. An unrated
  DrChrono raises it and not the notice. The code is in `ACCESS_CODES`.
- `tests/test_partner_access.py`: a token for an `Active`, unrated partner
  is high with `active-unrated` alone. The "notices that are not about
  access" case now uses an Onboarding record, since an `Active` unrated one
  is now an access finding.
- `dashboard/test/oversight.test.js`: the rule on the page for `Unrated`,
  blank and missing risk, and the notice for each status that is not yet
  `Active`. The sort-order test's record is now `Under review`.

Two mutations each fail named tests. With the check disabled on the server,
5 fail: three positive table cases, the seed test and the access test. With
it disabled on the page, 2 page tests fail: the new rule test and the
review-queue table.

Local gates on Windows, 2026-09-27: pytest 1380 collected, 57 skipped, 10
failed. Untouched `a274cb3` in a worktree: 1372 collected, 57 skipped, 10
failed. The failure sets are identical (Windows-only: `fcntl`, symlinks,
CRLF, the 20-writer lock test). None is in `tests/test_oversight.py` or
`tests/test_partner_access.py`. Page tests (`oversight.test.js`,
`render.test.js`) 98/98. `mypy --platform linux` clean, `ruff check` and
`ruff format --check` clean, `scripts/check_white_label.sh` passes. CI
green at `378c74b` (run 36328257014, `pull_request`; the duplicate `push`
run 36328253595 was cancelled): all six jobs, pytest 1323 passed, 57 skipped
on 3.10 and 3.12, persistence 293, dashboard 111/111, Firestore rules 91/91.

**An Active relationship of unknown data access is high, 2026-09-27.** Data
access `Unknown` (or blank) was a `data-access-unknown` notice whatever the
status. Whether a relationship owes a BAA turns on whether it handles PHI:
`phi-without-baa` fires only on `data_access` `PHI`. So an `Active` record
at `Unknown` with no BAA read as a notice, and a partner token acting for it
reviewed clean in `oversight access`. Setting a live PHI partner's data
access to `Unknown` made its missing BAA disappear from both.

Now `attention_findings()` (server) and `attentionFindings()` (page) raise
`active-access-unknown` (**high**) when `status` is `Active` and
`data_access` is `Unknown` or blank: "Active with data access not
established." It takes the place of the `data-access-unknown` notice on that
record, and follows `active-unrated` when both apply. Records not yet
`Active` keep the notice; retired records need no attention. It is an
`ACCESS_CODE`, so a partner token for such a record is high in `oversight
access` and fails `--fail-on high`. The export's attention column and the
packet's findings index carry it through the same function. No Sage seed
record carries it: DrChrono, the seed's one `Active` record, handles PHI.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review queue and
`oversight access`) and `HANDOFF.md` §17.

Tests (8 new pytest, 1 new page test):

- `tests/fixtures/oversight-attention.json`, the shared table: 6 new cases
  (72, up from 66). `Unknown` and cleared data access on an `Active` record
  raise it. So does `Unknown` with the BAA pending review: `phi-without-baa`
  cannot fire, and this finding does. Onboarding keeps the notice. Retired
  is clean. Unrated and unknown together list the rating first.
- `tests/test_oversight.py`: no Sage seed record carries it. DrChrono set to
  `Unknown` raises it, not the notice and not `phi-without-baa`. The code is
  in `ACCESS_CODES`.
- `tests/test_partner_access.py`: a token for an `Active` partner of unknown
  data access with no executed BAA is high with `active-access-unknown` alone.
- `dashboard/test/oversight.test.js`: the rule on the page for `Unknown`,
  blank and missing data access, the unexecuted-BAA case, and the notice for
  each status that is not yet `Active`.

Two mutations each fail named tests. With the check disabled on the server,
6 fail: four positive table cases, the seed test and the access test. With
it disabled on the page, 2 page tests fail: the new rule test and the
review-queue table.

Local gates on Windows, 2026-09-27: pytest 1388 collected, 57 skipped, 10
failed. Untouched `23c647a` in a worktree: 1380 collected, 57 skipped, 10
failed. The failure sets are identical (Windows-only: `fcntl`, symlinks,
CRLF, the 20-writer lock test). None is in `tests/test_oversight.py` or
`tests/test_partner_access.py`. Page tests (`oversight.test.js`,
`render.test.js`) 99/99. `mypy --platform linux` clean, `ruff check` and
`ruff format --check` clean, `scripts/check_white_label.sh` passes. CI for
the parent `23c647a` was green (run 36328434656, `pull_request`; the
duplicate `push` run 36328430900 was cancelled).

**A PHI scope on a record not marked PHI is a notice, 2026-09-27.** CI for
`1a52359` came back green first (run 36329034131, `pull_request`; the
duplicate `push` run 36329031749 was cancelled): all six jobs, pytest 1331
passed, 57 skipped on 3.10 and 3.12, persistence 300.

`phi-without-baa` reads `data_access` alone. Setting a PHI partner's data
access to `PII`, `Operational only` or `No production data` made its
missing BAA disappear from the review queue and from `oversight access`,
while `phi_scope` still said "Demographics, clinical data, DICOM
metadata/images". The last iteration closed the `Unknown` route to the same
result; this is the route through a definite value. `data_access` is not a
governance field (`GOVERNANCE_FIELDS`), so a contributor can make the
change without an approver.

Now `attention_findings()` (server) and `attentionFindings()` (page) raise
`phi-scope-contradicted` (**notice**) when `phi_scope` is non-blank and
`data_access` is set to anything but `PHI` or `Unknown`: "PHI scope recorded
but data access is PII." Unknown or blank access is left to
`active-access-unknown` / `data-access-unknown`, which already ask for it.
Retired records need no attention. It is **not** an access code: the record
contradicts itself, and whether the access or the scope is wrong is a
register question, so a partner token for such a record still reviews
clean in `oversight access` and `--fail-on high` is unchanged. The export's
attention column and the packet's findings index carry it through the same
function. No Sage seed record carries it: all six handle PHI.

No route, stored field, rule, vocabulary, token-file field, ledger line or
access-log line changed. Docs: `docs/http-api.md` (the review queue) and
`HANDOFF.md` §17.

Tests (9 new pytest, 1 new page test):

- `tests/fixtures/oversight-attention.json`, the shared table: 7 new cases
  (79, up from 72). `PII`, `Operational only` and `No production data` with
  a scope raise it; so does a record still onboarding. A blank scope does
  not. Cleared access while onboarding is the unknown-access notice, not
  this. Retired is clean. Six existing cases that set a non-PHI access now
  clear the scope too, so each still tests only what it names.
- `tests/test_oversight.py`: no Sage seed record carries it. DrChrono moved
  to `PII` loses `phi-without-baa` and raises this notice. The code is not
  in `ACCESS_CODES`.
- `tests/test_partner_access.py`: a token for an `Active` partner at `PII`
  with a PHI scope and no BAA reviews `ok`, pinning the choice above.
- `dashboard/test/oversight.test.js`: the rule on the page for each non-PHI
  access, the message, a blank scope, `Unknown`, a PHI record, retired.
  Three existing page tests that set a non-PHI access now clear the scope.

Two mutations each fail named tests. With the check disabled on the server,
5 fail: four positive table cases and the seed test. With it disabled on
the page, 2 page tests fail: the new rule test and the review-queue table.

Local gates on Windows, 2026-09-27: pytest 1397 collected, 57 skipped, 10
failed. The same 10 fail on untouched `1a52359` in a worktree
(Windows-only: `fcntl`, symlinks, CRLF, the 20-writer lock test). None is
in `tests/test_oversight.py` or `tests/test_partner_access.py`. Page tests
(`oversight.test.js`, `render.test.js`) 100/100. `mypy --platform linux`
clean, `ruff check` and `ruff format --check` clean,
`scripts/check_white_label.sh` passes.

Candidate next, not started: making `data_access` an approver-only field.
The BAA check turns on it, and a contributor can change it; this notice
and `active-access-unknown` show the change, but neither stops it. That
changes the rules, `next_revision`, the page's form and the contributor's
proposal default, so it wants a decision on what a proposal starts at.

CI for this change: green at `6834f50` (run 36329619927, `pull_request`;
the duplicate `push` run 36329617390 was cancelled): all six jobs, pytest
1340 passed, 57 skipped on 3.10 and 3.12, persistence 308, dashboard
113/113, Firestore rules 91/91.

**A register date must be a day that exists, 2026-09-27.** CI for
`c2352a9` (the STATUS commit above) came back green first (run
36329799176, `pull_request`; the duplicate `push` run 36329795930 was
cancelled).

The server (`content_problems()`) and the Firestore rules
(`optionalDate()`) checked `baa_execution_date`, `review_due` and
`cert_expiration_date` against the pattern `NNNN-NN-NN` only. `2026-02-30`,
`2026-13-01` and `2026-09-00` were stored. The review queue compares ISO
dates as strings, so an impossible date still sorts between real days. It
reads as a review date or a BAA signature that cannot have happened, and
it lands in the export and the access-review packet. The page's date
inputs cannot produce one; a direct API or Firestore write could.

Now:

- **Server.** A register date must be a real calendar day. The error is
  "review_due '2026-02-30' is not a YYYY-MM-DD calendar date or empty",
  and over HTTP it is a 400 naming the field; nothing is written.
  `check_as_of()` uses the same helper, so its behaviour is unchanged. A
  record already stored with such a date (only possible through Firestore
  today) is refused on its next edit until that edit names a real day.
  `check_stored()` refuses it too, so the stores cannot write one.
- **Rules.** `optionalDate()` now requires month `01`–`12` and day
  `01`–`31`. The rules language has no calendar arithmetic, so
  `2026-02-30` still passes there. The comment in `firestore.rules` says
  the server is the exact check.

No route, stored field, vocabulary or finding changed. Every date in the
Sage seed, the page tests and the rules suite still matches the new rules
pattern, except the three cases written to be refused (checked with
Node). Docs: `docs/http-api.md` (the closed schema).

Tests (6 new pytest, 3 new emulator cases):

- `tests/test_oversight.py`: `2026-02-30`, `2026-13-01` and `2026-09-00`
  are refused and named, one per date field. A leap day in 2028 is
  accepted, and one in 2027 is refused. A stored `2026-02-30` blocks an
  unrelated edit, an edit that fixes the date succeeds, and
  `check_stored()` refuses the stored record.
- `tests/test_http.py`: a create with `baa_execution_date: 2026-02-30` is
  400 naming the field, and the register stays empty.
- `tests/rules/rules.test.js`: month 13, day 00 and day 32 are refused.
  The existing valid record (`2026-12-31`, `2026-09-01`) covers the upper
  and lower bounds on the accepted side.

Mutation: with the server check put back to the pattern alone, 5 of the
new tests fail by name (the three refusals, the leap-day test and the
stored-record test).

Local gates on Windows, 2026-09-27: pytest 1403 collected, 57 skipped, 10
failed. The same 10 fail on untouched `c2352a9` in a worktree (1397
collected; Windows-only). None is in a changed file. Page tests
(`oversight.test.js`, `render.test.js`) 100/100. `mypy --platform linux`
clean, `ruff check` and `ruff format --check` clean. The rules change is
proven only by the emulator job in CI (no JDK on this machine).

CI for this change: green at `19afe65` (run 36330620304, `pull_request`;
the duplicate `push` run 36330617691 was cancelled): all six jobs, pytest
1346 passed, 57 skipped on 3.10 and 3.12, persistence 313, dashboard
113/113, Firestore rules 94/94. `a56fa4a` (the STATUS commit) green too
(run 36330793910, `pull_request`; the duplicate `push` run 36330791232
was cancelled).

**Data access is settled by an approver once stored, 2026-09-27.** The
candidate recorded under the PHI-scope entry. A contributor could move
`data_access`, and the BAA check turns on it. A partner's token may hold
`contributor`. Moving its own record from `PHI` to `PII` cleared
`phi-without-baa`, and with it the high finding on its own access in
`oversight access`. Clearing the scope too left no notice.

The open question was what a contributor's proposal starts at. This
change leaves it open: a contributor still proposes `data_access` on a new
record, as before, and the approver sees it when rating the record. What
changed is the edit. Once a record is stored, only an owner or compliance
manager moves `data_access`.

- **Server.** `SETTLED_FIELDS = ("data_access",)` in
  `ironclad/oversight.py`. `next_revision` refuses a contributor's edit
  that moves it, adds it to a record stored without it, or moves it off
  `Unknown`: "contrib-1 may not change data_access; an approver sets
  them". Over HTTP that is 403 and nothing is written. Restating the
  stored value is allowed, as it is for the ratings.
- **Rules.** `contributorKeepsGovernanceState()` lists `data_access` with
  the four governance fields. Create is unchanged.
- **Page.** `SETTLED_FIELDS` in `oversight-core.js`. `buildRecord` ignores
  a contributor's `data_access` on an edit, and the edit form disables the
  select for a contributor (`holdSettled`), freeing it again for a new
  record. The governance note says so.

No route, stored field, vocabulary or finding changed. No Sage seed record
changes. `phi-scope-contradicted` stays: it still catches an approver's
move and records written before this. Docs: `docs/http-api.md`,
`HANDOFF.md` (the phi-scope-contradicted paragraph).

Tests: 3 new pytest cases, 1 extended HTTP case, 1 new page test, 2 new
emulator cases.

- `tests/test_oversight.py`: a contributor proposes `PHI`, cannot move it
  to `PII`, a manager can, and a contributor may restate it. A contributor
  cannot establish access an owner left `Unknown`, or add it to a record
  stored without it. The rules-parity test now holds the rules' list to
  `GOVERNANCE_FIELDS` plus `SETTLED_FIELDS`.
- `tests/test_http.py`: the contributor flow ends with a `data_access`
  edit refused 403 naming the field. The stored record is unchanged at
  revision 3.
- `dashboard/test/oversight.test.js`: the rules' list equals the page's
  two lists. A contributor's proposal keeps `PHI`, a tampered edit form
  cannot move it, and an approver's can. The form holds the select on edit
  and frees it on a new record.
- `tests/rules/rules.test.js`: a contributor's `PHI` proposal lands; moving
  it to `PII` is refused; restating it with a note lands; a compliance
  manager moves it. A contributor adding access to an owner's record that
  has none is refused.

Two mutations each fail named tests. With `SETTLED_FIELDS` dropped from
the server check, 4 fail (the three new policy tests and the HTTP flow).
With the page guard removed, the new page test fails.

Local gates on Windows, 2026-09-27: pytest 1406 collected, 57 skipped, 10
failed. The same 10 fail on untouched `a56fa4a` in a worktree (1403
collected; Windows-only). None is in a changed file. Page
tests (`oversight.test.js`, `render.test.js`) 101/101. `mypy --platform
linux` clean, `ruff check` and `ruff format --check` clean,
`scripts/check_white_label.sh` passes, `node --check` on the rules suite.
The rules change is proven only by the emulator job in CI (no JDK here).

CI for this change: green at `1774a38` (run 36331566705, `pull_request`;
the duplicate `push` run 36331564392 was cancelled): all six jobs, pytest
1349 passed, 57 skipped on 3.10 and 3.12, persistence 316, dashboard
114/114, Firestore rules 96/96.

Candidate next, not started: whether a contributor's proposal should start
at `Unknown` data access instead of what the contributor enters. That is
the decision this change left open. It trades a contributor's knowledge
of the feed for a `data-access-unknown` notice on every proposal.

**PHI with no technical owner recorded is a notice, 2026-09-27.** The
register carried `technical_owner` and nothing asked for it. A record
could handle PHI with nobody named who can cut the feed or revoke its
credential in an incident. Response and access termination are
assessed on that. None of the six Sage seed records names one.

`attention_findings()` and `attentionFindings()` now raise
`technical-owner-unassigned` (notice) for PHI with a blank or absent
technical owner, after `phi-flow-unrecorded`. It is not an access code.
No route, stored field, rule, vocabulary, token-file field or ledger
line changed. Docs: `docs/http-api.md`, `HANDOFF.md`.

Tests: the shared table grows 79 -> 84 cases (absent, cleared, blank,
no PHI, and order behind `phi-flow-unrecorded`). One new page test and one
seed test name all six records. The HTTP governed record and the
`clean` base gained a technical owner. The access-review findings index
now lists the notice on the seed's DrChrono to PRIMO integration.

Two mutations each fail named tests. With the server check disabled,
6 fail: the four new table cases, the seed test and the access-review
index. With the page check disabled, 2 fail: the new page test and
the shared table.

Local gates on Windows, 2026-09-27: pytest 1412 collected, 57 skipped,
10 failed. The same 10 fail on untouched `3d696ba` in a worktree (1406
collected; Windows-only). Page tests (`oversight.test.js`,
`render.test.js`) 102/102. `mypy --platform linux`, `ruff check` and
`ruff format --check` are clean. `scripts/check_white_label.sh` passes and
`git diff --check` is clean.

CI for this change: green at `91139bc` (run 36344766255, `pull_request`;
the duplicate `push` run 36344763342 was cancelled): all six jobs, pytest
1355 passed, 57 skipped on 3.10 and 3.12, persistence 322, dashboard
115/115, Firestore rules 96/96.

**PHI with no network exposure recorded is a notice, 2026-09-27.** The
register carried `network_exposure`, and the form defaults it to
`Unknown`, but nothing asked for it. A record could handle PHI with no
account of whether that PHI crosses the internet, a VPN or a private
network. Transmission security (§164.312(e)) is assessed on that. The Sage
seed's three partners record none. Its three integrations record theirs.

`attention_findings()` and `attentionFindings()` now raise
`phi-exposure-unrecorded` (notice) for PHI whose network exposure is
blank, absent or the form's default `Unknown`. It comes after
`technical-owner-unassigned` and is not an access code. No route, stored
field, rule, vocabulary, token-file field or ledger line changed. Docs:
`docs/http-api.md`, `HANDOFF.md`.

Tests: the shared table grows 84 -> 90 cases (empty, absent, `Unknown`,
blank, no PHI, and order behind `technical-owner-unassigned`). One new
page test and one seed test name the three partners. The table's `clean`
base, the page's `clean` record and the HTTP governed record gained a
network exposure. The access-review index is unchanged: its DrChrono to
PRIMO integration records its exposure.

Two mutations each fail named tests. With the server check disabled, 6
fail: the five new table cases that expect the notice and the seed test.
With the page check disabled, 2 fail: the new page test and the shared
table.

Local gates on Windows, 2026-09-27: pytest 1419 collected, 57 skipped,
10 failed. The same 10 fail on untouched `f558238` in a worktree (1412
collected; Windows-only). Page tests (`oversight.test.js`,
`render.test.js`) 103/103. `mypy --platform linux`, `ruff check` and
`ruff format --check` are clean. `scripts/check_white_label.sh` passes and
`git diff --check` is clean.

CI for this change: green at `1ccac5c` (run 36359967726, `pull_request`;
the duplicate `push` run 36359965725 was cancelled): all six jobs, pytest
1362 passed, 57 skipped on 3.10 and 3.12, persistence 329, dashboard
116/116, Firestore rules 96/96.

**An assurance expiry set more than three years out is a notice,
2026-09-28.** `cert_expiration_date` was checked for expired, expiring and
(on a High or Critical rating) missing, never for how far ahead it was.
An expiry of `2099-12-31` kept a record out of `assurance-expired` for good
and satisfied `assurance-undated` on an elevated rating. That is the same
evasion `review-too-distant` closed for review dates.

`attention_findings()` and `attentionFindings()` now raise
`assurance-too-distant` (notice) for an expiry more than
`ASSURANCE_HORIZON_DAYS` (1096) after `as_of`. The horizon is ICIT policy,
not a standard: an ISO/IEC 27001 certificate's three-year cycle, a leap
day included, the longest-lived assurance the register names. It is not an
access code. No route, stored field, rule, vocabulary, token-file field or
ledger line changed. No Sage seed record carries it (none dates an
assurance yet). Docs: `docs/http-api.md`, `HANDOFF.md`.

Tests: the shared table grows 90 -> 97 cases (the horizon's last day, one
day past it, 2099, 2099 on a Critical rating, 2099 with no assurance named,
order behind `review-too-distant`, and a retired record). The fixture
carries `assurance_horizon_days`; Python asserts it equals both
constants and that the assurance horizon outlasts the review horizon. One
page test covers the edge, and one seed test names no record.

Two mutations each fail named tests. With the server check disabled, 5
fail: the five table cases that expect the notice. With the page check
disabled, 2 fail: the new page test and the shared table.

Local gates on Windows, 2026-09-28: pytest 1429 collected, 57 skipped,
10 failed. The same 10 fail on untouched `ed7fcf7` in a worktree (1419
collected; Windows-only). Page tests (`oversight.test.js`,
`render.test.js`) 104/104. `mypy --platform linux`, `ruff check` and
`ruff format --check` are clean. `scripts/check_white_label.sh` passes and
`git diff --check` is clean.

CI for this change: green at `0474cd0` (run 36451793517, `pull_request`;
the duplicate `push` run 36451788045 was cancelled): all six jobs, pytest
1372 passed, 57 skipped on 3.10 and 3.12, persistence 339, dashboard
117/117, Firestore rules 96/96.

**The operator runbooks' commands are held to the CLI, 2026-09-28.** Sage
staff grant, review and revoke a partner's access by pasting commands from
`HANDOFF.md` §17 and `docs/http-api.md`. Nothing checked those commands
against `ironclad` itself. A renamed flag or a moved subcommand would
first fail at an operator's terminal, mid-offboarding.

`tests/test_documented_commands.py` parses every `ironclad` /
`python -m ironclad.cli` line in a `sh` block of `README.md`, `HANDOFF.md`,
`docs/http-api.md` and `docs/ingestion-contract.md`, 55 of them, with
`build_parser()`. Continuations are joined, comments dropped, and parsing
stops at the first pipe or redirect. It parses and never runs them. A `...`
placeholder may leave required arguments out, but every flag shown must
exist. The 48 commands quoted inline in prose are usually partial
(`ironclad serve`, `[--anchor N:DIGEST]`), so for those every subcommand
and flag named must exist, and nothing more. STATUS.md and
PRODUCTIZE_NOTES.md are left out on purpose: they record what was run then.
A guard test requires at least 50 block commands, 40 prose mentions and
each access runbook (tokens issue / revoke / review, oversight access /
review-packet / verify-packet, access-log rotate / verify, tokens
verify-ledger). A change to how the docs quote commands therefore cannot
leave the file checking nothing.

No drift was found. All 103 documented commands match the CLI as it
stands. The value is the guard. Mutation: renaming `--on-behalf-of` in
`ironclad/cli.py` fails the two HANDOFF runbook commands that use it
(partner-linked issue, and offboarding revoke). No code, route, rule or
document behaviour changed. HANDOFF §17 says how to write a command so it
passes.

Local gates on Windows, 2026-09-28: pytest 1535 collected, 57 skipped,
10 failed. The same 10 fail on untouched `c4af49b` in a worktree (1429
collected; Windows-only). The new file is 106/106. `mypy --platform
linux`, `ruff check` and `ruff format --check` are clean.
`scripts/check_white_label.sh` passes and `git diff --check` is clean.

CI for this change: green at `2dd7962` (run 36504361651, `pull_request`;
the duplicate `push` run 36504358291 was cancelled): all six jobs, pytest
1478 passed, 57 skipped on 3.10 and 3.12, persistence 339, dashboard
117/117, Firestore rules 96/96.

**The pipelines' commands are held to the CLI, 2026-09-28.** The runbook
check above left out the one caller that runs `ironclad` for a client:
`compliance-assessment.yml` and the `Jenkinsfile` call
`python -m ironclad.cli` in shell, and nothing but a real dispatch or build
runs that shell. A flag renamed in `ironclad/cli.py` would first fail on a
client's assessment, after the evidence was staged. The existing workflow
check covered one direction of one list (every loader alias is a workflow
framework choice).

`tests/test_pipeline_commands.py` parses every `python -m ironclad.cli`
command in `ci.yml`, `compliance-assessment.yml`, `framework-updates.yml` and
the `Jenkinsfile` with `build_parser()`, without running it. That is 19
commands: 5 in CI, 8 in the workflow, 10 in Jenkins. An optional flag held
in a shell variable (`previous="--previous ..."`, `compare="--compare-to
..."`) is parsed both expanded and empty. A dispatch choice
(`${{ inputs.assessment_type }}` and the rest) is parsed with each option
the form offers, so the workflow's assessment step alone is 72 cases. The
workflow's framework, group and assessment-type options, the Jenkins
`FRAMEWORK` and `GROUP` choices, and the two smoke loops' framework lists
must each equal what the engine knows (loader aliases, registry groups,
report views), in both directions, with no duplicates. Every choice
default must be one of its options. A guard requires the assess, report,
export, `store latest`, `store health` and `store publish` steps of both
pipelines, and the assess step with and without `--previous`, to be among
those found.

No drift was found. Four mutations each fail named tests: renaming
`--compare-to` fails the report step in both pipelines, renaming
`store latest --before` fails the workflow's fetch, a group `express` offered
by the workflow fails the workflow-group case, and Jenkins dropping `hipaa`
fails the Jenkins-FRAMEWORK case. No code, workflow, route, rule or document
behaviour changed. `HANDOFF.md` §11 says so, and its table no longer calls
the workflow never executed (it has run as a dry run).

Local gates on Windows, 2026-09-28: pytest 1643 collected, 57 skipped,
10 failed. The same 10 fail on untouched `700330c` in a worktree (1535
collected; Windows-only). The new file is 108/108. `mypy --platform
linux`, `ruff check` and `ruff format --check` are clean.
`scripts/check_white_label.sh` passes and `git diff --check` is clean.

CI for this change: green at `560d83a` (run 36506607757, `pull_request`;
the duplicate `push` run 36506603473 was cancelled): all six jobs, pytest
1586 passed, 57 skipped on 3.10 and 3.12, persistence 339, dashboard
117/117, Firestore rules 96/96.

**The HTTP route table is held to the router, 2026-09-29.** The command
checks above cover what an operator types. The one surface a dashboard
author, a partner's integrator or an auditor reads to learn what
`ironclad serve` answers, and who may ask, is the route table in
`docs/http-api.md`. Nothing held it to `App._register()`. A route added
without a row would be a surface nobody reviewed. A row left after its
route was removed would be a promise the server breaks. A "Needs" cell out
of step with the permission the service checks would give an auditor the
wrong access rule.

`tests/test_documented_routes.py` reads the table and builds the router
without serving. Every row's method and path must be a registered route
(`/health` is asked through `App.handle` with no authenticator, the way a
load balancer asks), and every registered route must be a row. The query
parameters a row shows (`?limit=`, `?status=`, `?as_of=`) must be exactly
the ones its handler reads. The "Needs" cell must match what the handler
enforces. A permission such as `audit:read` must be the one the service
method it calls passes to `authorize`. "any role in the tenant" must be a
read-scoped register check. "owner, compliance manager, contributor" must
be a write-scoped check whose roles equal `oversight.MAINTAIN_ROLES`. "a
token" means authentication alone, and "nothing" is `/health` only. The
roles listed under Authentication must equal `Role`, and the register
kinds must equal `oversight.KINDS`. That is 65 cases.

No drift was found. Six mutations each fail named tests: the revoke row
saying `exception:read`, the service checking `report:read` for the audit
trail, `?limit=` dropped from the assessments row, an undocumented
`/oversight/raw` route, the review queue scoped as a write, and revoke
registered as `PUT`. No code, route, rule or document behaviour changed.

Local gates on Windows, 2026-09-29: pytest 1708 collected, 57 skipped,
10 failed. The 10 are the Windows-only set recorded for `560d83a` above
(symlinks, CRLF checkout, the 20-writer lock). The new file is 65/65.
`mypy --platform linux`, `ruff check` and `ruff format --check` are clean.
`scripts/check_white_label.sh` passes and `git diff --check` is clean.

CI for this change: green at `bb55e53` (run 36571709136, `pull_request`;
the duplicate `push` run 36571702107 was cancelled): all six jobs, pytest
1651 passed, 57 skipped on 3.10 and 3.12, persistence 339, dashboard
117/117, Firestore rules 96/96.

**The ingestion contract is held to the validators, and a dating defect is
fixed, 2026-10-03.** `docs/ingestion-contract.md` is what a client's evidence
collector and compliance lead write files against. `test_ingest.py` already
held its freshness windows, version and classifications. Nothing held the rest.
The exceptions section had drifted. It listed five statuses where the loader
accepts six (`expired` was missing), and it never said that `justification` and
`requested_by` are required. It now has a field table like the other sections.

`tests/test_documented_contract.py` checks each table row by behaviour, using
the document's own examples. A field marked required is removed and the
validator must name it. A field marked optional is removed and the file must
still validate and load. For exceptions, that runs once per status. Every field
`validate_manifest`, `validate_policy` and `policy_from_document` read must have
a row. The example manifest must be valid apart from its elided digest. The
example policy must validate and load. The prose's numbers (365 days, the
30-day review warning, 20,000 characters, 50 MB, 200 MB) must be the engine's
constants. That is 104 cases. Nine doc mutations each fail named tests: the
status list, `justification` marked optional, a renamed row, `approved_by`
loosened, `uri` loosened, `media_type` renamed, the 30-day and 50 MB figures,
and the example acceptance approved by its own requester.

Loading the example with the clock moved past its expiry found a defect. An
acceptance with no `requested_at` was dated from the moment the file was read.
The 365-day cap and the expiry were measured from today, so an approval running
20 months (approved 2025-10-01, expiring 2027-06-01) loaded. Once an acceptance
had run out, the whole policy refused to load ("expiry must be after the request
date") instead of the engine reporting it lapsed. The contract's example and a
fixture in `test_policy.py` would have started failing that way on 2026-11-15,
and the derived `exception_id` changed on every read. `policy_from_document`
now falls back to `approved_at` before the time of reading. The request came no
later than the approval, so the cap is never measured from a later date than
the true one. Three regression cases fail without the fix. The fixture with
no dates at all now gives `requested_at`. Files written by the service always
carry `requested_at`, so they are unaffected. A hand-written acceptance with
neither date is still dated from the time it is read; the contract now says so
and asks for `requested_at`.

Local gates on Windows, 2026-10-03: pytest 1812 collected, 57 skipped,
10 failed, the same set as untouched `3878395` run in a worktree (1708
collected, 57 skipped, 10 failed: symlinks, CRLF checkout, the 20-writer lock,
fcntl). The new file is 104/104.
`mypy --platform linux`, `ruff check` and `ruff format --check` are clean.
`scripts/check_white_label.sh` and `scripts/check_secret_literals.sh` pass.

CI for this change: green at `75e6694` (run 37160622941, `pull_request`;
the duplicate `push` run 37160620882 was cancelled): all six jobs, pytest
1755 passed, 57 skipped on 3.10 and 3.12, persistence 339, dashboard
117/117, Firestore rules 96/96.

**Cross-framework coverage no longer counts a pointer as coverage,
2026-10-05.** `Crosswalk.coverage` counted every target control any edge
reached, `related` edges included. A `related` edge never carries a verdict
(`INHERITANCE`), so a target reached only by one still needs a direct
assessment. Two shipped targets are like that: HIPAA `164.308(a)(3)(ii)(A)`
(workforce authorization, from `CC1.3`) and NIST CSF `ID.AM-05` (from `CC2.1`).
The figure reached the client: the `crosswalk_coverage` finding title ("HIPAA
Security Rule is 96% addressed by this assessment"), the report's "Coverage of
other frameworks" table, `ironclad crosswalk`, the generated
`docs/control-mapping.md` and the README. In the same finding, the detail's
count of controls needing direct review came from `inherit()` and did not
match the title. The true figures are HIPAA 91% (2 controls need direct
review, not 1) and NIST CSF 65% (15, not 14). PCI DSS stays at 82%.

`Crosswalk.addressed()` now returns the targets a verdict can reach. `coverage`,
`ironclad crosswalk`'s `unmapped_target_controls` and the generator's "needs
direct assessment" list all use it, so the percentage and the list add up to the
whole framework. The `related` edges are still listed under `mappings` and in the
doc's tables. `docs/control-mapping.md` is regenerated and the README is corrected.
`tests/test_frameworks.py::TestCoverage` (9 cases) checks that a `related`-only
target is not covered, that each verdict-carrying relationship is, and that an
edge authored in the other direction still counts. Per shipped target it checks
that coverage is exactly the set `inherit()` reaches with every SOC 2 control
met. It also checks that the README quotes the engine's figures and mapping
count. The CLI test now requires the coverage and unmapped list to add up to
the whole framework, with the HIPAA control among the unmapped. Removing the
relationship filter fails 5 of these (PCI correctly passes) and the generated
doc check.

Local gates on Windows, 2026-10-05: pytest 1821 collected, 57 skipped,
10 failed, the same set as untouched `8373959` run in a worktree (1812
collected, 57 skipped, 10 failed: symlinks, CRLF checkout, the 20-writer lock,
fcntl). `mypy --platform linux`, `ruff check`, `ruff format --check` and
`tools/build_control_mapping.py --check` are clean.
`scripts/check_white_label.sh` and `scripts/check_secret_literals.sh` pass.

CI for this change: green at `30a2d05` (run 37391953932, `pull_request`;
the duplicate `push` run 37391947692 was cancelled): all six jobs, pytest
1765 passed, 57 skipped on 3.10 and 3.12, persistence 339, dashboard
117/117, Firestore rules 96/96.

**A met control placed under a risk acceptance is a regression, 2026-10-06.**
`compare()` filed every move into `accepted_risk` as a decision, the compliant
one included. A control that was working and stopped, then got accepted, went
into "Accepted as risk" and not "Regressed". The headline and the report's
movement counts said "0 regressed" while readiness fell (credit 1.0 → 0.5).
The reverse move was already handled correctly: accepted and then fixed counts
as improved. Now `compliant → accepted_risk` is `regressed`, and the row shows
Was "Compliant", Now "Accepted risk". A gap or partial going into acceptance is
still a decision, not a movement, and its remediation item is still set aside,
not closed. `tests/test_compare.py::TestMovement::test_a_met_control_accepted_as_risk_is_a_regression`
holds it. Taking out the new branch fails that test.

Local gates on Windows, 2026-10-06: pytest 1823 collected, 57 skipped,
10 failed, the same set as untouched `5857b14` run in a worktree (1822
collected, 57 skipped, 10 failed: symlinks, CRLF checkout, the 20-writer lock,
fcntl). `mypy --platform linux`, `ruff check` and `ruff format --check` are
clean. `scripts/check_white_label.sh` and `scripts/check_secret_literals.sh`
pass.

CI for this change: green at `ed4ae22` (run 37468114223, `pull_request`;
the duplicate `push` run 37468108959 was cancelled): all six jobs, pytest
1766 passed, 57 skipped on 3.10 and 3.12, persistence 339, dashboard
117/117, Firestore rules 96/96.

**A remediation item whose control left the assessment is not closed,
2026-10-06.** `compare()` counted every item missing from the later plan as
closed unless its control was now accepted or scoped out. When a control was
in the earlier assessment and not in the later one, its item left the plan
with it and was counted as "remediation closed" in the headline and on the
report's card. The comparison already said such a control "is either a scope
change or a defect" and named it rather than dropping it, but then counted its
item as fixed work. Reproduced with the `tiny_framework` fixture: drop `CC9.9`
from the later run and its high-severity item came back in `remediation_closed`.
Such items now go into their own list, `remediation_control_gone`
(`"control_gone"` under `remediation` in the JSON). They are neither closed
nor set aside by decision. A caveat gives their count and says they are not
counted as closed. Two assessments against different frameworks share no
controls, so every earlier item now lands there instead of reading as closed.
`tests/test_compare.py::TestRemediationMovement::test_an_item_whose_control_left_the_assessment_is_not_closed`
holds it. It failed against `af57bc0` before the change.

Local gates on Windows, 2026-10-06: pytest 1824 collected, 57 skipped,
10 failed, the same set as untouched `af57bc0` run in a worktree (1823
collected, 57 skipped, 10 failed: symlinks, CRLF checkout, the 20-writer lock,
fcntl). `mypy --platform linux`, `ruff check` and `ruff format --check` are
clean. `scripts/check_white_label.sh` and `scripts/check_secret_literals.sh`
pass.

CI for this change: green at `2cd32bf` (run 37471526870, `pull_request`;
the duplicate `push` run 37471518420 was cancelled): all six jobs, pytest
1767 passed, 57 skipped on 3.10 and 3.12, persistence 339, dashboard
117/117, Firestore rules 96/96.

**A later run that planned no remediation closes nothing, 2026-10-06.**
The `quick` capability group leaves out `remediation_plan`. When a quick run
followed a deep or standard one, every item in the earlier plan was missing
from the later one. `compare()` counted each as "remediation closed" in the
headline and on the report's card. A caveat said the counts "are not a trend",
but the card and the headline still claimed the work was done. Reproduced with
the real engine: the `tiny_framework` fixture run `deep`, then `quick`, gave
2 of 2 items closed. Such items now go into their own list,
`remediation_unplanned` (`"unplanned"` under `remediation` in the JSON). They
are not closed, not set aside and not control-gone, and a second caveat gives
their count. The opposite direction is unchanged: a quick run followed by a
deep one still reports the deep run's items as opened, under the existing
caveat (`test_a_run_without_remediation_planning_is_not_a_remediation_trend`
pins that). Overstating open work does not flatter the client.
`tests/test_compare.py::TestTheComparisonRefusesToMislead::test_a_later_run_without_remediation_planning_closes_nothing`
holds it. It failed against `8603c38` before the change.

Local gates on Windows, 2026-10-06: pytest 1825 collected, 57 skipped,
10 failed, the same set as untouched `8603c38` run in a worktree (1824
collected, 57 skipped, 10 failed: symlinks, CRLF checkout, the 20-writer lock,
fcntl). `mypy --platform linux`, `ruff check` and `ruff format --check` are
clean. `scripts/check_white_label.sh` and `scripts/check_secret_literals.sh`
pass.

CI for this change: green at `7294a1e` (run 37474988157, `pull_request`;
the duplicate `push` run 37474977721 also ran to completion, green,
before it could be cancelled): all six jobs, pytest 1768 passed, 57 skipped on 3.10 and 3.12,
persistence 339, dashboard 117/117, Firestore rules 96/96.

**An earlier run that planned no remediation opens nothing, 2026-10-06.**
This is the opposite direction, which the entry above left alone. When a quick
run was followed by a deep or standard one, every item in the later plan was
new to the earlier run. `compare()` counted each as opened: "N opened" in the
headline and "Newly raised" on the client report's card. Only a caveat said
the counts were not a trend. The entry above reasoned that overstating open
work does not flatter the client. It still misstates the trend, though: a
client or auditor reading "Newly raised: 2" infers that two gaps appeared
between the runs, and the record shows nothing of the kind. Reproduced with
the real engine: the `tiny_framework` fixture run `quick`, then `deep`, gave
2 of 2 items opened. Such items now go into their own list,
`remediation_first_planned` (`"first_planned"` under `remediation` in the
JSON). They are not opened, and a caveat gives their count. Items in both
plans and items the earlier run alone held are unaffected.
`test_a_run_without_remediation_planning_is_not_a_remediation_trend` no
longer asserts the opened count. It asserted that the misleading number was
still reported.
`tests/test_compare.py::TestTheComparisonRefusesToMislead::test_an_earlier_run_without_remediation_planning_opens_nothing`
holds the change. It failed against `2b48f30` before the change.

Local gates on Windows, 2026-10-06: pytest 1826 collected, 57 skipped,
10 failed, the same set as untouched `2b48f30` run in a worktree (1825
collected, 57 skipped, 10 failed: symlinks, CRLF checkout, the 20-writer lock,
fcntl). `mypy --platform linux`, `ruff check` and `ruff format --check` are
clean. `scripts/check_white_label.sh` and `scripts/check_secret_literals.sh`
pass.

CI for this change: green at `c33cf00` (run 37479720179, `pull_request`;
the duplicate `push` run 37479715352 was cancelled): all six jobs, pytest 1769 passed,
57 skipped on 3.10 and 3.12, persistence 339, dashboard 117/117, Firestore rules 96/96.

**A remediation item whose control joined the assessment is not opened,
2026-10-06.** This is the mirror of the control-gone entry above, which only
fixed the closing side. When a control was absent from the earlier assessment
and present in the later one, its item arrived in the later plan with it.
`compare()` counted that item as opened: "N opened" in the headline and
"Newly raised" on the client report's card. The caveat named the control as
present in only one run, but nothing says its gap appeared between the two.
Two assessments against different frameworks share no controls, so every
later item read as newly raised, while every earlier item already went to
`remediation_control_gone`. Reproduced with the `tiny_framework` fixture:
drop `CC9.9` from the earlier run and its item came back in
`remediation_opened`. Such items now go into their own list,
`remediation_control_new` (`"control_new"` under `remediation` in the JSON),
and a caveat gives their count. An earlier run that planned no remediation
still sends every later item to `remediation_first_planned`, as the
unplanned case comes before control-gone on the closing side.
`tests/test_compare.py::TestRemediationMovement::test_an_item_whose_control_joined_the_assessment_is_not_opened`
holds it. It failed against `5d54788` before the change.

Local gates on Windows, 2026-10-06: pytest 1827 collected, 57 skipped,
10 failed, the same set as untouched `5d54788` run in a worktree (1826
collected, 57 skipped, 10 failed: symlinks, CRLF checkout, the 20-writer lock,
fcntl). `mypy --platform linux`, `ruff check` and `ruff format --check` are
clean. `scripts/check_white_label.sh` and `scripts/check_secret_literals.sh`
pass.

CI for this change: green at `9b51ec8` (run 37483094514, `pull_request`;
the duplicate `push` run 37483086366 was cancelled): all six jobs, pytest 1770 passed,
57 skipped on 3.10 and 3.12, persistence 339, dashboard 117/117, Firestore rules 96/96.

**An item that returns when a decision ends is not opened, 2026-10-06.**
This is the mirror of `remediation_set_aside`, which only covered the closing
side. The planner plans only gap and partial controls, and an item's id is
minted from the tenant and the control. A control under a risk acceptance, or
out of scope, therefore has no item. When the acceptance lapsed, or the control
came back into scope, its item reappeared in the later plan. `compare()`
counted it as opened: "N opened" in the headline and "Newly raised" on the
client report's card. The control lists already said the acceptance had lapsed
or the scope had changed, and nothing says the gap is new. It was there all
along, under a decision. Reproduced with the real engine: the `tiny_framework`
fixture run `deep` with an approved acceptance of `CC9.9` that expires before
the second run. The second run reported `CC9.9` under `acceptance_lapsed` and
its item under `remediation_opened`. Such items now go into their own list,
`remediation_resumed` (`"resumed"` under `remediation` in the JSON), and a
caveat gives their count. The order of the checks keeps the earlier cases
first: an earlier run that planned nothing still sends every later item to
`first_planned`, and a control absent from the earlier run still goes to
`control_new`.
`tests/test_compare.py::TestRemediationMovement::test_an_item_whose_decision_ended_is_not_opened`
(accepted and out-of-scope) and
`test_a_lapsed_acceptance_opens_nothing_with_the_real_engine` hold it. All three
failed against `963a0e0` before the change.

Local gates on Windows, 2026-10-06: pytest 1829 collected, 57 skipped,
10 failed, the same set as untouched `963a0e0` run in a worktree (1827
collected, 57 skipped, 10 failed: symlinks, CRLF checkout, the 20-writer lock,
fcntl). The engine case was added after that run began and passes in
`tests/test_compare.py` alone (all 52 pass). `mypy --platform linux`, `ruff
check` and `ruff format --check` are clean. `scripts/check_white_label.sh`
and `scripts/check_secret_literals.sh` pass.

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
