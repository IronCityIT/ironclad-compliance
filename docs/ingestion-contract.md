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
| `uri` | yes | must be unique within the manifest |
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

| Evidence class | Window |
|---|---|
| vulnerability scan, backup, log, monitoring | 30 days |
| access review, review, ticket | 90 days |
| meeting minutes | 180 days |
| policy, charter, training, risk assessment, penetration test | 365 days |
| anything else | 365 days |

Set `valid_until` explicitly to override. With no manifest at all the file's own
name is used as the evidence type, so `Q3 access review.xlsx` still ages on the
90-day clock rather than the annual one.

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

**Identity is the checksum.** An artifact's id is derived from `sha256` where
one is supplied, so the same file re-submitted under a new path is recognised as
the same evidence rather than counted twice. Without a checksum the URI is used
instead.

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
