# RAG Pipeline Specification

Full path: **Document → Extraction → Cleaning → Chunking → Metadata →
Embedding → Vector storage → Query embedding → Similarity search → Top-K
retrieval → Context construction → Prompt → LLM → Answer → Source
attribution.**

Technology choices are justified in `docs/ARCHITECTURE_DECISIONS.md`
(ADR-05, ADR-06, ADR-07, ADR-08). This document defines behavior, not
rationale.

## Stage-by-Stage Specification

### 1. Extraction

- **Input:** raw file bytes + declared MIME/extension (PDF, DOCX, TXT, MD).
- **Processing:** format-specific text extraction — `pypdf`/LangChain
  `PyPDFLoader` for PDF (page-by-page), `python-docx`/`Docx2txtLoader` for
  DOCX, direct UTF-8 decode for TXT/MD.
- **Output:** ordered list of `(text, page_number_or_none)` units — one per
  PDF page, or a single unit for DOCX/TXT/MD (page = `None`).
- **Technology:** LangChain document loaders (ADR-05).
- **Failure modes:** encrypted/password-protected PDF; corrupted file
  (parser exception); scanned/image-only PDF (extracts to empty string);
  unsupported encoding in TXT/MD.
- **Validation:** if extraction raises, or every unit's text is empty/
  whitespace-only after stripping, the document is marked `FAILED` with a
  specific reason string (see `docs/DOCUMENT_PROCESSING.md`).

### 2. Cleaning

- **Input:** raw extracted text units from Stage 1.
- **Processing:** collapse repeated whitespace/newlines, strip control
  characters, normalize Unicode (NFKC), drop units that are empty after
  cleaning.
