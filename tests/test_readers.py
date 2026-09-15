"""
Summary: Tests for the document readers: the text a Word, OpenDocument,
and RTF file each produce, with headings, lists, and tables kept; the
refusals for a binary .doc, a file of no known format, an unreadable
archive, a document type declaration, and an archive entry over its
ceiling; the title rule; the content node the chunker cuts at; and the
address rules that decide which links count as documents. Every file
is built in memory by tests/document_fixtures.py.

This file is part of Extractium™
tests/test_readers.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-15
Last Modified: 2026-09-15
Notes: See README file for documentation and full license information.
"""

# Copyright © 2026 The Regents of the University of Michigan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.

__author__ = "Gabriel Mongefranco, University of Michigan."
__copyright__ = "Copyright (C) 2026 The Regents of the University of Michigan"
__license__ = "GPLv3 or later"
__date__ = "2026-09-15"

import io
import zipfile

import pytest

from extractium.core import chunk
from extractium.core.models import Document
from extractium.readers import documents, isolated, office
from tests import document_fixtures as files


# ---------------------------------------------------------------------------
# What each format reads as
# ---------------------------------------------------------------------------

def test_a_word_file_reads_as_text_with_its_headings_lists_and_tables():
    assert documents.read_document(files.SAMPLE_DOCX, "plan.docx").text == files.SAMPLE_DOCX_MARKDOWN


def test_an_opendocument_file_reads_the_same_way():
    assert documents.read_document(files.SAMPLE_ODT, "plan.odt").text == files.SAMPLE_ODT_MARKDOWN


def test_an_rtf_file_keeps_text_runs_escapes_and_field_results_only():
    """
    The font table, the color table, the generator, the document
    information, a bookmark, and a field's instruction are all dropped;
    the field's visible result, a code-page escape, and a unicode escape
    with its fallback character are all read.
    """
    assert documents.read_document(files.SAMPLE_RTF, "plan.rtf").text == files.SAMPLE_RTF_MARKDOWN


def test_the_format_is_decided_from_the_bytes_and_not_the_name():
    assert documents.read_document(files.SAMPLE_RTF, "misnamed.docx").text == files.SAMPLE_RTF_MARKDOWN
    assert documents.read_document(files.SAMPLE_DOCX, "misnamed.rtf").text == files.SAMPLE_DOCX_MARKDOWN


def test_a_word_outline_level_marks_a_heading_when_the_style_does_not():
    body = (
        '<w:p><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:r><w:t>Section</w:t></w:r></w:p>'
        + files.word_paragraph("Body text.")
    )
    assert documents.read_document(files.make_docx(body)).text == "## Section\n\nBody text.\n"


def test_word_tabs_breaks_deleted_text_and_fallback_content_are_handled():
    body = (
        "<w:p><w:r><w:t>Left</w:t><w:tab/><w:t>Right</w:t><w:br/><w:t>Next</w:t></w:r>"
        "<w:del><w:r><w:delText>gone</w:delText></w:r></w:del>"
        "<mc:AlternateContent><mc:Choice><w:r><w:t> kept</w:t></w:r></mc:Choice>"
        "<mc:Fallback><w:r><w:t> dropped</w:t></w:r></mc:Fallback></mc:AlternateContent></w:p>"
    )
    assert documents.read_document(files.make_docx(body)).text == "Left\tRight\nNext kept\n"


def test_a_word_file_with_no_text_reads_as_empty():
    assert documents.read_document(files.make_docx(files.word_paragraph("   "))).text == ""


def test_markup_in_a_document_is_indexed_as_the_words_written():
    """A tag inside a document is text to index, never HTML to parse."""
    body = files.word_paragraph("Use <b>bold</b> & #1 priority")
    text = documents.read_document(files.make_docx(body)).text
    node = documents.content_node(text)
    assert node.find("b") is None
    assert node.get_text() == "Use <b>bold</b> & #1 priority"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_the_binary_word_format_is_refused_by_name():
    with pytest.raises(documents.DocumentError, match=r"binary \.doc format is not read"):
        documents.read_document(files.OLE_HEADER, "old.doc")


