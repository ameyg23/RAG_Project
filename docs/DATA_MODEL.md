# Data Model

Conceptual data structures. Physical storage per structure is noted in each
section and must match `docs/ARCHITECTURE_DECISIONS.md` (ADR-07, ADR-11,
ADR-12) and `ARCHITECTURE.md` §8.

## 1. KnowledgeBase

| Field | Type | Required | Notes |
|---|---|---|---|
| `knowledge_base_id` | string | required | `kb_demo` (fixed) or `kb_user_<uuid>` |
| `kind` | enum(`demo`, `user`) | required | Determines read/write rules |
| `owner_session_token` | string \| null | required (null for demo) | Null for `demo`; set for `user` |
| `created_at` | datetime | required | |
| `document_count` | int | derived | Computed from DocumentChunk records, not stored |

**Purpose:** the unit of isolation (NFR-004) and the unit a chat request is
scoped to (FR-020).

**Persistence:** not stored as its own record — it is an *implicit* entity
derived from the distinct `knowledge_base_id` values present in Qdrant
payloads, plus the in-process document-status map for anything still
`PROCESSING`. This follows ADR-12 (no separate database).

**Relationships:** one KnowledgeBase → many Document.

## 2. Document

| Field | Type | Required | Notes |
|---|---|---|---|
| `document_id` | string (UUID) | required | Stable identifier, used in chunk_id and citations |
| `knowledge_base_id` | string | required | FK-equivalent to KnowledgeBase; never optional (ADR-14) |
| `filename` | string | required | Original filename as uploaded |
| `file_type` | enum(`pdf`,`docx`,`txt`,`md`) | required | Drives extraction stage (docs/RAG_PIPELINE.md §1) |
| `size_bytes` | int | required | Validated ≤ 5,242,880 (5 MB) at upload |
| `status` | enum(`UPLOADED`,`PROCESSING`,`READY`,`FAILED`) | required | See `docs/DOCUMENT_PROCESSING.md` state machine |
| `failure_reason` | string \| null | optional | Set only when `status = FAILED` |
| `uploaded_at` | datetime | required | |
| `chunk_count` | int | derived | Count of DocumentChunk rows once `READY` |

**Purpose:** tracks one uploaded (or demo-seeded) source file end-to-end
from upload through ingestion.

**Persistence:** while `UPLOADED`/`PROCESSING`, held in backend process
memory (ADR-12). Once `READY`, its existence is represented entirely by its
DocumentChunk rows in Qdrant (a document with zero chunks after processing
is definitionally `FAILED`, not `READY` with nothing — see
`docs/DOCUMENT_PROCESSING.md`). `FAILED` status is retained in memory only
long enough for the client to observe it via polling; it is not persisted
indefinitely (a fresh backend restart clears it, which is acceptable per
ADR-12 — the user simply re-uploads).

**Relationships:** one Document → many DocumentChunk. Many Document →
one KnowledgeBase.

## 3. DocumentChunk

| Field | Type | Required | Notes |
|---|---|---|---|
| `chunk_id` | string | required | `{document_id}_{chunk_index}` — idempotent upsert key |
| `document_id` | string | required | FK to Document |
| `knowledge_base_id` | string | required | Duplicated onto every chunk for filterable isolation (ADR-14) |
| `document_name` | string | required | Duplicated from Document for citation display without a join |
| `chunk_index` | int | required | Position within the document |
| `page` | int \| null | optional | Set for PDF; null for DOCX/TXT/MD |
| `text` | string | required | Cleaned, chunked text (≤ ~800 chars, docs/RAG_PIPELINE.md §3) |

**Purpose:** the retrievable unit; also the row-level citation source
(FR-040).

**Persistence:** stored as a Qdrant point's **payload** (this table = payload
schema); the embedding vector is stored alongside as the point's vector,
described separately below (§4) since it is not a payload field
conceptually, even though it lives in the same Qdrant point.

**Relationships:** many DocumentChunk → one Document → one KnowledgeBase.
One DocumentChunk → one Embedding (1:1, same Qdrant point).

## 4. Embedding / Vector Record

| Field | Type | Required | Notes |
|---|---|---|---|
| `chunk_id` | string | required | Same value as DocumentChunk.chunk_id; this *is* the Qdrant point ID |
| `vector` | float[384] | required | Output of `all-MiniLM-L6-v2` (ADR-06) |
| `payload` | DocumentChunk (§3) | required | Everything above, attached to the same Qdrant point |

**Purpose:** enables similarity search (`docs/RAG_PIPELINE.md` §6–8).

**Persistence:** Qdrant Cloud, single shared collection (ADR-07, ADR-14).

**Relationships:** 1:1 with DocumentChunk (same physical record, different
conceptual facet — vector vs. payload).

