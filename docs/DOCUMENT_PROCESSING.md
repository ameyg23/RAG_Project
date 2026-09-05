# Document Processing Specification

Covers upload validation through the status state machine. Pipeline
mechanics (extraction/chunking/embedding internals) are specified stage-by-
stage in `docs/RAG_PIPELINE.md`; this document governs the surrounding
document-lifecycle behavior referenced by `docs/API.md` and
`docs/DATA_MODEL.md`.

## Supported File Formats

| Format | Extension | Extraction method |
|---|---|---|
| PDF | `.pdf` | LangChain `PyPDFLoader` (page-by-page) |
| Word | `.docx` | LangChain `Docx2txtLoader` |
| Plain text | `.txt` | Direct UTF-8 decode |
| Markdown | `.md` | Direct UTF-8 decode (Markdown syntax is not stripped — kept as plain text for retrieval; this is a V1 simplification, not a defect) |

No other format is accepted (FR-012). Legacy `.doc`, images, spreadsheets,
and HTML are explicitly excluded (`docs/REQUIREMENTS.md` §12).

## Upload Constraints

- **Per-file size limit:** 5 MB (5,242,880 bytes), hard limit — FR-011.
- **Per-request file count:** 1–5 files — FR-010.
- **Total request body:** bounded by the ASGI server as defense-in-depth
  beyond the per-file check (`docs/API.md` → `413`).

## Validation Order (matches `docs/API.md` → `POST /documents/upload`)

Validation runs **before any file is written to disk or processing begins**,
and the **whole batch is rejected** if any single file fails any check —
there is no partial acceptance:

1. **Count check** — 1–5 files present, else `400 NO_FILES_PROVIDED` /
   `400 TOO_MANY_FILES`.
2. **Size check** (per file) — ≤ 5,242,880 bytes, else `400 FILE_TOO_LARGE`
   naming the offending file.
3. **Type check** (per file) — extension/MIME resolves to pdf/docx/txt/md,
   else `400 UNSUPPORTED_FILE_TYPE` naming the offending file and the
   supported list.

Only after all files in the batch pass all three checks does the endpoint
return `202 Accepted` and enqueue background processing (ADR-13).

## Text Extraction

- PDF: extracted page-by-page, each page becomes one text unit with its page
  number preserved (`docs/RAG_PIPELINE.md` §1). A scanned/image-only PDF
  extracts to an empty (or whitespace-only) string per page — this is not an
  extraction *error*, but is caught by empty-document handling below.
- DOCX: extracted as a single text unit (no native page concept).
- TXT/MD: decoded directly as a single text unit; a decode error (invalid
  UTF-8) is treated as a corrupted-document failure.

## Empty Document Handling

If, after extraction and cleaning (`docs/RAG_PIPELINE.md` §1–2), every text
unit is empty or whitespace-only, the document is marked:

```
status = FAILED
failure_reason = "No extractable text found (file may be a scanned image)."
```

This is a distinct, specific reason string — never a generic "processing
failed" — so the user understands *why* (a scanned PDF with no OCR layer is
the most common real-world cause).

## Corrupted Document Handling

If extraction raises an exception (malformed PDF structure, unreadable
DOCX archive, decode error), the document is marked:

```
status = FAILED
failure_reason = "This file could not be read. It may be corrupted or in an unexpected format."
```

The underlying exception is logged server-side for diagnosis (consistent
with the error-sanitization principle applied throughout this project:
internal exception detail is never forwarded to the client, only a safe,
specific-enough summary is).

A vector-store write failure during the embedding/upsert stage
(`docs/RAG_PIPELINE.md` §6) is a **third, distinct** failure reason:

```
status = FAILED
failure_reason = "The document was processed but could not be saved. Please try uploading again."
```

— distinguished from the two extraction-side failures above because it is
transient/retriable (a Qdrant hiccup), whereas the first two are properties
of the file itself and re-uploading the same file would not help.

