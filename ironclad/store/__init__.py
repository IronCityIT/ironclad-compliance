"""Where a finished assessment goes.

The engine has always known how to produce a result and never where to put it.
`scripts/store_results.py` POSTed to a Cloud Function that wrote Firestore, and
that path is being retired: persistent state moves to NAS-backed MariaDB, with
artifact files on a NAS volume.

This package is the seam. `rows.py` flattens a result document into tenant-scoped
records with no opinion about storage; the stores write those records. Building
the seam first is what makes the transport decision reversible — a self-hosted
runner writing MariaDB directly, an authenticated ingest in front of it, or a
loader run beside the database all consume the same rows.
"""

from ironclad.store.base import ResultStore, StoreError
from ironclad.store.factory import store_from_target, target_summary
from ironclad.store.files import FileResultStore
from ironclad.store.rows import BOUNDS, TABLES, RowSet, rows_from_document

__all__ = [
    "BOUNDS",
    "TABLES",
    "FileResultStore",
    "ResultStore",
    "RowSet",
    "StoreError",
    "rows_from_document",
    "store_from_target",
    "target_summary",
]