- **Output:** cleaned text units, same ordering.
- **Technology:** plain Python (`unicodedata`, `re`) — no library needed.
- **Failure modes:** cleaning reduces a unit to empty (e.g. a page that was
  only headers/footers) — such units are dropped, not treated as failure,
  unless *all* units end up empty (→ Stage 1's empty-document failure).
- **Validation:** unit test asserts idempotence (cleaning already-clean text
  is a no-op) and that no unit is silently duplicated or reordered.

### 3. Chunking

- **Input:** cleaned text units with page numbers.
- **Processing:** LangChain `RecursiveCharacterTextSplitter` applied per
  unit (so a chunk never silently merges text across a PDF page boundary
  without recording it), preserving the source page number as chunk
  metadata.
- **Output:** ordered list of chunks: `{text, page, chunk_index}`.
- **Technology:** LangChain text splitter (ADR-05).
- **Configuration:**
  - Chunk size: **800 characters**
  - Chunk overlap: **120 characters** (15%)
  - Separators tried in order: `\n\n`, `\n`, `. `, `" "`, `""`
- **Failure modes:** a single unit shorter than the overlap (tiny page) —
  splitter returns it as one chunk unchanged, which is correct behavior, not
  a failure.
- **Validation:** unit test asserts every chunk ≤ chunk size + small
  tolerance, and that concatenating chunks (minus overlap) reconstructs the
  cleaned text.

### 4. Metadata

- **Input:** chunks from Stage 3 + upload-time context (`document_id`,
  `document_name`, `knowledge_base_id`, `uploaded_at`).
- **Processing:** attach metadata to each chunk record (see
  `docs/DATA_MODEL.md` → DocumentChunk for the full field list).
- **Output:** chunk records ready for embedding, each with a stable
  `chunk_id` (`{document_id}_{chunk_index}`).
- **Technology:** plain Python dict/Pydantic model.
- **Failure modes:** missing `knowledge_base_id` — treated as a programming
  error (raised, not silently defaulted), since it is the isolation
  boundary (NFR-004).
- **Validation:** schema validation via Pydantic; ADR-14's rule that
  `knowledge_base_id` has no default value anywhere in the write path.

### 5. Embedding

- **Input:** chunk text strings (batched).
- **Processing:** local inference via `sentence-transformers`, batched (e.g.
  32 chunks per batch) to bound peak memory on the free-tier instance.
- **Output:** 384-dim float vector per chunk.
- **Technology:** `sentence-transformers/all-MiniLM-L6-v2` (ADR-06), CPU.
- **Failure modes:** out-of-memory on a very large batch (mitigated by
  batching); model not yet loaded on a cold start (first request pays load
  latency — model is loaded once at process startup, not per-request, to
  avoid repeating this cost).
- **Validation:** unit test checks output vector dimensionality (384) and
  that identical input text yields identical (deterministic) vectors.

### 6. Vector Storage

- **Input:** `(chunk_id, vector, payload)` tuples.
- **Processing:** upsert into the single shared Qdrant collection
  (ADR-14), keyed by `chunk_id` (idempotent — re-processing the same
  document overwrites rather than duplicates).
- **Output:** write acknowledgment; document status transitions toward
  `READY` once all its chunks are upserted.
- **Technology:** Qdrant Cloud (ADR-07), cosine distance.
- **Failure modes:** Qdrant unreachable/timeout → document marked `FAILED`
  with a retriable reason (distinct from an extraction failure, per
  FR-055); partial upsert (some chunks written, connection drops) → the
  whole document is re-upserted on retry (idempotent keys make this safe).
- **Validation:** integration test upserts then immediately queries by
  `document_id` filter and asserts the expected chunk count is present.

### 7. Query Embedding

- **Input:** the user's chat message text.
- **Processing:** same `embed_texts()` function as Stage 5, single input.
- **Output:** one 384-dim vector.
- **Technology:** same as Stage 5 (shared code path — guarantees query and
  document vectors live in the same embedding space).
- **Failure modes:** empty/whitespace-only message → rejected at the API
  layer before reaching this stage (NFR-006).
- **Validation:** same unit test as Stage 5 covers this path.

### 8. Similarity Search

- **Input:** query vector, `knowledge_base_id`, `top_k`.
- **Processing:** Qdrant search with a mandatory payload filter
  `knowledge_base_id == <value>` (never optional — ADR-14) and cosine
  similarity scoring.
- **Output:** up to `top_k` `(chunk_id, score, payload)` results, sorted
  descending by score.
- **Technology:** Qdrant Cloud search API.
- **Failure modes:** knowledge base has zero chunks (empty KB, FR-056) →
  empty result set, handled by Stage 10's no-context path; Qdrant timeout →
  surfaced as a retriable chat error (FR-055).
- **Validation:** the KB-isolation test (docs/TEST_STRATEGY.md) asserts a
  query against KB A's filter never returns a chunk whose payload
  `knowledge_base_id` is B.

### 9. Top-K Retrieval

- **Input:** search results from Stage 8.
- **Processing:** apply a minimum-similarity-score threshold in addition to
  `top_k`, so low-relevance results are excluded even if fewer than `top_k`
  chunks are returned.
- **Output:** filtered list of "usable" chunks (may be empty).
- **Configuration:**
  - Top-K: **5**
  - Minimum cosine similarity threshold: **0.35** (tuned empirically against
    the evaluation set in `docs/RAG_EVALUATION.md`; documented as
    configurable, not hard-coded magic)
- **Failure modes:** threshold set too high/low is a tuning problem, not a
  runtime failure — surfaced via the evaluation suite's groundedness metric.
- **Validation:** `docs/RAG_EVALUATION.md` no-context evaluation cases.

### 10. Context Construction

- **Input:** usable chunks from Stage 9.
- **Processing:** if the usable-chunk list is empty, short-circuit directly
  to the fixed "not enough information in this knowledge base" response
  (FR-022) — **the LLM is never called** in this case, both to guarantee the
  no-context guarantee and to save free-tier LLM quota. Otherwise, concatenate
  chunk texts in descending-score order, each labeled with a citation marker
  (`[1]`, `[2]`, …) tied to its source metadata.
- **Output:** a context string + an ordered citation-index → chunk-metadata
  map.
- **Technology:** plain Python string templating.
- **Failure modes:** combined context exceeds the model's practical context
  budget — mitigated by Stage 9's `top_k=5` cap at ~800 chars/chunk
  (≈4,000 chars ≈ 1,000 tokens), far under Groq's context window.
- **Validation:** unit test asserts citation markers in the constructed
  context match 1:1 with the citation-index map.

### 11. Prompt

- **Input:** context string + citation map + user question.
- **Processing:** a fixed system prompt instructs the model to: answer only
  from the provided context, cite using the bracket markers, and explicitly
  say it cannot answer if the context is insufficient (defense-in-depth
  alongside Stage 10's short-circuit, since a marginal-relevance context
  can still be topically off).
- **Output:** final prompt (system + user turn) sent to the LLM.
- **Technology:** plain string template, versioned in code
  (`retrieval/generation.py`).
- **Failure modes:** prompt-injection attempts embedded in a user-uploaded
  document's text (e.g. "ignore previous instructions") — acknowledged and
  mitigated in `docs/SECURITY.md`; the system prompt frames retrieved
  context as *data to reference*, not *instructions to follow*.
- **Validation:** `docs/RAG_EVALUATION.md` groundedness + hallucination
  cases; `docs/TEST_STRATEGY.md` includes an adversarial-context test.

### 12. LLM

- **Input:** the constructed prompt.
- **Processing:** call Groq's chat completion API (`qwen/qwen3.8-27b` — see
  ADR-08 for why this replaced the originally-planned `llama-3.3-70b-versatile`,
  which Groq had removed from its catalog by the time this was verified
  against the real API), temperature low (0.1–0.2) to favor extractive,
  grounded answers over creative ones.
