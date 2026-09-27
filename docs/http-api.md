# HTTP API — the dashboard's backend without Firebase

`ironclad serve` exposes `ComplianceService` over HTTP. It is the same service
the CLI drives: assessments and remediation are read from the result store (a
NAS volume or MariaDB) and the risk-acceptance workflow runs against each
tenant's policy file. Standard library only, so it runs on the NAS with nothing
installed.

This is migration stage 5's prerequisite (`HANDOFF.md` §13): a backend the
dashboard can read from that is not Firestore. The dashboard's data layer is not
yet pointed at it.

## Running it

```sh
# 1. a token for one person, hashed; the token itself never touches a file or
#    a command line
printf '%s\n' "$TOKEN" | ironclad hash-token      # prints the sha256 digest

# 2. the token file — digests, user ids, tenants, roles
cat > /srv/ironclad/tokens.json <<'EOF'
{"tokens": [
  {"sha256": "<digest from step 1>", "user_id": "alice@acme.example",
   "tenant_id": "acme", "roles": ["compliance_manager"],
   "expires_at": "2026-12-31"}
]}
EOF
ironclad tokens review /srv/ironclad/tokens.json   # who holds access, and what is wrong

# 3. serve
IRONCLAD_STORE=/srv/ironclad/results \
  ironclad serve --policy-root /srv/ironclad/policies \
                 --tokens /srv/ironclad/tokens.json \
                 --static dashboard/public                  --access-log /srv/ironclad/logs/access.log
```

- `--policy-root` holds `<tenant>/policy.json`, its audit sidecar and a
  `policy.json.lock` per tenant. The directory for a tenant is created on that
  tenant's first authorized write — a refused request creates nothing. Every
  write path holds the lock for its whole read-modify-write, so two people
  acting at once take turns, and the CLI working on the same volume takes the
  same lock; both files are replaced atomically, so a reader never sees a
  half-written one.
- Without `--tokens` the server starts and answers every request with 503. It
  never falls open.
- `expires_at` (`YYYY-MM-DD`, optional) is the last day a token works, in UTC;
  from the next day it is refused with 401, no restart needed, since the file
  is re-read on every request. An `expires_at` that is not a calendar date
  refuses the token, and so does a digest listed in two entries: neither is
  guessed at. An entry without one works until it is removed, and
  `ironclad tokens review` reports it. The review lists every entry's user,
  tenant, roles, expiry and state (`active`, `expiring` within 30 days,
  `expired`, `refused`) and exits 4 under `--fail-on high|any`; it reads
  digests only and prints a 12-character prefix of each. An expired token is
  logged like any unrecognised one: `user` is `null`.
- `ironclad tokens review FILE --access-log LOG` adds each entry's use: its
  request count, its 403 count and its last request, matched on the user and
  tenant the log names (the log holds no digest, so two entries for one user
  share their use). The log is verified first, and a log that is not a whole
  chain gets no review (exit 4). Lines after `--as-of` are not counted. Two
  notices follow: an active entry with no request in `--dormant-days` (90 by
  default, our number; "since the log begins" when it has none, so a rotated
  log narrows what the review can see), and any 403, with the latest path.
  An expired entry's use is shown and not called dormant; it is already high.
- Binds `127.0.0.1:8787` unless told otherwise. It speaks plain HTTP; a reverse
  proxy terminates TLS in front of it.
- A connection that sends nothing for 30 seconds — the rest of a request, the
  rest of a declared body, or the next request on a kept-alive connection — is
  closed. A browser reconnects; a client that never finishes its request does
  not keep a thread. (`READ_TIMEOUT_SECONDS`; the proxy in front should have
  its own, shorter, client limits.)

## Access log

With `--access-log FILE` the server appends one line per API request, before
the answer is sent: when (UTC), the token's `user` and `user_tenant` (both
`null` for a request with no recognised token), the method, the path and the
status. Reads, writes and refusals alike, so a partner's token probing another
tenant's register is recorded by name with the 403 it got. Health checks and
the dashboard's static files are not recorded. The query string, the body and
every header, the token included, never are: the path names a tenant and a
record id, and nothing a record says.

Each line carries a `seq`, the previous line's digest and its own, like the
policy audit trail, so a line edited, deleted or reordered breaks the chain
from there on. `ironclad access-log verify FILE` prints the number of entries,
the first broken line and the head digest, and exits 4 if the chain is broken
(2 if the file cannot be read). The server re-checks the file when it starts
and refuses to append to a broken one: move it aside (it is the evidence) and
start a new file. As with the register seal, the chain proves nothing on its
own; copy the head digest somewhere the server's operators cannot write.

If a line cannot be written, the caller gets 503 and nothing else. A write that
had already landed stays landed and is named in the register's own history;
nothing is read out of the server without a line. One server per file.

## Authentication

`Authorization: Bearer <token>`. The token file is re-read on every request —
it is the record, not a cache — so removing an entry revokes the token at the
next request. A malformed or missing token file makes the server answer 503 to
everyone; it does not serve anyone while it cannot tell who they are.

