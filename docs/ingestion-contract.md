# Evidence ingestion contract

**Version 1.0**

The agreement between whatever collects a client's evidence — a storage sync, a
document-management connector, a client upload — and the assessment engine.

It is declared, versioned and validated strictly for one reason: without it, a
half-delivered evidence set produces a report full of gaps that are really a
broken pipeline, and nobody can tell the difference by looking at the report.

## Shape

```json
{
  "contract_version": "1.0",
  "tenant_id": "acme-corp",
  "framework": "soc2",
  "source_system": "gcs",
  "collected_at": "2026-09-05T12:00:00+00:00",
  "items": [
    {
      "name": "Access Control Policy.pdf",
      "uri": "gs://ironclad-evidence/acme-corp/access-control-policy.pdf",
      "evidence_type": "Access control policy",
      "media_type": "application/pdf",
      "sha256": "3b1f…64 hex characters…a7",
      "size_bytes": 148213,
      "collected_at": "2026-09-01T00:00:00+00:00",
      "valid_from": "2026-01-15T00:00:00+00:00",
      "valid_until": "2027-01-15T00:00:00+00:00",
      "classification": "confidential",
      "control_hints": ["CC6.1", "CC6.2"]
    }
  ]
}
```

## Document fields

| Field | Required | Notes |
|---|---|---|
| `contract_version` | yes | must be `"1.0"`; an unknown version is refused rather than guessed at |
| `tenant_id` | yes | normalized to a slug; must match the tenant the assessment runs for |
| `framework` | no | advisory; the assessment's own `--framework` decides |
| `source_system` | no | recorded on every artifact for traceability |
| `collected_at` | no | ISO-8601; the default `collected_at` for items that omit their own |
| `items` | yes | may be empty — see *An empty set is legitimate* below |

## Item fields

| Field | Required | Notes |
|---|---|---|
| `name` | yes | as shown to a human in the report and the evidence index |
| `uri` | yes | must be unique within the manifest; a local path must resolve inside the evidence directory — see *Rules* |
| `evidence_type` | no | **drives the freshness window** — see below |
| `media_type` | no | advisory |
| `sha256` | no | 64 hex characters. Strongly recommended: it is what gives an artifact a stable identity |
| `size_bytes` | no | non-negative integer |
| `collected_at` | no | ISO-8601 |
| `valid_from` | no | when the evidence period starts |
| `valid_until` | no | explicit expiry; overrides the derived window |
| `classification` | no | `public`, `internal`, `confidential` (default), `restricted` |
| `control_hints` | no | control ids a human asserts this item supports |

## Why `evidence_type` matters

The freshness window is derived from it. An access review from fourteen months
ago does not evidence a control today, and an auditor will say so — the engine
says so first.

The classes below are matched as substrings of `evidence_type`, longest match
first, so `Quarterly vulnerability scan` takes the scan window rather than the
default. This table is checked against the engine's own `VALIDITY_DAYS` by a
test — a window that changes in the code and not here fails the build.

| Evidence class | Window |
|---|---|
| scan, vulnerability scan, backup, log, monitoring | 30 days |
| access review, review, ticket | 90 days |
| meeting minutes | 180 days |
| policy, charter, training, risk assessment, penetration test | 365 days |
| anything else | 365 days |

Set `valid_until` explicitly to override. With no manifest at all the file's own
name is used as the evidence type, so `Q3 access review.xlsx` still ages on the
90-day clock rather than the annual one.

The windows are Iron City policy and the manifest is the tenant's own file, so
the dates in it cannot quietly move the clock. A `collected_at` or `valid_from`
more than a day in the future is pulled back to the time of ingestion and the
item is named in a warning. A `valid_until` that runs past the standard window
for the item's class stands — that is what the override is for — and is
disclosed in a warning that reaches the report's caveats; one that shortens the
window is nobody's business.

With no manifest, hidden files and directories (`.DS_Store`, `.git/`) and the
`__MACOSX` resource forks a Mac zip leaves behind are not treated as evidence.
The skip is reported as a warning naming them, never silent; declare such a file
in a manifest if it really is evidence.

## `control_hints`

How a human asserts a link the automatic matcher would miss — a scanned policy
with no extractable text, or evidence whose wording shares nothing with the
control. A hint produces a **manual** link, recorded as asserted rather than
derived, so an auditor reading `evidence-index.csv` can tell them apart.

Hints are additive. They never suppress a match the engine found on its own.

## Rules

**Every fault is reported at once.** Validation does not stop at the first
problem; a manifest that is wrong in four places tells you all four.

**An empty set is legitimate — when declared.** A client who has submitted
nothing yet is a real state. The contract accepts `"items": []`, and the
assessment then reports plainly that no evidence was submitted. What the
contract exists to prevent is that state being *inferred* from a failed download.

**Remote URIs are catalogued, not fetched.** A `gs://` or `https://` item is
recorded — an auditor can be pointed at it — but the engine reads only local
paths. The pipeline downloads first and hands over a manifest pointing at the
local copies. The engine never reaches out to storage on its own.

