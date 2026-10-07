"""The white-label rule, applied to text the engine did not write.

No underlying tool or model vendor is named on a surface a client sees. The
static surfaces — the renderer, the templates, the dashboard — are scanned by
`scripts/check_white_label.sh` on every gate. The one text the gates cannot
scan is what the AI stage sends back at run time: fifteen models' aggregated
remediation advice, stored on the record and shipped in the auditor package.
Nothing in the real output to date names a tool; nothing stops a model from
recommending one by name tomorrow.

`PATTERN` is the gate's pattern, kept identical by a test: one rule, two places
it must run.
"""

from __future__ import annotations

import re

# The same alternation `scripts/check_white_label.sh` greps for.
PATTERN = "zap|nuclei|wazuh|prowler|puppeteer|openai|anthropic|groq|gemini"

_NAMES = re.compile(rf"\b({PATTERN})\b", re.IGNORECASE)
REPLACEMENT = "a supported tool"


def redact(text: str) -> tuple[str, int]:
    """The text with any named tool replaced, and how many were."""
    redacted, count = _NAMES.subn(REPLACEMENT, text)
    return redacted, count
