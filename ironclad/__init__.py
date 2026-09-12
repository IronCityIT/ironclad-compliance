"""Ironclad Compliance — the Iron City compliance evidence engine.

The package is layered so each concern has exactly one home:

    model/       the domain objects (control, evidence, assessment, remediation,
                 exception, audit, tenant) with no I/O
    frameworks/  framework loading, validation and cross-framework crosswalks
    ingest/      the evidence ingestion contract and the extractors behind it
    modules/     one assessment capability per file (the ICIT module pattern)
    registry.py  module discovery + selection; the one catalog the CLI and the
                 dashboard both render from
    engine.py    orchestration: selected modules -> a scored Assessment
    report/      HTML rendering and auditor exports
    api/         tenant-scoped service surface with RBAC enforcement
    cli.py       the CLI entry point and the JSON contract to the AI engine
"""

from ironclad.version import __version__

__all__ = ["__version__"]
