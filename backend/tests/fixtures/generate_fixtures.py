"""One-time generator for backend/tests/fixtures/*. Not part of the app or
test suite runtime — run manually only when fixtures need regenerating.
Requires: pip install reportlab python-docx (not in requirements*.txt).
"""

from pathlib import Path

from docx import Document
from reportlab.pdfgen import canvas

FIXTURES_DIR = Path(__file__).parent

PAGE1_TEXT = "Quarterly revenue grew 12 percent driven by new enterprise contracts."
PAGE2_TEXT = "Customer satisfaction scores improved to 94 percent this quarter."


def make_sample_pdf():
    path = FIXTURES_DIR / "sample.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, PAGE1_TEXT)
    c.showPage()
    c.drawString(72, 720, PAGE2_TEXT)
    c.showPage()
    c.save()


def make_blank_pdf():
    path = FIXTURES_DIR / "blank_no_text.pdf"
    c = canvas.Canvas(str(path))
    c.showPage()
    c.save()


def make_sample_docx():
    path = FIXTURES_DIR / "sample.docx"
    doc = Document()
    doc.add_paragraph(
        "This is a short sample paragraph used to verify DOCX extraction works correctly."
    )
    doc.save(str(path))


def make_corrupted_docx():
    path = FIXTURES_DIR / "corrupted.docx"
    path.write_bytes(b"this is not a real zip/docx file, just plain bytes")


def make_sample_txt():
    path = FIXTURES_DIR / "sample.txt"
    path.write_text("This is a short sample sentence for TXT extraction.\n", encoding="utf-8")


def make_sample_md():
    path = FIXTURES_DIR / "sample.md"
    content = "# Sample Heading\n\nThis is a short sample paragraph for MD extraction.\n"
    path.write_text(content, encoding="utf-8")


def make_empty_md():
    path = FIXTURES_DIR / "empty.md"
    path.write_text("   \n\n   \t\n", encoding="utf-8")


def make_corrupted_pdf():
    path = FIXTURES_DIR / "corrupted.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is deliberately truncated and malformed\n")


def make_invalid_encoding_txt():
    path = FIXTURES_DIR / "invalid_encoding.txt"
    # 0xff 0xfe is not valid standalone UTF-8.
    path.write_bytes(b"\xff\xfe\x00invalid utf-8 bytes\x00\xff")


if __name__ == "__main__":
    make_sample_pdf()
    make_blank_pdf()
    make_sample_docx()
    make_corrupted_docx()
    make_sample_txt()
    make_sample_md()
    make_empty_md()
    make_corrupted_pdf()
    make_invalid_encoding_txt()
    print("Fixtures generated in", FIXTURES_DIR)