def test_a_file_of_no_known_format_is_refused():
    with pytest.raises(documents.DocumentError, match="not a Word, OpenDocument, RTF, or PDF file"):
        documents.read_document(b"just some bytes", "x.docx")


def test_an_unreadable_archive_is_refused():
    with pytest.raises(documents.DocumentError, match="not a readable archive"):
        documents.read_document(documents.ZIP_MAGIC + b"not really a zip", "x.docx")


def test_an_archive_that_is_neither_format_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.txt", "an ordinary zip")
    with pytest.raises(documents.DocumentError, match="neither a Word nor an OpenDocument"):
        documents.read_document(buffer.getvalue(), "x.docx")


def test_an_opendocument_spreadsheet_is_refused_as_the_wrong_kind():
    data = files.make_odt("<text:p>cells</text:p>", mimetype="application/vnd.oasis.opendocument.spreadsheet")
    with pytest.raises(documents.DocumentError, match="only text documents are read"):
        documents.read_document(data, "x.ods")


@pytest.mark.parametrize("declaration", [
    '<!DOCTYPE w:document [<!ENTITY e "boom">]>',
    '<!DOCTYPE w:document SYSTEM "file:///etc/passwd">',
    '<!doctype x>',
])
def test_a_document_type_declaration_is_refused_before_parsing(declaration):
    """
    An entity expansion and an external entity both need a declaration,
    so refusing every declaration closes both without a special parser.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?>{declaration}<w:document xmlns:w="{files.W_NS}">'
            "<w:body><w:p><w:r><w:t>&e;</w:t></w:r></w:p></w:body></w:document>",
        )
    with pytest.raises(documents.DocumentError, match="document type declaration"):
        documents.read_document(buffer.getvalue(), "x.docx")


def test_an_archive_entry_over_the_ceiling_is_refused_by_its_declared_size(monkeypatch):
    monkeypatch.setattr(office, "MAX_PART_BYTES", 1_000)
    body = files.word_paragraph("x" * 2_000)
    with pytest.raises(documents.DocumentError, match="over the 1000 byte ceiling"):
        documents.read_document(files.make_docx(body), "x.docx")


def test_an_archive_entry_over_the_ceiling_is_refused_by_its_real_size_too(monkeypatch):
    """A declared size can lie, so the bytes are counted as they unpack."""
    monkeypatch.setattr(office, "MAX_PART_BYTES", 1_000)
    data = files.make_docx(files.word_paragraph("x" * 2_000))
    lying = zipfile.ZipFile(io.BytesIO(data))
    info = lying.getinfo("word/document.xml")
    info.file_size = 10   # what the header claims
    with pytest.raises(documents.DocumentError, match="ceiling|could not be read"):
        office._raw_part(lying, "word/document.xml")


def test_a_file_over_the_document_ceiling_is_refused_before_it_is_opened(monkeypatch):
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", 100)
    with pytest.raises(documents.DocumentError, match="over the 100 byte ceiling"):
        documents.read_document(files.SAMPLE_DOCX, "x.docx")


def test_malformed_xml_is_refused_with_the_part_named():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><w:body>")
    with pytest.raises(documents.DocumentError, match="word/document.xml is not well-formed"):
        documents.read_document(buffer.getvalue(), "x.docx")


def test_unbalanced_rtf_groups_are_refused():
    with pytest.raises(documents.DocumentError, match="groups do not balance"):
        documents.read_document(b"{\\rtf1 text}}", "x.rtf")


# ---------------------------------------------------------------------------
# Title, content node, and address rules
# ---------------------------------------------------------------------------

def read(text, **properties):
    """A ReadDocument with the given text and properties, as a reader would return it."""
    return documents.ReadDocument(text=text, properties=properties)


def test_the_title_is_the_first_heading_else_the_properties_title_else_a_short_first_line_else_the_fallback():
    heading_and_property = read(files.SAMPLE_DOCX_MARKDOWN, title="Properties Title")
    assert documents.document_title(heading_and_property, "plan") == "Youth Mental Health Resources"
    short_line = "A short opening line\n\nMore text.\n"
    assert documents.document_title(read(short_line, title="Properties Title"), "plan") == "Properties Title"
    # A PDF made from a Word file often declares the Word file's name.
    assert documents.document_title(read(short_line, title="Sample Plan.docx"), "plan") == "Sample Plan"
    assert documents.document_title(read(short_line, title=" .PDF "), "plan") == "A short opening line"
    assert documents.document_title(read(short_line), "plan") == "A short opening line"
    assert documents.document_title(read(("word " * 40).strip() + "\n\nMore.\n"), "plan") == "plan"
    assert documents.document_title(read("| a | b |\n|---|---|\n"), "plan") == "plan"
    assert documents.document_title(read(""), "plan") == "plan"
    assert documents.document_title(read("# Fish &amp; Chips\n"), "plan") == "Fish & Chips"


# ---------------------------------------------------------------------------
# File properties
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("data", [files.SAMPLE_DOCX, files.SAMPLE_ODT, files.SAMPLE_RTF])
def test_every_format_reads_the_title_subject_keywords_and_description_it_declares(data):
    assert documents.read_document(data).properties == files.SAMPLE_PROPERTIES


def test_the_properties_open_the_indexed_text_and_the_title_is_left_out():
    """
    The subject, keywords, and description are what a person wrote to
    say what the file is about, so they are indexed with it, and they
    are all that survives when a long file is reduced to its outline.
    """
    read_document = documents.read_document(files.SAMPLE_DOCX)

    assert read_document.indexed_text == files.SAMPLE_PROPERTIES_PARAGRAPH + "\n" + files.SAMPLE_DOCX_MARKDOWN
    assert "Properties Title" not in read_document.indexed_text


def test_blank_properties_are_the_same_as_none():
    data = files.make_docx(files.word_paragraph("Body only."), properties={"title": "  ", "keywords": ""})
    read_document = documents.read_document(data)
    assert read_document.properties == {}
    assert read_document.indexed_text == "Body only.\n"


def test_a_file_without_a_properties_part_has_none():
    assert documents.read_document(files.make_docx(files.word_paragraph("Body."))).properties == {}
    assert documents.read_document(files.make_odt("<text:p>Body.</text:p>")).properties == {}


def test_a_document_type_declaration_in_the_properties_part_is_refused_too():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{files.W_NS}"><w:body/></w:document>')
        archive.writestr("docProps/core.xml", '<!DOCTYPE x [<!ENTITY e "boom">]><cp:coreProperties xmlns:cp="x"/>')
    with pytest.raises(documents.DocumentError, match="docProps/core.xml carries a document type declaration"):
        documents.read_document(buffer.getvalue())


def test_the_content_node_cuts_at_the_headings_the_reader_kept():
    node = documents.content_node(files.SAMPLE_DOCX_MARKDOWN)
    document = Document(
        url="https://example.org/files/plan.docx", title="Youth Mental Health Resources",
        content=node, source_type="web", content_type="text",
    )

    parents, _ = chunk.chunk_document(document)

    assert [parent["t"] for parent in parents] == [
        "Youth Mental Health Resources",
        "Youth Mental Health Resources -- Middle School",
        "Youth Mental Health Resources -- High School",
    ]
    assert "Breathing exercise video" in parents[1]["x"]
    assert "Feelings 2" in parents[1]["x"]


@pytest.mark.parametrize("url, expected", [
    ("https://example.org/files/plan.docx", True),
    ("https://example.org/files/plan.DOCX?dl", True),
    ("https://example.org/files/plan.odt#top", True),
    ("https://example.org/files/plan.rtf", True),
    ("https://example.org/files/report.pdf", True),
    ("https://cdn.example.org/files/p/prod/0a1b2c.pdf/annual-report", True),
    ("https://cdn.example.org/files/p/prod/0a1b2c.docx/youth-resources", True),
    ("https://cdn.example.org/files/p/prod/0a1b2c.docx/youth-resources.docx?dl", True),
    ("https://example.org/files/plan.doc", False),
    ("https://example.org/files/plan.docx/deeper/path", False),
    ("https://example.org/docx/index.html", False),
    ("https://example.org/page", False),
])
def test_which_addresses_count_as_documents(url, expected):
    assert documents.is_document_url(url) is expected


def test_which_file_names_count_as_documents():
    assert documents.is_document_path("notes/plan.docx") is True
    assert documents.is_document_path("notes/PLAN.RTF") is True
    assert documents.is_document_path("notes/report.pdf") is True
    assert documents.is_document_path("notes/old.doc") is True    # recognised, then refused by the reader
    assert documents.is_document_path("notes/plan.md") is False
    assert documents.is_document_path("notes/plan") is False


def test_a_name_is_taken_from_the_address_for_a_file_that_declares_none():
    assert documents.name_from_url("https://cdn.example.org/files/p/0a1b.docx/youth-resources") == "Youth Resources"
    assert documents.name_from_url("https://example.org/files/ethics-consent_form.docx?dl") == "Ethics Consent Form"
    assert documents.name_from_url("https://example.org/") == "Document"


def test_the_name_the_server_gave_wins_over_the_address():
    url = "https://teamdynamix.example.edu/TDClient/210/Org/Shared/FileOpen?AttachmentID=abc"

    assert documents.name_from_url(url) == "Fileopen"
    assert documents.name_from_url(url, "Sample Data manager Job Description.pdf") == "Sample Data Manager Job Description"
    assert documents.name_from_url(url, "C:\\Users\\someone\\ethics_form.docx") == "Ethics Form"
    assert documents.name_from_url(url, "   ") == "Fileopen"


# ---------------------------------------------------------------------------
# PDF files
# ---------------------------------------------------------------------------

@pytest.fixture
def pypdf_installed():
    """Skips a test when the optional pdf extra is not installed."""
    pytest.importorskip("pypdf")


def test_a_pdf_reads_page_by_page_with_a_heading_per_page(pypdf_installed):
    read = documents.read_document(files.SAMPLE_PDF, "plan.pdf")

    assert read.text == files.SAMPLE_PDF_MARKDOWN
    assert read.properties == {
        "title": "Properties Title",
        "subject": "Classroom mental health resources",
        "keywords": "depression, anxiety, classroom",
    }
    assert read.indexed_text.startswith(files.SAMPLE_PDF_PROPERTIES_PARAGRAPH)


def test_a_pdf_with_bookmarks_takes_its_headings_from_them(pypdf_installed):
    assert documents.read_document(files.OUTLINED_PDF, "manual.pdf").text == files.OUTLINED_PDF_MARKDOWN


def test_a_single_page_pdf_gets_no_page_heading(pypdf_installed):
    assert documents.read_document(files.SINGLE_PAGE_PDF, "one.pdf").text == "Only page.\n"


def test_a_pdf_title_comes_from_its_properties_or_its_first_line_and_never_from_a_page_heading(
    pypdf_installed,
):
    """
    The headings in a PDF's text were made by the reader from page
    numbers and bookmarks, so "Page 1" must never become a title.
    """
    with_properties = documents.read_document(files.SAMPLE_PDF, "plan.pdf")
    without = documents.read_document(files.OUTLINED_PDF, "manual.pdf")
    bare = documents.read_document(
        files.make_pdf([[["First line.", "A wrapped second line of the same block."]], ["More."]]),
        "bare.pdf",
    )

    assert documents.document_title(with_properties, "plan") == "Properties Title"
    assert documents.document_title(without, "manual") == "Cover text."
    assert documents.document_title(bare, "bare") == "First line."
    assert documents.document_title(
        documents.ReadDocument(text="## Page 1\n\n" + "x" * 200 + "\n", properties={}, headings_are_titles=False),
        "fallback",
    ) == "fallback"


def test_a_pdf_holding_no_text_is_reported_as_likely_scanned(pypdf_installed):
    with pytest.raises(documents.DocumentError, match="holds no text; it is likely scanned images"):
        documents.read_document(files.EMPTY_PAGE_PDF, "scan.pdf")


def test_an_encrypted_pdf_is_refused(pypdf_installed):
    with pytest.raises(documents.DocumentError, match="encrypted files are not read"):
        documents.read_document(files.ENCRYPTED_PDF, "locked.pdf")


def test_a_truncated_pdf_is_refused_with_the_reason(pypdf_installed):
    with pytest.raises(documents.DocumentError, match="the PDF could not be read"):
        documents.read_document(files.TRUNCATED_PDF, "cut.pdf")


def test_a_pdf_header_after_a_few_bytes_of_junk_is_still_read(pypdf_installed):
    assert documents.read_document(files.JUNK_PREFIX_PDF, "odd.pdf").text == "Hello\n"


def test_pages_past_the_ceiling_are_not_read_and_the_text_says_so(pypdf_installed, monkeypatch):
    from extractium.readers import pdf

    monkeypatch.setattr(pdf, "MAX_PDF_PAGES", 1)
    blocks, _ = pdf.read_pdf(files.SAMPLE_PDF)

    assert [block.text for block in blocks] == [
        "Page 1",
        "Youth Mental Health Resources",
        f"for Middle School {files.BODY}",
        "Only the first 1 of 2 pages were read.",
    ]


def test_extracted_text_is_cleaned_of_odd_spacing_and_replacement_characters(pypdf_installed):
    """
    A font with no usable encoding yields a replacement character per
    glyph, and some writers put a non-breaking space between every
    word; neither is anything a person searches for.
    """
    from extractium.readers import pdf

    text = "\ufffd\xa0Book\xa0of\xa0Poems\xa0\ufffd\n \xa0\n Peer2Peer\xa0Project\n\nSecond.\n"
    assert list(pdf._paragraphs(text, first_line_alone=True)) == [
        "Book of Poems", "Peer2Peer Project", "Second.",
    ]


def test_a_pdf_is_refused_with_an_install_hint_when_the_reader_is_missing(monkeypatch):
    real = documents.importlib.util.find_spec
    monkeypatch.setattr(
        documents.importlib.util, "find_spec",
        lambda name, *args: None if name == "pypdf" else real(name, *args),
    )
    with pytest.raises(documents.DocumentError, match=r'pip install "extractium\[pdf\]"'):
        documents.read_document(files.SAMPLE_PDF, "plan.pdf")


# ---------------------------------------------------------------------------
# The reader's child process
# ---------------------------------------------------------------------------

def test_a_reader_that_runs_too_long_is_ended_and_the_next_call_gets_a_fresh_child():
    with pytest.raises(isolated.IsolationError, match="gave up after 0.5 seconds"):
        isolated.run("tests.document_fixtures", "sleep_reader", (b"",), timeout=0.5)

    assert isolated.run("builtins", "len", ("abc",)) == 3


def test_a_child_that_dies_is_reported_and_replaced():
    with pytest.raises(isolated.IsolationError, match="stopped unexpectedly"):
        isolated.run("tests.document_fixtures", "crash_reader", (b"",), timeout=30)

    assert isolated.run("builtins", "len", ("abcd",)) == 4


def test_an_error_in_the_child_arrives_as_its_type_and_message_and_nothing_else():
    with pytest.raises(isolated.RemoteError) as raised:
        isolated.run("builtins", "int", ("not a number",))

    assert raised.value.type_name == "ValueError"
    assert "not a number" in raised.value.message
    assert "Traceback" not in str(raised.value)


def test_a_pdf_readers_refusal_reaches_the_caller_under_its_own_message(pypdf_installed):
    """A DocumentError raised in the child is a DocumentError here, word for word."""
    with pytest.raises(documents.DocumentError) as raised:
        documents.read_document(files.ENCRYPTED_PDF, "locked.pdf")

    assert str(raised.value) == "the PDF is encrypted; encrypted files are not read"


def test_shutting_the_child_down_is_safe_to_repeat():
    isolated.shutdown()
    isolated.shutdown()

    assert isolated.run("builtins", "len", ("ab",)) == 2
