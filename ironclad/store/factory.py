"""Choose a store from a target string.

One place decides which backend a target names, so the CLI, the workflow and any
future service all resolve `--to` identically and the transport decision is one
string rather than a code path.

    file:///srv/ironclad          a NAS-backed volume
    /srv/ironclad                 the same, written the way a person writes it
    mysql://user:pw@host/db       MariaDB
    mariadb://user:pw@host/db     the same

A target is never guessed at: an unrecognised scheme is refused rather than
treated as a path, because silently writing a client's assessment to a directory
called `https:` is worse than failing.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from ironclad.store.base import StoreError
from ironclad.store.files import FileResultStore

FILE_SCHEMES = ("file", "")
SQL_SCHEMES = ("mysql", "mariadb")


def store_from_target(target: str) -> Any:
    """The store a target string names."""
    value = (target or "").strip()
    if not value:
        raise StoreError("no store target was given")

    scheme = urllib.parse.urlparse(value).scheme.lower()

    if scheme in SQL_SCHEMES:
        from ironclad.store.mariadb import MariaDBResultStore  # noqa: PLC0415

        return MariaDBResultStore(value)

    if scheme in FILE_SCHEMES:
        if scheme == "file":
            path = urllib.parse.urlparse(value).path
            if not path:
                raise StoreError(f"{value!r} names no path")
            return FileResultStore(Path(path))
        # A bare path. On Windows a drive letter parses as a scheme, which is
        # why single-character schemes are treated as paths rather than refused.
        return FileResultStore(Path(value))

    if len(scheme) == 1:
        return FileResultStore(Path(value))

    raise StoreError(
        f"{scheme}:// is not a store this product writes to; "
        f"use file:// for a NAS volume or mysql:// for MariaDB"
    )


def target_summary(target: str) -> str:
    """The target with any password removed, safe to print."""
    scheme = urllib.parse.urlparse((target or "").strip()).scheme.lower()
    if scheme in SQL_SCHEMES:
        from ironclad.store.mariadb import dsn_summary  # noqa: PLC0415

        return dsn_summary(target)
    return target
