"""Text extraction from evidence files.

Re-housed from the original scripts/assess_controls.py, with the behaviour that
mattered kept and the parts that hid problems fixed:

  * the original swallowed every extraction failure into a bare except and
    returned a placeholder string, so a corrupt PDF looked exactly like a PDF
    with no relevant content. Failures are now reported to the caller.
  * the original truncated at 5000 characters for every format. That cap exists
    to bound memory across a large evidence set, so it stays, but it is now a
    named constant and the truncation is recorded rather than silent.

Binary format support is optional. An engine that cannot read a PDF should say
so on that one artifact and keep assessing the rest, not fail the run.

The PDF reader prefers `pypdf` over `PyPDF2`. PyPDF2 announces its own
deprecation on import and no longer receives fixes, and this parser is pointed
at documents a client uploads. Both expose the same `PdfReader`, so preferring
the maintained one costs nothing and the superseded one still works as a
fallback.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Bounds memory across a large evidence set. Control matching keys on evidence
# type and section headings, which sit near the top of a policy document, so the
# cap costs little recall.
MAX_CHARS = 20_000
MAX_PDF_PAGES = 20
MAX_SHEETS = 5
MAX_SHEET_ROWS = 200

# What an evidence file may cost to open. Both formats built on a zip — .docx
# and .xlsx — are parsed in full by their libraries before the first character
# comes back, so the clip above does nothing for memory: a 0.57 MB .docx whose
# document.xml expands to 143 MB took 19 s and 545 MB to yield 20,000
# characters (PRODUCTIZE_NOTES §16.22). The zip's own table of contents says
# what each member expands to, so the answer is known before anything is
# inflated. A member over the cap, or a file over the cap, is reported as too
# large to read safely and catalogued without text, like any other unreadable.
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 50 * 1024 * 1024

TEXT_SUFFIXES = frozenset({".txt", ".md", ".csv", ".json", ".log", ".yaml", ".yml", ".html"})


@dataclass
class Extraction:
    """What came out of one file, and whether anything went wrong getting it."""

    text: str = ""
    truncated: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def supported_extensions() -> list[str]:
    """Every suffix the extractor will attempt, for the ingestion docs and UI."""
    return sorted(TEXT_SUFFIXES | {".pdf", ".docx", ".xlsx", ".xls"})


def _clip(text: str) -> Extraction:
    if len(text) > MAX_CHARS:
        return Extraction(text=text[:MAX_CHARS], truncated=True)
    return Extraction(text=text)


def _pdf_reader() -> Any:
    """The PDF reader class, preferring the maintained library.

    `pypdf` is the continuation of `PyPDF2`, which announces its own deprecation
    on import and no longer receives fixes. This parser is pointed at documents
    a client uploads, so running the unmaintained one when the maintained one is
    installed would be a choice worth defending and there is no defence. Both
    expose `PdfReader` with the same signature, so preferring one costs nothing.
    """
    try:
        from pypdf import PdfReader as Maintained  # noqa: PLC0415 — optional dependency
    except ImportError:
        pass
    else:
        return Maintained

    from PyPDF2 import PdfReader as Superseded  # noqa: PLC0415 — the fallback

    return Superseded


def _extract_pdf(path: Path) -> Extraction:
    try:
        reader_class = _pdf_reader()
    except ImportError:
        return Extraction(error="PDF support is not installed (pypdf, or PyPDF2)")

    try:
        with path.open("rb") as handle:
            reader = reader_class(handle)
            pages = [(page.extract_text() or "") for page in reader.pages[:MAX_PDF_PAGES]]
        return _clip("\n".join(pages))
    except Exception as exc:  # noqa: BLE001 — any parser fault is reported, not raised
        return Extraction(error=f"could not read PDF: {exc}")


def _too_large_to_inflate(path: Path) -> str:
    """Why a zip-based document should not be opened, or "" if it may be.

    Read from the central directory, which costs nothing: the declared
    uncompressed size of each member. A member that expands past the cap is
    refused before a byte of it is inflated.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.file_size > MAX_ZIP_MEMBER_BYTES:
                    return (
                        f"{member.filename} expands to {member.file_size // (1024 * 1024)} MB, "
                        f"over the {MAX_ZIP_MEMBER_BYTES // (1024 * 1024)} MB a document "
                        f"may expand to; too large to read safely"
                    )
    except (zipfile.BadZipFile, OSError):
        # Not a zip at all: the format parser will say so in its own words.
        return ""
    return ""


def _too_large(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size > MAX_FILE_BYTES:
        return f"{size // (1024 * 1024)} MB is over the {MAX_FILE_BYTES // (1024 * 1024)} MB an evidence file may be; too large to read safely"
    return ""


def _extract_docx(path: Path) -> Extraction:
    try:
        from docx import Document  # noqa: PLC0415 — optional dependency
    except ImportError:
        return Extraction(error="DOCX support is not installed (python-docx)")
    if reason := _too_large_to_inflate(path):
        return Extraction(error=f"could not read DOCX: {reason}")

    try:
        document = Document(str(path))
        parts = [p.text for p in document.paragraphs]
        # Control evidence often lives in tables (access matrices, review logs),
        # which the original extractor skipped entirely.
        for table in document.tables:
            for row in table.rows:
                parts.append(" ".join(cell.text for cell in row.cells))
        return _clip("\n".join(parts))
    except Exception as exc:  # noqa: BLE001
        return Extraction(error=f"could not read DOCX: {exc}")


def _extract_xlsx(path: Path) -> Extraction:
    try:
        import openpyxl  # noqa: PLC0415 — optional dependency
    except ImportError:
        return Extraction(error="spreadsheet support is not installed (openpyxl)")
    # read_only streams the rows, but the shared-strings table is loaded whole.
    if reason := _too_large_to_inflate(path):
        return Extraction(error=f"could not read spreadsheet: {reason}")

    try:
        workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        lines: list[str] = []
        for sheet in workbook.worksheets[:MAX_SHEETS]:
            lines.append(str(sheet.title))
            for row in sheet.iter_rows(max_row=MAX_SHEET_ROWS, values_only=True):
                lines.append(" ".join(str(cell) for cell in row if cell is not None))
        workbook.close()
        return _clip("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        return Extraction(error=f"could not read spreadsheet: {exc}")


def _extract_text_file(path: Path) -> Extraction:
    # Only as much as the clip can use is read: a 62 MB text file was read
    # whole to keep 20,000 characters of it. Four bytes per character covers
    # any UTF-8 sequence, and a file with more is truncated by definition.
    try:
        with path.open("rb") as handle:
            head = handle.read(MAX_CHARS * 4 + 1)
    except OSError as exc:
        return Extraction(error=f"could not read file: {exc}")
    text = head.decode("utf-8", errors="replace")
    if len(head) > MAX_CHARS * 4:
        return Extraction(text=text[:MAX_CHARS], truncated=True)
    return _clip(text)


def extract_text(path: Path) -> Extraction:
    """Pull searchable text out of one evidence file.

    Never raises for an unreadable file — an assessment must not die because one
    artifact in a hundred is corrupt. The fault travels on the Extraction and
    ends up as a note on the affected control.
    """
    if not path.exists():
        return Extraction(error="file not found")
    if not path.is_file():
        return Extraction(error="not a file")

    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return _extract_text_file(path)
    if reason := _too_large(path):
        return Extraction(error=f"could not read {suffix}: {reason}")
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix in (".xlsx", ".xls"):
        return _extract_xlsx(path)
    return Extraction(error=f"unsupported evidence format {suffix or '(none)'}")
