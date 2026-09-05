from pathlib import Path

import pytest

from ingestion.extract import (
    EMPTY_DOCUMENT_MESSAGE,
    CorruptedDocumentError,
    EmptyDocumentError,
    _clean_text,
    extract_and_clean,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_pdf_happy_path_per_page():
    units = extract_and_clean(str(FIXTURES / "sample.pdf"), "pdf")
    assert len(units) == 2
    assert units[0].page == 1
    assert "Quarterly revenue" in units[0].text
    assert units[1].page == 2
    assert "Customer satisfaction" in units[1].text


def test_docx_happy_path():
    units = extract_and_clean(str(FIXTURES / "sample.docx"), "docx")
    assert len(units) == 1
    assert units[0].page is None
    assert "short sample paragraph" in units[0].text


def test_txt_happy_path():
    units = extract_and_clean(str(FIXTURES / "sample.txt"), "txt")
    assert len(units) == 1
    assert units[0].page is None
    assert "short sample sentence" in units[0].text


def test_md_happy_path():
    units = extract_and_clean(str(FIXTURES / "sample.md"), "md")
    assert len(units) == 1
    assert units[0].page is None
    assert "Sample Heading" in units[0].text


def test_blank_pdf_raises_empty_document_error():
    with pytest.raises(EmptyDocumentError) as exc_info:
        extract_and_clean(str(FIXTURES / "blank_no_text.pdf"), "pdf")
    assert str(exc_info.value) == EMPTY_DOCUMENT_MESSAGE


def test_empty_md_raises_empty_document_error():
    with pytest.raises(EmptyDocumentError) as exc_info:
        extract_and_clean(str(FIXTURES / "empty.md"), "md")
    assert str(exc_info.value) == EMPTY_DOCUMENT_MESSAGE


def test_corrupted_pdf_raises_corrupted_document_error():
    with pytest.raises(CorruptedDocumentError):
        extract_and_clean(str(FIXTURES / "corrupted.pdf"), "pdf")


def test_corrupted_docx_raises_corrupted_document_error():
    with pytest.raises(CorruptedDocumentError):
        extract_and_clean(str(FIXTURES / "corrupted.docx"), "docx")


def test_invalid_encoding_txt_raises_corrupted_document_error():
    with pytest.raises(CorruptedDocumentError):
        extract_and_clean(str(FIXTURES / "invalid_encoding.txt"), "txt")


def test_cleaning_is_idempotent():
    units = extract_and_clean(str(FIXTURES / "sample.txt"), "txt")
    once = units[0].text
    twice = _clean_text(once)
    assert once == twice


def test_cleaning_strips_control_characters_without_altering_meaningful_content():
    dirty = "Hello\x00world\x0b, this\x0cis\x01a\x02real\x1fsentence."
    cleaned = _clean_text(dirty)
    assert "\x00" not in cleaned
    assert "\x0b" not in cleaned
    assert "\x0c" not in cleaned
    assert "\x01" not in cleaned
    assert "\x02" not in cleaned
    assert "\x1f" not in cleaned
    # Every real word survives, just no longer glued together by the
    # stripped control character.
    for word in ("Hello", "world", "this", "is", "a", "real", "sentence"):
        assert word in cleaned


def test_cleaning_normalizes_whitespace_without_altering_words():
    dirty = "This   has\t\tirregular\n\n\nwhitespace   throughout."
    cleaned = _clean_text(dirty)
    for word in ("This", "has", "irregular", "whitespace", "throughout."):
        assert word in cleaned
    assert "   " not in cleaned


def test_unsupported_file_type_raises_value_error():
    with pytest.raises(ValueError):
        extract_and_clean(str(FIXTURES / "sample.txt"), "exe")
