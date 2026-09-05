# Requirements Specification

Status: Planning phase. No implementation exists yet.

> **Source note:** No `CLAUDE.md` was present in this repository at planning time. This
> specification was derived from the project brief supplied for the planning phase
> (a zero-cost RAG chatbot with a demo knowledge base and user-uploaded documents,
> chat with source citations). If a `CLAUDE.md` is added later with conflicting or
> additional requirements, this document must be reconciled against it. See
> `docs/PLANNING_REVIEW.md` → Open Questions.

## 1. Project Objective

Build a portfolio-grade Retrieval-Augmented Generation (RAG) chatbot that:

- Ships with a pre-loaded **demo knowledge base** so a visitor can evaluate the
  product with zero setup.
- Lets a visitor **upload their own documents** to create a private, isolated
  knowledge base and chat against it.
- Answers questions **grounded in retrieved source chunks**, with visible
  **citations** back to the originating document.
- Runs entirely on **free-tier infrastructure** (no required paid service, no
  credit-card-gated tier) so the project can be deployed and kept live at
  $0/month indefinitely.
- Demonstrates a realistic, evaluable RAG pipeline (chunking, embeddings,
  vector retrieval, grounded generation) suitable for a technical portfolio.

## 2. Target Users

| User type | Description | Primary need |
|---|---|---|
| Recruiter / hiring manager | Technical or semi-technical, limited time | See the app work in under 60 seconds without setup |
| Engineer evaluating the project | Reads code and architecture | Understand design decisions and RAG correctness |
| Casual visitor | Wants to try uploading their own file | Upload a document and get a correct, cited answer |

There are no authenticated user accounts in V1 (see §12 exclusions).

## 3. Primary User Journeys

1. **Explore the demo** — visitor lands on the app, sees the demo knowledge base
   already selected, sees suggested questions, asks one, gets a cited answer.
2. **Bring your own document** — visitor uploads 1–5 files, watches processing
   status, then chats against only their own uploaded knowledge base.
3. **Compare sources** — visitor asks a question and inspects which document(s)
   and chunk(s) the answer was grounded in.
4. **Recover from a bad upload** — visitor uploads an unsupported or oversized
   file and understands why it was rejected.

## 4. Demo Knowledge-Base Flow

- FR-001: On first load, the app selects the demo knowledge base by default.
- FR-002: The demo knowledge base is pre-ingested at build/deploy time (not
  ingested on the fly by a visitor request).
- FR-003: The demo knowledge base displays 3–5 suggested questions that are
  known to be answerable from its content.
- FR-004: The demo knowledge base is read-only — visitors cannot add, delete,
  or modify its documents.

**Acceptance:** A visitor who has performed no upload can ask a suggested
question and receive a grounded, cited answer within one request.

## 5. User Document-Upload Flow

- FR-010: A visitor may upload 1–5 files in a single request.
- FR-011: Each file must be ≤ 5 MB.
- FR-012: Supported formats: PDF, DOCX, TXT, Markdown (`.md`).
- FR-013: Uploaded documents form a knowledge base scoped to the uploading
  browser session (see §7, Knowledge-Base Isolation).
- FR-014: The visitor sees per-file status (`UPLOADED` → `PROCESSING` →
  `READY`/`FAILED`) without manually refreshing the page.
- FR-015: A visitor may delete a previously uploaded document from their
  session's knowledge base.

**Acceptance:** A visitor who uploads a valid 2 MB PDF sees it reach `READY`
within a bounded time (see NFR-002) and can then ask questions answered from
its content.

## 6. Chat Flow

- FR-020: A visitor selects exactly one knowledge base (demo or their own)
  before/while chatting; every chat request is scoped to that one knowledge
  base.
- FR-021: Each chat request returns an answer plus zero or more source
  citations.
- FR-022: If retrieval finds no sufficiently relevant chunks, the app returns
  an explicit "not enough information in this knowledge base" response instead
  of an unguided LLM answer.
- FR-023: Chat history is retained for the duration of the browser session
  (in-memory or `localStorage`), not persisted server-side beyond that.

**Acceptance:** Every answer shown in the UI either carries at least one
source citation or is the explicit no-context response from FR-022 — never an
uncited free-form answer.

## 7. Knowledge-Base Selection Behavior

- FR-030: Exactly one knowledge base is active at a time (no cross-KB
  retrieval/blending in V1).
- FR-031: The demo knowledge base is visible to every visitor; a user-created
  knowledge base is visible only to the session that created it.
- FR-032: Switching knowledge bases clears the active chat context (new
  conversation), since answers are scoped per knowledge base.

## 8. Source Citation Behavior

- FR-040: Each citation identifies at minimum: document name, and a locator
  (page number for PDF, or chunk index) sufficient to find the passage.
- FR-041: Citations reference only chunks that were actually included in the
  LLM's context for that answer (no citation of unused retrieval results).
- FR-042: If the underlying document has been deleted after an answer was
  generated, the citation still renders (using stored metadata) but is marked
  as referring to a removed document.

## 9. Error Scenarios

- FR-050: Upload rejected — wrong file type → clear inline error naming the
  supported types.
- FR-051: Upload rejected — file too large → clear inline error stating the
  5 MB limit.
- FR-052: Upload rejected — more than 5 files in one request → clear inline
  error stating the 5-file limit.