A token is bound to one tenant and a set of roles (`owner`,
`compliance_manager`, `contributor`, `auditor`, `viewer` — the matrix in
`ironclad/model/tenant.py`). A token file entry whose `tenant_id` is not its own
slug authenticates nobody.

Auth0-issued JWTs are not verified by this authenticator: RS256 needs RSA
signature verification the standard library does not provide. A JWT
authenticator is a second implementation of the same `Authenticator` protocol
behind a dependency decision, not a change to the surface.

## Routes

All under `/api/v1`. Every answer is JSON of the shape
`{"ok": bool, "data": {...}, "errors": [...]}`.

| Method | Path | Needs | Returns |
|---|---|---|---|
| GET | `/health` | nothing | `ok`, `version`, `store` kind, `writable` — never a path or DSN |
| GET | `/me` | a token | the principal and its permissions |
| GET | `/catalog` | a token | modules, groups, frameworks — from `registry.catalog()`, the same source the CLI uses |
| GET | `/tenants/{t}/assessments?limit=` | `assessment:read` | summaries, most recent first |
| GET | `/tenants/{t}/assessments/{id}` | `assessment:read` | one assessment record |
| GET | `/tenants/{t}/remediation?limit=` | `remediation:read` | the queue from the latest assessment |
| GET | `/tenants/{t}/exceptions?status=` | `exception:read` | the risk-acceptance register |
| POST | `/tenants/{t}/exceptions` | `exception:request` | raise an acceptance; body: `control_id`, `justification`, `compensating_controls`, `expires_in_days` |
| POST | `/tenants/{t}/exceptions/{id}/approve` | `exception:approve` | approve; separation of duties is enforced by the model |
| POST | `/tenants/{t}/exceptions/{id}/revoke` | `exception:approve` | revoke; body: `reason` |
| GET | `/tenants/{t}/audit?limit=` | `audit:read` | the hash-chained trail |
| GET | `/tenants/{t}/oversight/attention?as_of=` | any role in the tenant | the review queue across both registers, as of `as_of` (`YYYY-MM-DD`, default today in UTC) |
| GET | `/tenants/{t}/oversight/verification` | any role in the tenant | every record's history in both registers re-checked, with a verdict each |
| GET | `/tenants/{t}/oversight/seal` | any role in the tenant | a digest of every history entry in both registers, for the caller to keep outside the store |
| GET | `/tenants/{t}/oversight/{kind}` | any role in the tenant | the register's current records; `kind` is `partners` or `integrations` |
| POST | `/tenants/{t}/oversight/{kind}` | owner, compliance manager, contributor | create; body: `{"fields": {...}}` |
| GET | `/tenants/{t}/oversight/{kind}/{id}` | any role in the tenant | one record |
| POST | `/tenants/{t}/oversight/{kind}/{id}` | owner, compliance manager, contributor | edit; body: `{"base_revision": n, "fields": {...}}` |
| GET | `/tenants/{t}/oversight/{kind}/{id}/history` | any role in the tenant | every revision, oldest first, and a `verification` verdict |

Anything that is not under `/api/v1/` is served from `--static` if given, with
the resolved path checked to be inside the static root — `..` and a symlink
pointing out of it are both 404.

## Status codes

The service reports every refusal with a *kind*, and the transport maps the
kind rather than parsing the message:

| `ServiceResponse.kind` | HTTP |
|---|---|
| `validation` | 400 |
| `authorization` | 403 |
| `not_found` | 404 |
| `unavailable` | 503 |

Plus, from the transport itself: 401 for no or an unknown token, 405 for the
wrong verb on a known path, 413 for a body over 64 KiB (refused unread, and the
connection is closed so the unread bytes are not parsed as a second request),
501 for any `Transfer-Encoding` — a body is framed by `Content-Length` only, and a
chunked one is refused unread and the connection closed for the same reason; a
`Content-Length` that is not one plain decimal number (`+7`, `0_7`, a repeated or
listed header) is a 400 with the connection closed, likewise — and
503 when there is no authenticator or it cannot read its file.

## Tenant rules

- The tenant in the path is what the caller is asking about. The service
  compares it with the tenant the token is bound to and refuses a mismatch with
  403 — the same message whether or not the other tenant exists.
- A path segment that is not its own slug (`Acme`, `ACME-CORP`, `acme..`) is
  refused with 400 before it can become a directory name on the policy volume.
- A body naming a different `tenant_id` or `client_id` is dropped; the path is
  what gets authorized.
- `requested_by` on a raised acceptance is the token's user, whatever the body
  says. The service accepts a `requested_by` for the CLI, where the actor is a
  flag; over HTTP, honouring it would let one person raise an acceptance "for"
  a colleague and then approve it themselves. The test that found this is
  `test_the_body_cannot_name_a_different_requester`.
