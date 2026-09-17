#!/bin/sh
# No credential value lives in this repository, as one command every gate runs.
#
# Secrets are pulled by name from the organisation's store; a literal that looks
# like a credential — a key-ish name, an assignment, a long token-shaped string
# in quotes — is a hard failure, not a warning. This was inline shell in ci.yml,
# which meant the Jenkins pipeline did not run it at all; one script, three
# callers, one rule.
#
# POSIX sh, no bashisms — it runs under BusyBox on the NAS too.
set -eu

cd "$(dirname "$0")/.."

pattern='(api[_-]?key|secret|token|password|passwd|credential)[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9_/+=-]{12,}'

if grep -rEn "$pattern" \
     --include='*.py' --include='*.js' --include='*.yml' \
     --include='*.json' --include='Jenkinsfile' \
     --exclude-dir=node_modules --exclude-dir=.git . ; then
  echo "a hardcoded credential literal is present" >&2
  exit 1
fi
echo "no hardcoded credential literals"
