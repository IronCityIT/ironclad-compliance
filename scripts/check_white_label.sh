#!/bin/sh
# The white-label rule, as one command every gate runs.
#
# No underlying tool or model vendor may be named on a surface a client sees:
# the report, the auditor package, the dashboard and anything served beside it,
# and the capability catalog. Internal code and comments may name them.
#
# This scans directories, not a list of files. The list it replaced named four
# files, so a fifth dropped into dashboard/public/ — a data file naming a SIEM
# product, served to every visitor — passed the gate without being read. A
# surface is a place, and every file in the place is on it.
#
# POSIX sh, no bashisms — it runs under BusyBox on the NAS too.
set -eu

cd "$(dirname "$0")/.."

pattern='zap|nuclei|wazuh|prowler|puppeteer|openai|anthropic|groq|gemini'
surfaces="ironclad/report templates dashboard/public"

if grep -rinE "$pattern" $surfaces; then
  echo "an underlying tool is named on a client-facing surface" >&2
  exit 1
fi
echo "no tool names on any client-facing surface"