- A control carries **one open acceptance at a time** — draft, pending or
  approved. A second request while one is open is refused with 400 naming the
  acceptance in the way. A rejected, expired or revoked one is history: it stays
  on the record and does not stop the next request, which is how an acceptance
  is renewed after it lapses.
- `expires_in_days` is a whole number from 1 to 365; `control_id` is a string.
  Anything else is 400, never a coerced value on the record.

## Partner and integration register

The register the Sage Spine workspace keeps (`dashboard/public/oversight.html`),
served from the result store rather than Firestore. The policy is
`ironclad/oversight.py`, which is `firestore.rules`' create and update
predicates as Python; the store writes each revision and its history entry as
one step (`put_oversight`). The dashboard still writes Firestore; pointing it
here waits on B6, the browser sign-in. A service token can use these routes now.

- **Tenant and role first.** A caller from another tenant is refused with 403
  before the store is asked anything, with the same message whether the record
  id exists or not. A viewer or auditor reads the register and its history and
  cannot write (403).
- **The server stamps.** `tenant_id`, `revision`, `created_*` and `updated_*`
  come from the token and the clock. A body that supplies any of them is
  refused with 400, not quietly overwritten.
- **A closed schema.** A field the register does not have, a value outside a
  vocabulary (`risk`, `status`, `agreement_status`, `baa_status`,
  `data_access`, `data_flow_direction`), a date that is not `YYYY-MM-DD` or
  over-long text is 400, and `errors` names every problem.
- **A contributor proposes, an approver rates.** A contributor's new record
  starts unrated. A contributor who sets or moves `status`, `risk`,
  `agreement_status` or `baa_status` gets 403.
- **No lost updates.** An edit must carry `base_revision`, the revision its
  form was loaded from. If the record has moved on since, the edit gets 409 and
  nothing is written. Two editors who both start from revision *n* cannot both
  land.
- **The history reports its own state.** `/history` returns every revision as
  written plus `verification`: `verified`, `revisions`, `broken_at` and
  `detail`. A missing or edited revision on the volume shows up there as
  `verified: false`.
- **The review queue.** `/oversight/attention` is the page's *Needs attention*
  list, computed on the server from stored fields only: PHI without an executed
  BAA, a BAA marked executed without its date or document, a review overdue or
  assurance expired (high); a review or expiry within 30 days, no review date,
  risk unrated, data access unknown (notice). Retired records are left out.
  Each item carries `kind`, `id`, `name`, `revision`, its highest `level` and
  its `findings` (`level`, `code`, `message`); high items come first, then by
  name, with `records` and `high` counts. The rules are
  `attention_findings()` in `ironclad/oversight.py`, held finding for finding
  to the dashboard's `attentionFindings()` by one table of cases,
  `tests/fixtures/oversight-attention.json`. An `as_of` that is not a calendar
  day is 400; a POST there is 404, since `attention` is not a register.
- **The integrity sweep.** `/oversight/verification` re-checks every record
  in both registers the way `/history` checks one, and walks every id that
  has a record *or* any history, so a MariaDB record row deleted from under
  its history is reported (`history exists for a record that does not`)
  rather than silently missing from the inventory. The body is `tenant_id`,
  `records`, `broken`, `verified` (true only if every record is) and `items`,
  one per record: `kind`, `id` and the same verdict fields as `/history`. A
  POST there is 404. The sweep checks each history against itself, so two
  things pass it: an entry rewritten in place that keeps its revision, tenant
  and creation stamp (a rating, a BAA date, who approved), and, on a volume,
  a record whose *latest* revision file was removed, which rolls back to a
  whole, shorter history. The seal is the answer to both.
- **The seal.** `/oversight/seal` is the anchor kept outside the store:
  `format` (`ironclad-oversight-seal/1`), `tenant_id`, `sealed_at`,
  `sealed_by`, `records` (per record: `kind`, `id`, `revisions`, and the
  SHA-256 of each entry over sorted-key compact JSON, oldest first) and
  `digest`, one hash over the tenant and every entry. The digest leaves out
  who sealed and when, so an unchanged register seals to the same digest.
  Whoever relies on the register later (an auditor, a CI job) keeps the file
  and writes the digest down somewhere else. `ironclad oversight
  compare-seals --earlier A --later B` then needs no store: every sealed
  record must still be there with the same entries, and new revisions and
  records are reported, not refused; `ironclad oversight verify --seal A`
  does the same against the store. A seal edited after it was taken no
  longer matches its digest and is refused. The seal proves nothing on its
  own: it is as good as the place it is kept, and the digest is what makes
  that place checkable. A POST there is 404.
- An unknown `kind` or record is 404. A record id outside `[A-Za-z0-9_-]` is
  400. A store that does not hold the register answers 503.

## What is not here

Running an assessment. The pipeline runs assessments, with evidence staged
from the tenant's volume; a POST carrying evidence is a different product with
a different threat model. The surface reads results, works the acceptance
workflow and maintains the partner/integration register, which is everything
the dashboard does today.