**A local URI must lie inside the evidence directory.** The manifest is the
tenant's own file, so every URI in it is tenant-supplied. When the engine is
given a directory — which is how the CLI and the pipeline always call it — a
local item that resolves anywhere else is refused, whether written as
`../other-client/policy.pdf`, as an absolute path, or as a symlink that lands
outside; and the refusal names every offending item. The same rule applies to
a directory with no manifest: symbolic links in it are refused, not followed.
Existence is not the test — a path outside the directory would otherwise be
recorded in the tenant's evidence inventory even when nothing is there.

**Identity is the checksum, and a copy is counted once.** An artifact's id is
derived from `sha256` where one is supplied, so the same file re-submitted under
a new path is recognised as the same evidence rather than counted twice. Without
a checksum the URI is used instead. Beyond bytes, two items whose extracted text
is the same once case and whitespace are set aside are one document: the
earlier submission (by `collected_at`, or the file's own timestamp) is kept, its
`control_hints` merged, and the copy is named in a warning. The corroboration
rule asks for two *independent* items; a second copy of the policy is not one.

**An unreadable item is a fact about the pipeline, not the client.** A corrupt
PDF is catalogued and reported as unreadable at `info` severity. It never
silently becomes "no relevant content", which is the same thing as a control gap
from the report's point of view.

## Validating

```sh
ironclad validate --manifest evidence/evidence-manifest.json
```

Exit `0` valid, `2` with the faults listed as JSON.

## Without a manifest

Point the engine at a directory. A manifest is derived: every file catalogued,
checksummed, and typed from its own filename.

```sh
ironclad assess --client "Acme Corp" --framework soc2 --evidence-dir evidence/
```

A manifest is better — it carries evidence types, validity periods and asserted
links that a filename cannot — but its absence never blocks an assessment.

---

# Tenant policy

**Version 1.0** — `policy.json` beside the evidence, or `--policy <path>`.

Three client-specific decisions an assessment has to honour. Without this file
the engine can produce neither a `not_applicable` nor an `accepted_risk` verdict,
so the risk-acceptance workflow is unreachable.

```json
{
  "policy_version": "1.0",
  "tenant_id": "acme-corp",
  "scope_exclusions": [
    {
      "control_id": "CC6.4",
      "justification": "All infrastructure is cloud-hosted; the organisation operates no data centre of its own.",
      "approved_by": "j.reyes (CISO)",
      "approved_at": "2026-03-01T00:00:00+00:00",
      "review_by": "2027-03-01T00:00:00+00:00"
    }
  ],
  "exceptions": [
    {
      "control_id": "CC9.2",
      "justification": "The vendor risk programme is being rebuilt following the acquisition.",
      "requested_by": "m.okafor",
      "approved_by": "j.reyes (CISO)",
      "approved_at": "2026-08-15T00:00:00+00:00",
      "expires_at": "2026-11-15T00:00:00+00:00",
      "compensating_controls": ["Monthly manual review of critical vendor attestations"],
      "status": "approved"
    }
  ],
  "owners": {
    "CC6.*": "platform-team@acme.example",
    "CC1.1": "people-ops@acme.example"
  }
}
```

## Scope exclusions

A scoped-out control leaves the readiness denominator entirely, which makes
scoping the cheapest way to make a failing control disappear. It is therefore
held to the same bar as a risk acceptance:

| Field | Required | Notes |
|---|---|---|
| `control_id` | yes | must exist in the framework being assessed |
| `justification` | yes | a written reason. A scope-out with no reason is refused |
| `approved_by` | yes | someone owns the decision. Recorded in the audit trail |
| `approved_at` | no | defaults to the time of the run |
| `review_by` | no | when the determination falls due for re-examination |

Three things are reported rather than silently honoured:

- an exclusion **past its `review_by`** — "not applicable" was true about a
  business three years ago and may not be true now
- an exclusion **falling due** within 30 days
- an excluded control that the **evidence nonetheless supports**, which usually
  means the exclusion has outlived its reason

## Exceptions

The same shape as the service API's risk acceptance, and held to the same rules —
they are enforced by replaying the approval workflow rather than by trusting the
file, so a policy **cannot assert an approval the workflow would refuse**:

- the approver may not be the requester
- an approved acceptance must name its approver and must carry an expiry
- no acceptance may run beyond 365 days

`status` may be `draft`, `pending_approval`, `approved`, `rejected` or `revoked`.
Only an approved, unexpired acceptance changes a verdict.

Where a control is both excluded and accepted, **the exclusion wins** and the
run warns — otherwise the control would return to the denominator as
`accepted_risk`.

## Owners

Maps a control to whoever the work should go to. `"CC6.*"` assigns a whole
family; an exact control id beats a wildcard. The owner lands on every
remediation item for that control, which is the difference between a report line
and a piece of work someone is accountable for.

## Validating

```sh
ironclad validate --policy policy.json
```

This checks the schema **and** replays the approval workflow, so a self-approved
acceptance fails validation rather than surfacing at assessment time.