- FR-053: Document processing fails (corrupt file, extraction yields no text)
  → status becomes `FAILED` with a user-readable reason; other files in the
  same batch continue processing independently.
- FR-054: LLM provider request fails or times out → chat UI shows a retryable
  error, not a raw stack trace or provider error payload.
- FR-055: Vector database unreachable → chat UI shows a retryable error;
  upload flow shows a retryable error, distinguished from an LLM failure.
- FR-056: Empty knowledge base (no documents ready yet) → chat input is
  disabled or clearly warns that no answer can be grounded.

## 10. Functional Requirements Summary

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-001 | Demo KB selected by default | Landing state shows demo KB active, no user action required |
| FR-002 | Demo KB pre-ingested | Demo KB is queryable with zero visitor-triggered ingestion |
| FR-003 | Demo KB suggested questions | 3–5 suggestions shown, each answerable from demo content |
| FR-004 | Demo KB read-only | No upload/delete controls rendered for demo KB |
| FR-010 | Multi-file upload (≤5) | 6th file in one request is rejected client- and server-side |
| FR-011 | 5 MB per-file limit | File >5 MB rejected before upload completes |
| FR-012 | Supported formats | Only PDF/DOCX/TXT/MD accepted; others rejected with FR-050 |
| FR-013 | Session-scoped user KB | Two browser sessions never see each other's uploaded docs |
| FR-014 | Live status without refresh | Status updates visible via polling or push within NFR-002 window |
| FR-015 | Delete uploaded document | Deleted doc's chunks removed from vector DB and no longer retrievable |
| FR-020 | Single active KB per chat | Chat request payload carries exactly one `knowledge_base_id` |
| FR-021 | Answer + citations | Response schema always includes a `sources` array (may be empty only per FR-022) |
| FR-022 | No-context guard | Below-threshold retrieval returns fixed "not enough information" response |
| FR-023 | Session-only chat history | No chat message persists after session/localStorage is cleared |
| FR-030 | One KB at a time | API rejects/ignores multi-KB query params |
| FR-031 | KB visibility isolation | Demo KB = global; user KB = session-private |
| FR-032 | KB switch resets context | Switching KB clears displayed chat thread |
| FR-040 | Citation locator | Every citation includes document name + page/chunk locator |
| FR-041 | Citation ⊆ used context | No citation appears for a chunk absent from the prompt context |
| FR-042 | Stale citation handling | Citation to a deleted doc renders with a "removed" marker, no crash |
| FR-050–056 | Error scenarios | Each error path produces a distinct, user-readable message (see §9) |

## 11. Non-Functional Requirements

| ID | Requirement | Acceptance criterion |
|---|---|---|
| NFR-001 | Zero required cost | The documented V1 deployment uses only free-tier services; no step requires entering payment details |
| NFR-002 | Bounded processing time | A 5 MB PDF reaches `READY` or `FAILED` within 60 seconds under normal (non-cold-start) conditions |
| NFR-003 | Cold-start tolerance | UI communicates a "waking up" state when the free-tier backend is cold-starting, rather than appearing broken |
| NFR-004 | Knowledge-base isolation | No retrieval query against KB A can return chunks stored under KB B |
| NFR-005 | No secrets in frontend | No LLM/vector-DB API key appears in any frontend bundle, source map, or network request visible to the browser |
| NFR-006 | Basic input validation | All upload and chat endpoints validate size/type/shape before processing |
| NFR-007 | Reasonable retrieval quality | Evaluation suite (docs/RAG_EVALUATION.md) defines measurable groundedness/relevance thresholds |
| NFR-008 | Portability | Any single provider (LLM, vector DB, hosting) can be swapped without rewriting the RAG pipeline logic |
| NFR-009 | Observability | Errors are logged server-side with enough context to diagnose, without leaking secrets into logs |

## 12. Explicit V1 Exclusions

The following are **out of scope for V1** and must not be implied as available
in any UI copy or documentation:

- User authentication / accounts / login.
- Multi-turn conversation memory that persists across browser sessions or
  devices.
- Cross-knowledge-base search or merging multiple KBs into one answer.
- Editing an uploaded document in place (re-upload is the only path).
- Re-downloading the original uploaded file after ingestion (only extracted
  chunks persist).
- Streaming token-by-token responses (V1 returns a complete answer per
  request; streaming is a future improvement).
- Any paid LLM, vector DB, or hosting tier.
- Admin dashboard / usage analytics UI.
- Support for file formats beyond PDF/DOCX/TXT/MD (e.g. images, spreadsheets,
  HTML, audio transcripts).
- Automatic retry/backoff scheduling for failed document processing (a failed
  document must be manually re-uploaded, see docs/DOCUMENT_PROCESSING.md).

## 13. Cross-Reference

This document is the source of truth for *what* the system must do. See:

- `docs/ARCHITECTURE_DECISIONS.md` — *how* each requirement is technically satisfied.
- `docs/RAG_PIPELINE.md` — implementation of FR-020–FR-042.
- `docs/DOCUMENT_PROCESSING.md` — implementation of FR-010–FR-015, FR-050–FR-053.
- `docs/SECURITY.md` — implementation of NFR-005, NFR-006.
- `docs/RAG_EVALUATION.md` — implementation of NFR-007.
