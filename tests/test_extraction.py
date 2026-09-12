"""Getting text out of a client's evidence files.

The highest-consequence code in the ingest path, and it was the least covered.
A policy document that fails to extract produces no matched terms, the control
it supports reads as a gap, and the client is told they do not meet a control
they do meet. The original extractor swallowed every failure into a bare except
and returned a placeholder, which made that outcome indistinguishable from a
document with nothing relevant in it (PRODUCTIZE_NOTES §2.4).

So the rule under test is not "extraction works". It is **a failure is always
reported as a failure** — never as an empty document, never as a raised
exception that ends the run, and never as a placeholder that reads like content.

The binary formats need optional dependencies. Where they are absent the tests
assert the *refusal* is well-formed, which is the branch that runs on a machine
without them, and skip the extraction itself. Both halves run in CI.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from ironclad.ingest.extractors import (
    MAX_CHARS,
    Extraction,
    extract_text,
    supported_extensions,
)

try:  # pragma: no cover — availability, not behaviour
    import pypdf  # noqa: F401

    HAS_PDF = True
except ImportError:  # pragma: no cover
    try:
        import PyPDF2  # noqa: F401

        HAS_PDF = True
    except ImportError:
        HAS_PDF = False

try:  # pragma: no cover
    import docx  # noqa: F401

    HAS_DOCX = True
except ImportError:  # pragma: no cover
    HAS_DOCX = False

try:  # pragma: no cover
    import openpyxl  # noqa: F401

    HAS_XLSX = True
except ImportError:  # pragma: no cover
    HAS_XLSX = False


PDF_TEXT = b"BT /F1 12 Tf 72 700 Td (Access control policy restricts logical access) Tj ET"


def minimal_pdf(content: bytes = PDF_TEXT) -> bytes:
    """A complete one-page PDF, built rather than written out.

    Built because a PDF needs a correct cross-reference table with real byte
    offsets and a %%EOF marker, and a hand-written literal that lacks them is
    not a valid PDF — it is a corrupt one, which tests the wrong branch. Built
    here rather than with a writer library so proving the reader works does not
    depend on a second dependency.
    """
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n%s\nendstream" % (len(content), content),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj" % number + obj + b"endobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n" % (len(objects) + 1))
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer<</Root 1 0 R/Size %d>>\n" % (len(objects) + 1))
    out.write(b"startxref\n%d\n%%%%EOF\n" % xref)
    return out.getvalue()


class TestWhatIsSupported:
    def test_the_advertised_formats_are_the_handled_ones(self) -> None:
        # The ingestion contract and the dashboard both publish this list, so a
        # format advertised and not handled is a client submitting evidence that
        # will silently produce nothing.
        advertised = set(supported_extensions())
        assert {".txt", ".md", ".csv", ".json", ".pdf", ".docx", ".xlsx"} <= advertised
        for suffix in advertised:
            assert suffix.startswith(".")


class TestAFailureIsAlwaysAFailure:
    """Never an empty document, never a raised exception, never a placeholder."""

    def test_a_missing_file_is_reported(self, tmp_path: Path) -> None:
        result = extract_text(tmp_path / "absent.pdf")
        assert not result.ok
        assert "not found" in result.error
        assert result.text == ""

    def test_a_directory_is_not_a_file(self, tmp_path: Path) -> None:
        result = extract_text(tmp_path)
        assert not result.ok
        assert "not a file" in result.error

    def test_an_unsupported_format_names_the_suffix(self, tmp_path: Path) -> None:
        path = tmp_path / "scan.pcap"
        path.write_bytes(b"\x00\x01")
        result = extract_text(path)
        assert not result.ok
        assert ".pcap" in result.error

    def test_a_file_with_no_suffix_is_refused_readably(self, tmp_path: Path) -> None:
        path = tmp_path / "policy"
        path.write_text("Access control policy.", encoding="utf-8")
        result = extract_text(path)
        assert not result.ok
        assert "(none)" in result.error

    @pytest.mark.parametrize("suffix", [".pdf", ".docx", ".xlsx"])
    def test_a_corrupt_binary_never_raises(self, tmp_path: Path, suffix: str) -> None:
        # The case the original swallowed: an assessment must not die because one
        # artifact in a hundred is corrupt, and must not call it empty either.
        path = tmp_path / f"evidence{suffix}"
        path.write_bytes(b"this is not a valid document at all")
        result = extract_text(path)
        assert isinstance(result, Extraction)
        assert not result.ok
        assert result.text == ""
        assert result.error

    @pytest.mark.parametrize("suffix", [".pdf", ".docx", ".xlsx"])
    def test_an_empty_binary_never_raises(self, tmp_path: Path, suffix: str) -> None:
        path = tmp_path / f"empty{suffix}"
        path.write_bytes(b"")
        result = extract_text(path)
        assert not result.ok
        assert result.error

    def test_a_truncated_zip_container_is_reported(self, tmp_path: Path) -> None:
        # DOCX and XLSX are zip files. A truncated upload is a realistic fault
        # and reads as a valid-looking file right up to the parser.
        path = tmp_path / "review.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", "<not-really-a-document/>")
        result = extract_text(path)
        assert not result.ok
        assert result.error

    def test_the_refusal_names_the_missing_dependency(self, tmp_path: Path, monkeypatch) -> None:
        # An engine without PDF support must say which support is missing, not
        # report the client's PDF as empty.
        import builtins

        real_import = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name in ("pypdf", "PyPDF2"):
                raise ImportError(f"no {name} here")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse)
        path = tmp_path / "policy.pdf"
        path.write_bytes(minimal_pdf())
        result = extract_text(path)
        assert not result.ok
        assert "pypdf" in result.error


class TestThePdfReaderIsTheMaintainedOne:
    def test_pypdf_is_preferred_over_its_deprecated_predecessor(self, monkeypatch) -> None:
        # PyPDF2 announces its own deprecation on import and no longer receives
        # fixes. This parser reads documents a client uploads.
        from ironclad.ingest.extractors import _pdf_reader

        pytest.importorskip("pypdf")
        assert _pdf_reader().__module__.startswith("pypdf")

    def test_pypdf2_still_works_when_it_is_all_there_is(self, monkeypatch) -> None:
        import builtins

        pytest.importorskip("PyPDF2")
        real_import = builtins.__import__

        def no_pypdf(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_pypdf)
        from ironclad.ingest.extractors import _pdf_reader

        assert _pdf_reader().__module__.startswith("PyPDF2")


class TestTextFiles:
    def test_a_policy_reads_back(self, tmp_path: Path) -> None:
        path = tmp_path / "policy.txt"
        path.write_text("Access control policy. Restricts logical access.", encoding="utf-8")
        result = extract_text(path)
        assert result.ok
        assert "Restricts logical access" in result.text
        assert not result.truncated

    def test_a_long_document_is_clipped_and_says_so(self, tmp_path: Path) -> None:
        # The cap bounds memory across a large evidence set. Silent truncation
        # would be the same defect as everywhere else in this product.
        path = tmp_path / "long.md"
        path.write_text("x" * (MAX_CHARS + 500), encoding="utf-8")
        result = extract_text(path)
        assert result.ok
        assert result.truncated
        assert len(result.text) == MAX_CHARS

    def test_invalid_utf8_is_replaced_not_refused(self, tmp_path: Path) -> None:
        # A policy exported from a Windows tool is still evidence.
        path = tmp_path / "policy.txt"
        path.write_bytes(b"Access control policy \xff\xfe restricts logical access")
        result = extract_text(path)
        assert result.ok
        assert "restricts logical access" in result.text

    def test_an_empty_text_file_is_readable_and_empty(self, tmp_path: Path) -> None:
        # Distinct from a failure: nothing went wrong, there is just nothing there.
        path = tmp_path / "blank.txt"
        path.write_text("", encoding="utf-8")
        result = extract_text(path)
        assert result.ok
        assert result.text == ""


@pytest.mark.skipif(not HAS_PDF, reason="PyPDF2 is not installed")
class TestPdf:
    def test_text_comes_out_of_a_real_pdf(self, tmp_path: Path) -> None:
        path = tmp_path / "policy.pdf"
        path.write_bytes(minimal_pdf())
        result = extract_text(path)
        assert result.ok, result.error
        assert "logical access" in result.text.lower()

    def test_a_pdf_with_no_text_layer_is_empty_not_an_error(self, tmp_path: Path) -> None:
        # A scanned policy: valid PDF, no extractable text. Reporting it as an
        # error would be wrong — nothing failed — but the control it was meant to
        # support will read as unevidenced, which is the honest outcome.
        path = tmp_path / "scanned.pdf"
        path.write_bytes(minimal_pdf(b" " * len(PDF_TEXT)))
        result = extract_text(path)
        assert result.ok, result.error
        assert result.text.strip() == ""


@pytest.mark.skipif(not HAS_DOCX, reason="python-docx is not installed")
class TestDocx:
    def _document(self, path: Path, paragraphs: list[str], table: list[list[str]] | None = None):
        from docx import Document

        document = Document()
        for text in paragraphs:
            document.add_paragraph(text)
        if table:
            grid = document.add_table(rows=len(table), cols=len(table[0]))
            for row_index, row in enumerate(table):
                for cell_index, value in enumerate(row):
                    grid.cell(row_index, cell_index).text = value
        document.save(str(path))
        return path

    def test_paragraphs_come_out(self, tmp_path: Path) -> None:
        path = self._document(
            tmp_path / "policy.docx", ["Access Control Policy", "Restricts logical access."]
        )
        result = extract_text(path)
        assert result.ok, result.error
        assert "Restricts logical access." in result.text

    def test_tables_come_out_too(self, tmp_path: Path) -> None:
        # Control evidence often lives in tables — access matrices, review logs —
        # and the original extractor skipped them entirely, so a review recorded
        # as a table produced a gap.
        path = self._document(
            tmp_path / "review.docx",
            ["User Access Review"],
            [["User", "System", "Decision"], ["a.smith", "billing", "retain"]],
        )
        result = extract_text(path)
        assert result.ok, result.error
        assert "a.smith" in result.text
        assert "retain" in result.text

    def test_an_empty_document_is_readable(self, tmp_path: Path) -> None:
        path = self._document(tmp_path / "empty.docx", [])
        result = extract_text(path)
        assert result.ok, result.error


@pytest.mark.skipif(not HAS_XLSX, reason="openpyxl is not installed")
class TestSpreadsheets:
    def _workbook(self, path: Path, sheets: Mapping[str, Sequence[Sequence[object]]]):
        import openpyxl

        workbook = openpyxl.Workbook()
        workbook.remove(workbook.active)
        for title, rows in sheets.items():
            sheet = workbook.create_sheet(title=title)
            for row in rows:
                sheet.append(row)
        workbook.save(str(path))
        return path

    def test_cells_and_sheet_names_come_out(self, tmp_path: Path) -> None:
        path = self._workbook(
            tmp_path / "review.xlsx",
            {"Q3 Access Review": [["User", "Decision"], ["a.smith", "retain"]]},
        )
        result = extract_text(path)
        assert result.ok, result.error
        assert "Q3 Access Review" in result.text
        assert "a.smith" in result.text

    def test_empty_cells_do_not_become_the_word_none(self, tmp_path: Path) -> None:
        # "None" scattered through the text would match control terms by
        # accident and is not something the client wrote.
        path = self._workbook(
            tmp_path / "sparse.xlsx", {"Sheet1": [["User", None, "retain"], [None, None, None]]}
        )
        result = extract_text(path)
        assert result.ok, result.error
        assert "None" not in result.text

    def test_only_the_first_sheets_are_read(self, tmp_path: Path) -> None:
        from ironclad.ingest.extractors import MAX_SHEETS

        sheets = {f"Sheet{n}": [[f"marker{n}"]] for n in range(MAX_SHEETS + 3)}
        path = self._workbook(tmp_path / "many.xlsx", sheets)
        result = extract_text(path)
        assert result.ok, result.error
        assert f"marker{MAX_SHEETS + 2}" not in result.text
