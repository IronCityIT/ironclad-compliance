"""Single source of truth for the product version.

Bumped by hand. `pyproject.toml` carries the same string; `tests/test_version.py`
fails the build if the two ever drift, so a release cannot ship a version that
disagrees with its own package metadata.
"""

__version__ = "1.0.0"