## Chunking, Metadata, Embedding, Vector Storage

These stages run exactly as specified in `docs/RAG_PIPELINE.md` §3–6:

- Chunking: 800-character chunks, 120-character (15%) overlap, per-page
  splitting for PDFs so page attribution is never lost across a chunk
  boundary.
- Metadata: every chunk carries `document_id`, `knowledge_base_id`,
  `document_name`, `chunk_index`, and `page` (nullable) — schema defined in
  `docs/DATA_MODEL.md` → DocumentChunk.
- Embedding: local `all-MiniLM-L6-v2`, batched (e.g. 32 chunks/batch) to
  bound peak memory on the free-tier backend instance.
- Vector storage: Qdrant upsert, keyed by `chunk_id =
  {document_id}_{chunk_index}` — idempotent, so re-processing (e.g. after a
  transient failure and re-upload) overwrites rather than duplicates.

## Status State Machine

```
UPLOADED ──► PROCESSING ──► READY
                 │
                 └────────► FAILED
```

| State | Meaning | Entered when | Exited when |
|---|---|---|---|
| `UPLOADED` | File passed all upload validation; background task not yet started or just starting | `POST /documents/upload` returns `202` | Background task begins extraction |
| `PROCESSING` | Extraction → cleaning → chunking → embedding → upsert in progress | Background task starts | All chunks upserted (→`READY`) or any stage fails (→`FAILED`) |
| `READY` | Document is fully queryable | Last chunk upserted successfully | Terminal — only exits via deletion (`DELETE /documents/{id}`) |
| `FAILED` | Terminal failure state, `failure_reason` set | Extraction failure, empty-document, or vector-store write failure | Terminal — user must re-upload; the failed `document_id` is not reused |

A document is never `READY` with zero chunks — zero extractable/chunkable
content is definitionally the empty-document `FAILED` case, never a silent
"empty but ready" state (this closes a gap that would otherwise let a chat
request silently retrieve nothing without the user knowing why).

## Retry Behavior

**V1 has no automatic retry.** A `FAILED` document must be manually
re-uploaded by the user as a new upload request (a new `document_id` is
issued — failed documents are not reused or overwritten in place).

This is a deliberate simplification (`docs/ARCHITECTURE_DECISIONS.md`
ADR-13): automatic retry scheduling would require a background scheduler or
task queue, which was explicitly avoided to keep the system dependency-free
at this project's scale. Given the 5MB/5-file caps, a manual re-upload is a
low-cost recovery path for the user.

## User Behavior During PROCESSING

While one or more of a knowledge base's documents are `UPLOADED` or
`PROCESSING`:

- The document list shows a per-file status badge (see `docs/UI_UX.md` for
  the exact visual treatment) reflecting live polling of
  `GET /documents/{id}/status`.
- Chat against that knowledge base remains available if **at least one**
  other document is already `READY` — processing is per-document, not
  batch-blocking.
- If **zero** documents in the active knowledge base are `READY` yet (all
  still `UPLOADED`/`PROCESSING`, or all `FAILED`), the chat input is
  disabled with an explanatory message (FR-056), rather than silently
  allowing a query that can retrieve nothing.

## Demo Knowledge-Base Seeding

The demo knowledge base is **never** populated through the public
`/documents/upload` endpoint and is never observed by a visitor in
`UPLOADED`/`PROCESSING` state — it is always already `READY`.

It is populated by an offline, deploy-time script,
`backend/scripts/seed_demo_kb.py`, which runs the identical pipeline described above
(extraction → cleaning → chunking → metadata → embedding → vector storage)
directly against the fixed `kb_demo` knowledge base ID, before the backend
is exposed to public traffic. This keeps the demo KB's content
deterministic and reproducible (needed for `docs/RAG_EVALUATION.md`'s
evaluation dataset, which is written against this fixed content) and means
the public API surface never needs a "seed the demo KB" endpoint that would
otherwise have to be access-controlled.