- **Output:** raw answer text.
- **Technology:** Groq API (ADR-08).
- **Failure modes:** rate limit exceeded, timeout, network error, malformed
  response — all mapped to the single retriable chat-error path (FR-054);
  no raw provider error is passed to the client.
- **Validation:** integration test with a mocked Groq client covers each
  failure mode's mapped response.

### 13. Answer

- **Input:** raw LLM answer text.
- **Processing:** pass through largely as-is; light post-processing only to
  normalize whitespace.
- **Output:** final answer string shown to the user.
- **Technology:** plain Python.
- **Failure modes:** model ignores citation instructions and returns no
  bracket markers — handled by Stage 14 falling back to "all chunks that
  were in context" as the citation set rather than failing the response.
- **Validation:** `docs/RAG_EVALUATION.md` answer-relevance evaluation.

### 14. Source Attribution

- **Input:** answer text + citation-index map from Stage 10.
- **Processing:** parse bracket markers actually present in the answer text
  and resolve each to its chunk metadata (document name, page/chunk locator).
  If no markers are found in the answer (model omitted them), attribute all
  chunks that were included in the prompt context (safe fallback — never
  fabricate a citation not present in Stage 10's map).
- **Output:** `sources[]` array: `{document_id, document_name, page_or_chunk,
  snippet}`, matching `docs/DATA_MODEL.md` → SourceReference and
  `docs/API.md`'s `/chat` response schema.
- **Technology:** plain Python (regex on bracket markers).
- **Failure modes:** none beyond the fallback above; this stage cannot
  reference a chunk absent from Stage 10's map (FR-041 is enforced
  structurally, not just by convention).
- **Validation:** unit test asserts every citation in `sources[]` maps to a
  `chunk_id` that was actually present in the prompt for that request.

## Configuration Summary

| Parameter | Value | Rationale |
|---|---|---|
| Chunk size | 800 characters | Balances context precision vs. chunk count on a 5MB/file cap |
| Chunk overlap | 120 characters (15%) | Reduces boundary information loss without excessive duplication |
| Embedding model | `all-MiniLM-L6-v2` (384-dim) | Zero-cost, no rate limit (ADR-06) |
| Distance metric | Cosine similarity | Standard for normalized sentence embeddings |
| Top-K | 5 | Enough diversity for citation without exceeding LLM context budget |
| Min similarity threshold | 0.35 | Empirically tuned against `docs/RAG_EVALUATION.md` dataset |
| LLM | Groq `qwen/qwen3.8-27b` | Free, fast, no card required, non-reasoning (ADR-08) |
| LLM temperature | 0.1–0.2 | Favor grounded/extractive answers |
| Context budget | ≈5 chunks × 800 chars ≈ 4,000 chars | Comfortably inside Groq free-tier TPM limits |

## Grounding Strategy

Groundedness is enforced at three independent layers, so a failure in one
does not silently produce an ungrounded answer:

1. **Retrieval gate (Stage 9–10):** below-threshold retrieval never reaches
   the LLM at all.
2. **Prompt instruction (Stage 11):** explicit instruction to answer only
   from context and to decline if insufficient.
3. **Citation fallback (Stage 14):** attribution is derived only from chunks
   structurally present in that request's prompt — a citation cannot
   reference anything the model wasn't actually given.

Measured effectiveness of this strategy is the subject of
`docs/RAG_EVALUATION.md` (groundedness and hallucination metrics).
