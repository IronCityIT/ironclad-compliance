"""Evidence ingestion: the manifest contract and the collectors behind it."""

from ironclad.ingest.collectors import collect_from_directory, collect_from_manifest
from ironclad.ingest.contract import (
    CONTRACT_VERSION,
    build_manifest,
    manifest_from_directory,
    validate_manifest,
)
from ironclad.ingest.extractors import extract_text, supported_extensions

__all__ = [
    "CONTRACT_VERSION",
    "build_manifest",
    "collect_from_directory",
    "collect_from_manifest",
    "extract_text",
    "manifest_from_directory",
    "supported_extensions",
    "validate_manifest",
]
