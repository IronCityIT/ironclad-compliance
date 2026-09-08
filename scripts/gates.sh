#!/bin/sh
# Every gate CI runs, in one command, so a local pass means the same thing.
#
# Written because it did not: a lint error reached CI after a local run that
# checked formatting and forgot `ruff check`. A gate you have to remember to
# invoke is a gate that gets forgotten under time pressure, which is exactly
# when it matters.
#
# POSIX sh, no bashisms — it has to run under BusyBox on the NAS too.
#
#   sh scripts/gates.sh          every gate that needs no service
#   sh scripts/gates.sh --all    those plus the ones that need node or MariaDB
set -eu

failed=""
run() {
  name="$1"
  shift
  printf '── %s\n' "$name"
  if "$@"; then
    printf '   passed\n'
  else
    printf '   FAILED\n'
    failed="$failed $name"
  fi
}

# A local pass and a CI pass mean the same thing only when the environment does.
# The extraction extras are in requirements-dev.txt and cannot be installed into
# an externally-managed Python (PEP 668), so on a machine without them both the
# binary-format tests and mypy's view of those imports differ from CI. Said out
# loud rather than left to be discovered from a red CI run — which is how it was
# discovered.
if python3 -c "import pypdf, docx, openpyxl" 2>/dev/null; then
  printf '── environment: matches CI (extraction extras present)\n'
else
  printf '── environment: NO extraction extras — the binary-format tests will\n'
  printf '   skip and mypy sees those imports as Any. A pass here is weaker\n'
  printf '   than a pass in CI. Use a venv to match:\n'
  printf '     python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt\n'
fi

run "format"    ruff format --check .
run "lint"      ruff check .
run "typecheck" mypy
run "test"      python3 -m pytest -q
run "artifacts" python3 scripts/validate_artifacts.py
run "catalog"   python3 tools/build_catalog.py --check

if [ "${1:-}" = "--all" ]; then
  if command -v npm >/dev/null 2>&1; then
    run "functions" npm --prefix functions test
    run "dashboard" npm --prefix dashboard test
  else
    printf '── functions, dashboard: SKIPPED, no npm on this machine\n'
  fi
  if [ -n "${IRONCLAD_TEST_DSN:-}" ]; then
    run "persistence" python3 -m pytest tests/test_store.py -q
  else
    printf '── persistence: SKIPPED, set IRONCLAD_TEST_DSN for a real MariaDB\n'
  fi
fi

if [ -n "$failed" ]; then
  printf '\ngates failed:%s\n' "$failed" >&2
  exit 1
fi
printf '\nall gates passed\n'
