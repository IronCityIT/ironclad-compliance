"""Resolving a tenant's evidence on a NAS-backed volume.

The pipeline fetched evidence with `gcloud storage cp` from a `gs://` prefix.
GCP storage is retired from the target architecture: evidence lives on a
NAS-backed volume, laid out one prefix per tenant.

    <root>/<tenant_id>/...

This is the rule that decides which prefix a run may read, and it lives here
rather than in the workflow's shell for the same reason the equivalent check in
`functions/core.js` does — a containment test written in shell is a
`--recursive` away from reading another client's documents, and nothing tests
shell.

The rule is structural, not textual. `<root>/acme/../beta/` names beta's
evidence however it is spelled, so the resolved path is compared against the
resolved root: a prefix that does not sit under the tenant's own directory is
refused whatever route it took to get there, including a symlink planted inside
one tenant's tree pointing at another's.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ironclad.errors import IroncladError
from ironclad.ids import slugify


class EvidenceRootError(IroncladError):
    """The evidence prefix could not be used. Raised, never worked around."""


@dataclass(frozen=True)
class EvidencePrefix:
    """One tenant's evidence directory, resolved and checked."""

    tenant_id: str
    root: Path
    path: Path
    file_count: int


def resolve_prefix(root: Path | str, client: str) -> EvidencePrefix:
    """The tenant's own evidence directory under `root`.

    Refuses anything that does not resolve to a directory inside the tenant's
    own prefix, and refuses an empty one: a fetch that silently produces no
    evidence makes an assessment report every control as a gap, which reads to a
    client as a catastrophic result rather than a broken fetch. That mistake has
    been made in this pipeline before — see PRODUCTIZE_NOTES.md §2.2.
    """
    # Slugify coerces "Acme Corp" into "acme-corp", which is the point. It also
    # quietly turns "../other-client" into "other-client" — a *different valid
    # tenant*, which is not a traversal but is a silent reinterpretation of what
    # was asked for, and this product refuses those rather than guessing.
    raw = str(client or "")
    if "/" in raw or "\\" in raw or ".." in raw:
        raise EvidenceRootError(
            f"{raw!r} is not a client identifier; a path separator or '..' in one names "
            f"a different tenant's prefix once normalised, so it is refused rather than "
            f"quietly reinterpreted"
        )

    tenant = slugify(raw)
    if not tenant:
        raise EvidenceRootError(f"{client!r} does not name a tenant")

    base = Path(root)
    if not base.is_dir():
        raise EvidenceRootError(f"the evidence root is not a directory: {base}")

    resolved_root = base.resolve(strict=True)
    candidate = (resolved_root / tenant).resolve(strict=False)

    # Compared after resolution, so a symlink inside one tenant's tree pointing
    # at another's is refused along with a textual traversal.
    if candidate != resolved_root / tenant:
        raise EvidenceRootError(
            f"the evidence prefix for {tenant!r} resolves outside its own directory"
        )
    if not candidate.is_dir():
        raise EvidenceRootError(f"no evidence prefix for {tenant!r} under {base}")

    files = [p for p in candidate.rglob("*") if p.is_file()]
    if not files:
        raise EvidenceRootError(
            f"the evidence prefix for {tenant!r} is empty; refusing to assess nothing, "
            f"because every control would read as a gap and that is a delivery problem "
            f"rather than a client result"
        )

    return EvidencePrefix(
        tenant_id=tenant, root=resolved_root, path=candidate, file_count=len(files)
    )


def stage_evidence(root: Path | str, client: str, destination: Path | str) -> EvidencePrefix:
    """Copy a tenant's evidence into a working directory. Returns what was staged.

    Copied rather than read in place so a run cannot modify what is on the
    volume, and so the working directory is the same shape whatever the source.
    Anything that resolves outside the tenant's prefix is skipped and named.
    """
    prefix = resolve_prefix(root, client)
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)

    staged = 0
    for source in sorted(prefix.path.rglob("*")):
        if not source.is_file():
            continue
        resolved = source.resolve(strict=False)
        if not resolved.is_relative_to(prefix.path):
            # A symlink out of the tenant's prefix. Skipped, not followed.
            continue
        relative = source.relative_to(prefix.path)
        landing = target / relative
        landing.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, landing)
        staged += 1

    if not staged:
        raise EvidenceRootError(
            f"nothing was staged for {prefix.tenant_id!r}: every item under its prefix "
            f"resolved outside it"
        )

    return EvidencePrefix(
        tenant_id=prefix.tenant_id, root=prefix.root, path=prefix.path, file_count=staged
    )
