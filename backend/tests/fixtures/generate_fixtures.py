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


# Synthetic content mimicking a "Chrome print-to-PDF from a webpage" resume
# template: a narrow left sidebar (Contact/Skills) beside a wider right main
# column (Experience/Education). All-fake data.
TWO_COLUMN_MAIN_LINES = [
    (320, 740, "Jordan Alvarez"),
    (320, 720, "Experience"),
    (320, 700, "Senior Backend Engineer, Nimbus Data Corp (2022-2026)"),
    (320, 682, "Led migration of the billing service to event-driven"),
    (320, 664, "architecture, reducing invoice latency by 40 percent."),
    (320, 646, "Software Engineer, Fenwick Analytics (2019-2022)"),
    (320, 628, "Built internal dashboards used by 200+ analysts daily."),
    (320, 600, "Education"),
    (320, 582, "B.S. Computer Science, Riverbend State University, 2019"),
]
TWO_COLUMN_SIDE_LINES = [
    (40, 740, "Contact"),
    (40, 722, "jordan.alvarez.demo@example.com"),
    (40, 704, "+1-555-0134"),
    (40, 680, "Skills"),
    (40, 662, "Python"),
    (40, 644, "Kubernetes"),
    (40, 626, "PostgreSQL"),
    (40, 608, "Distributed Systems"),
]


def make_two_column_pdf():
    """A single-page, two-column (sidebar + main) PDF whose content stream
    interleaves the two columns line-by-line — this draw-order interleaving
    (not necessarily matching on-page visual order) is what pypdf's default
    "plain" extraction mode is sensitive to; "layout" mode is not, since it
    positions text by (x, y) instead of draw order.
    """
    path = FIXTURES_DIR / "two_column_resume.pdf"
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    n = max(len(TWO_COLUMN_MAIN_LINES), len(TWO_COLUMN_SIDE_LINES))
    for i in range(n):
        if i < len(TWO_COLUMN_SIDE_LINES):
            x, y, t = TWO_COLUMN_SIDE_LINES[i]
            c.drawString(x, y, t)
        if i < len(TWO_COLUMN_MAIN_LINES):
            x, y, t = TWO_COLUMN_MAIN_LINES[i]
            c.drawString(x, y, t)
    c.showPage()
    c.save()


# Synthetic single-column resume content (all-fake data) used to empirically
# measure embedding-model similarity behavior on short fact-list documents —
# the class of document (a resume) that motivated the all-MiniLM-L6-v2 ->
# BAAI/bge-small-en-v1.5 embedding-model swap: MiniLM scored real resumes at
# 0.07-0.24 against natural questions, always below MIN_SIMILARITY_SCORE,
# while the demo KB's long narrative policy docs scored 0.48-0.84. Plain
# single-column .md (not a PDF) — this fixture is about embedding/threshold
# behavior on short fact-list text, not about extract.py's column-order
# handling (see make_two_column_pdf for that, a separate concern).
SYNTHETIC_RESUME_MD = """\
# Priya Chandrasekaran

## Contact
priya.chandrasekaran.demo@example.com | +1-555-0198 | Austin, TX

## Summary
Backend software engineer with 6 years of experience building distributed
systems and data pipelines. Focused on Python, Go, and cloud infrastructure.

## Skills
Python, Go, PostgreSQL, Redis, Kafka, Docker, Kubernetes, AWS, Terraform,
gRPC, REST API design, CI/CD pipelines

## Experience

### Senior Backend Engineer, Alderbrook Systems (2021-2026)
Designed and operated a Kafka-based event pipeline processing 40 million
events per day. Migrated a monolithic billing service to a set of Go
microservices, cutting p99 latency from 800ms to 120ms. Mentored two junior
engineers and led the on-call rotation for the payments team.

### Backend Engineer, Hartwell Logistics (2018-2021)
Built REST and gRPC APIs for a fleet-tracking platform used by 300+
warehouse operators. Introduced Terraform-managed infrastructure, reducing
environment provisioning time from two days to under one hour.

### Junior Developer, Oakline Software (2016-2018)
Maintained a Django-based inventory management system and wrote automated
regression tests that cut manual QA time by half.

## Education
B.S. in Computer Science, Westfield Institute of Technology, 2016

## Certifications
AWS Certified Solutions Architect - Associate (2022)
Certified Kubernetes Administrator (2023)
"""


def make_synthetic_resume():
    path = FIXTURES_DIR / "synthetic_resume.md"
    path.write_text(SYNTHETIC_RESUME_MD, encoding="utf-8")


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
    make_two_column_pdf()
    make_synthetic_resume()
    make_sample_docx()
    make_corrupted_docx()
    make_sample_txt()
    make_sample_md()
    make_empty_md()
    make_corrupted_pdf()
    make_invalid_encoding_txt()
    print("Fixtures generated in", FIXTURES_DIR)
