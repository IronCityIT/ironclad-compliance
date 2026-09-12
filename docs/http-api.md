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
   "tenant_id": "acme", "roles": ["compliance_manager"]}
]}
EOF

# 3. serve
IRONCLAD_STORE=/srv/ironclad/results \
  ironclad serve --policy-root /srv/ironclad/policies \
                 --tokens /srv/ironclad/tokens.json \
                 --static dashboard/public
```

- `--policy-root` holds `<tenant>/policy.json` and its audit sidecar per tenant.
  The directory for a tenant is created on that tenant's first write, after the
  write has been authorized — a refused request creates nothing.
- Without `--tokens` the server starts and answers every request with 503. It
  never falls open.
- Binds `127.0.0.1:8787` unless told otherwise. It speaks plain HTTP; a reverse
  proxy terminates TLS in front of it.

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
and 503 when there is no authenticator or it cannot read its file.

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

## What is not here

Running an assessment. The pipeline runs assessments, with evidence staged
from the tenant's volume; a POST carrying evidence is a different product with
a different threat model. The surface reads results and works the acceptance
workflow, which is everything the dashboard does today.