## 5. ChatSession

**Decision: no server-side ChatSession record exists in V1** (per
`docs/REQUIREMENTS.md` FR-023 and ADR-12). The only session-level state the
backend holds is the mapping of `session_token → owned knowledge_base_id`,
which is not a "session" in the conversational sense — it carries no message
history, only ownership.

| Field | Type | Required | Notes |
|---|---|---|---|
| `session_token` | string (UUID) | required | Issued once per browser, stored client-side |
| `owned_knowledge_base_id` | string \| null | optional | Set once the session uploads its first document |

**Persistence:** in-process memory map on the backend (acceptable per
ADR-12 — losing this on restart just means a returning session with an
existing KB in Qdrant needs to re-establish ownership; see
`docs/SECURITY.md` for how ownership is verified against Qdrant directly
rather than trusted purely from this map).

## 6. ChatMessage

**Decision: no server-side ChatMessage record exists in V1.** Chat history
is a client-only concept (React state / `localStorage`), never transmitted
to or stored by the backend beyond the single in-flight request/response.

| Field (client-side only) | Type | Notes |
|---|---|---|
| `role` | enum(`user`,`assistant`) | For rendering the thread |
| `content` | string | Message text |
| `sources` | SourceReference[] | Only present on `assistant` messages |
| `timestamp` | datetime | Client-generated, display only |

**Purpose:** UI rendering only (`docs/UI_UX.md`).

## 7. SourceReference

| Field | Type | Required | Notes |
|---|---|---|---|
| `document_id` | string | required | |
| `document_name` | string | required | |
| `locator` | string | required | `"page 3"` or `"chunk 2"` depending on file type |
| `snippet` | string | required | The cited chunk's text (or a truncation of it) |
| `is_removed` | bool | required | True if the source document was deleted after this answer was generated (FR-042) |

**Purpose:** the structure returned in every `/chat` response's `sources[]`
array (matches `docs/API.md`).

**Persistence:** not persisted — constructed per-response from Stage 14 of
`docs/RAG_PIPELINE.md`, held client-side only as part of ChatMessage (§6).

**Relationships:** many SourceReference → one DocumentChunk (at the time of
generation); may outlive the underlying DocumentChunk if deleted (`is_removed`
flag covers this).

## 8. EvaluationCase

| Field | Type | Required | Notes |
|---|---|---|---|
| `case_id` | string | required | Unique within the evaluation dataset |
| `knowledge_base_id` | string | required | Which KB (typically `kb_demo` or a fixed eval KB) the case targets |
| `question` | string | required | Input query |
| `expected_answer_summary` | string | required | Human-written expected gist, not exact-match text |
| `expected_source_documents` | string[] | required | Document names expected to be cited |
| `category` | enum(`answerable`,`no_context`,`adversarial`) | required | Drives which evaluation dimension it feeds (`docs/RAG_EVALUATION.md`) |

**Purpose:** the fixed input to the evaluation suite.

**Persistence:** flat files under `evaluation/dataset/` (JSON/YAML), version
controlled — not a database table.

**Relationships:** many EvaluationCase → one EvaluationResult per run.

## 9. EvaluationResult

| Field | Type | Required | Notes |
|---|---|---|---|
| `run_id` | string | required | Timestamped identifier for one evaluation run |
| `case_id` | string | required | FK to EvaluationCase |
| `actual_answer` | string | required | What the system returned |
| `actual_sources` | string[] | required | Document names actually cited |
| `retrieval_hit` | bool | required | Whether expected source(s) were in top-K |
| `groundedness_score` | float (0–1) | required | See `docs/RAG_EVALUATION.md` |
| `relevance_score` | float (0–1) | required | See `docs/RAG_EVALUATION.md` |
| `passed` | bool | required | Derived from thresholds, not fabricated |

**Purpose:** output of one evaluation run, compared across runs to detect
regressions.

**Persistence:** flat files under `evaluation/results/<run_id>.json` — not a
database table; explicitly separate from application runtime data (never
touches Qdrant).

**Relationships:** many EvaluationResult → one EvaluationCase; many
EvaluationResult grouped by one `run_id`.

## Cross-Entity Summary

```
KnowledgeBase (implicit) ─┬─< Document ─< DocumentChunk ──(1:1)── Embedding
                          │                     │
                          │                     └── (per response) → SourceReference
                          │
                          └─ ownership via session_token (no ChatSession record)

EvaluationCase ─< EvaluationResult  (entirely separate from the above; evaluation/ tree only)
```

Knowledge-base isolation (NFR-004) is enforced at the DocumentChunk/Embedding
level via the mandatory `knowledge_base_id` payload field — there is no
separate KnowledgeBase table to accidentally bypass.
