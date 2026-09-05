# Test Fixtures

Real, valid (or deliberately invalid) files used by `tests/test_extract.py`.
Committed as static binary/text files — the test suite only reads them.

| File | Purpose |
|---|---|
| `sample.pdf` | 2 real pages, distinct text per page, verifies per-page extraction |
| `sample.docx` | short real paragraph, verifies DOCX extraction |
| `sample.txt` | short real sentence, verifies TXT extraction |
| `sample.md` | short real heading + paragraph, verifies MD extraction |
| `blank_no_text.pdf` | one real PDF page with no text (simulates a scanned/image-only page) — triggers `EmptyDocumentError` |
| `empty.md` | whitespace-only content — triggers `EmptyDocumentError` via the direct-decode path |
| `corrupted.pdf` | malformed/truncated PDF bytes — triggers `CorruptedDocumentError` |
| `corrupted.docx` | not a real zip file — triggers `CorruptedDocumentError` |
| `invalid_encoding.txt` | not valid UTF-8 — triggers `CorruptedDocumentError` via `UnicodeDecodeError` |

## Regenerating

`generate_fixtures.py` (in this directory) creates all of the above. It
requires `reportlab` and `python-docx`, which are **not** in
`requirements.txt`/`requirements-dev.txt` — they're one-time generation
tools, not application or test-suite runtime dependencies:

```
pip install reportlab python-docx
python tests/fixtures/generate_fixtures.py
```

Running the test suite itself never needs these two packages.
