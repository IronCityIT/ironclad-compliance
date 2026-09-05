#!/usr/bin/env python3
"""Report generation — CLI wrapper.

Renders the HTML report from a stored assessment, and a PDF alongside it when
WeasyPrint is installed. Rendering itself is stdlib-only, so a missing PDF
toolchain degrades the deliverable rather than failing the run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ironclad.cli import _StoredResult  # noqa: E402
from ironclad.report.render import render_html  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a compliance assessment report.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True, help="output path; .pdf is attempted, .html always written")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--client-name", default="")
    parser.add_argument("--framework", default="", help="accepted for compatibility; unused")
    args = parser.parse_args(argv)

    document = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _StoredResult(document)
    html = render_html(result, args.client_name or args.client_id)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    html_path = output.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    print(f"report written: {html_path}")

    if output.suffix.lower() == ".pdf":
        try:
            from weasyprint import HTML  # noqa: PLC0415 — optional dependency

            HTML(string=html).write_pdf(str(output))
            print(f"PDF written: {output}")
        except ImportError:
            print("PDF toolchain not installed; the HTML report above is the deliverable")
        except Exception as exc:  # noqa: BLE001 — a PDF fault must not lose the report
            print(f"PDF rendering failed ({exc}); the HTML report above is the deliverable")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
