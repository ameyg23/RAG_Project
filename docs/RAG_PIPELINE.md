# RAG Pipeline Specification

Full path: **Document → Extraction → Cleaning → Chunking → Metadata →
Embedding → Vector storage → Query rewriting → Query embedding → Similarity
search → Reranking → Top-K retrieval → Context construction → Prompt → LLM →
Answer → Source attribution.**

Technology choices are justified in `docs/ARCHITECTURE_DECISIONS.md`
(ADR-05, ADR-06, ADR-07, ADR-08, ADR-16, ADR-17). This document defines
behavior, not rationale.

Stages are numbered 1–14 for historical continuity with existing code
comments (`backend/retrieval/*.py`, `backend/ingestion/embed.py`) that cite
specific stage numbers; the two additions from ADR-16/ADR-17 are inserted
as **Stage 6.5** (Query Rewriting) and **Stage 8.5** (Reranking) rather than
renumbering 7–14, so those existing comments stay accurate.

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
- **Technology:** `sentence-transformers/BAAI/bge-small-en-v1.5` (ADR-06;
  this document previously said `all-MiniLM-L6-v2`, which was the originally
  planned model — a later migration swapped to BGE to fix short-document/
  resume recall, and this doc was not updated at the time. Corrected here;
  see ADR-06's model note and `backend/retrieval/retriever.py`'s docstring
  for the full empirical record), CPU.
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

### 6.5. Query Rewriting

*(New — ADR-16. Sits between the ingestion-side pipeline, Stages 1–6, and
the query-side pipeline, Stages 7–14, since it is the first thing that
happens to a user's message before anything else touches it.)*

- **Input:** the user's raw chat `message`, plus `conversation_history`
  (optional, ≤8 entries of `{role, content}`, from the `/chat` request body
  — see `docs/API.md`).
- **Processing:** if `conversation_history` is empty (thread's first
  message), skip this stage entirely — pass `message` through unchanged.
  Otherwise, call Groq (same client/model as Stage 12, different prompt) via
  `retrieval/query_rewrite.py`, asking it to rewrite `message` into a fully
  standalone question given the history, or return it unchanged if it's
  already standalone.
- **Output:** `rewritten_query` (string) — used by **both** Stage 7 (query
  embedding, and therefore Stage 8's similarity search and Stage 8.5's
  reranking) and Stage 11 (the `QUESTION:` fed into the generation prompt).
  The user's original `message` text is untouched — it is what the frontend
  displays in the chat thread and what gets sent back as a
  `conversation_history` entry on the *next* turn (never the rewritten
  text, to avoid rewrite-of-a-rewrite drift across a long thread).
- **Technology:** Groq chat-completion call, `temperature≈0.0`,
  `max_tokens≈100` (short output only).
- **Failure modes:** Groq request fails/times out (same failure class as
  Stage 12) → does **not** raise the request's `502 LLM_UNAVAILABLE` error;
  falls back to using the raw `message` as `rewritten_query` (i.e. behaves
  as if this stage didn't exist for this one request), logged server-side
  (NFR-009). This stage is an internal retrieval-quality enhancement, not
  the user-facing "answer service" contract Stage 12's failure mode covers.
- **Validation:** `docs/RAG_EVALUATION.md`'s dataset needs a multi-turn case
  category to exercise this stage (follow-up-with-pronoun cases) —
  implementation-phase task for RAG/QA, not yet present in
  `evaluation/dataset/demo_kb_cases.json`.

### 7. Query Embedding

- **Input:** `rewritten_query` from Stage 6.5 (equal to the raw `message`
  when Stage 6.5 was skipped or failed over).
- **Processing:** same `embed_texts()` function as Stage 5, single input.
- **Output:** one 384-dim vector.
- **Technology:** same as Stage 5 (shared code path — guarantees query and
  document vectors live in the same embedding space).
- **Failure modes:** empty/whitespace-only message → rejected at the API
  layer before reaching this stage (NFR-006).
- **Validation:** same unit test as Stage 5 covers this path.

### 8. Similarity Search

*(Modified — ADR-17: `top_k` widened from a final-answer count to a
reranker candidate-pool size; the similarity threshold's role changes from
"final relevance gate" to "cheap pre-filter." See Stage 8.5/9.)*

- **Input:** query vector (Stage 7, embedding `rewritten_query`),
  `knowledge_base_id`, `top_k`.
- **Processing:** Qdrant search with a mandatory payload filter
  `knowledge_base_id == <value>` (never optional — ADR-14) and cosine
  similarity scoring; results below `MIN_SIMILARITY_SCORE` are excluded here
  as a cheap pre-filter, before the more expensive Stage 8.5 reranker runs
  on the survivors.
- **Output:** up to `top_k` `(chunk_id, score, payload)` candidate results,
  sorted descending by cosine score (this order is provisional — Stage 8.5
  re-sorts by rerank score).
- **Configuration:**
  - Candidate-pool `top_k`: **20** (widened from the pre-ADR-17 value of 5,
    which was sized for "final chunks shown to the LLM," not "candidates
    for a reranker to choose among")
  - `MIN_SIMILARITY_SCORE`: **0.45** (unchanged value from the BGE
    migration — see ADR-06's model note and `retriever.py`'s docstring for
    its empirical derivation; now a pre-filter, not the final gate)
- **Technology:** Qdrant Cloud search API.
- **Failure modes:** knowledge base has zero chunks (empty KB, FR-056) →
  empty result set, handled by Stage 10's no-context path; Qdrant timeout →
  surfaced as a retriable chat error (FR-055).
- **Validation:** the KB-isolation test (docs/TEST_STRATEGY.md) asserts a
  query against KB A's filter never returns a chunk whose payload
  `knowledge_base_id` is B.

### 8.5. Reranking

*(New — ADR-17.)*

- **Input:** up to 20 candidate chunks from Stage 8, plus `rewritten_query`
  (the same standalone query text used for Stage 7's embedding — not the
  raw original message, for the same referent-resolution reason ADR-16
  applies it everywhere else).
- **Processing:** score each `(rewritten_query, chunk.text)` pair with a
  local cross-encoder (`CrossEncoder.predict`); re-sort the candidate list
  descending by this new rerank score, discarding the Stage 8 cosine
  ordering (it was provisional).
- **Output:** the same candidate chunks, re-scored and re-ordered.
- **Technology:** `sentence-transformers`'s `CrossEncoder` class,
  `cross-encoder/ms-marco-MiniLM-L-6-v2` (ADR-17) — zero new dependency,
  loaded once per process (mirrors Stage 5/7's model-loading pattern).
- **Failure modes:** none beyond a process-level model-load failure (same
  class as Stage 5's embedding model failing to load — treated as a startup
  problem, not a per-request one).
- **Validation:** `docs/RAG_EVALUATION.md`'s `no_context_precision` metric
  is the primary acceptance signal (target: recover from the documented 0.6
  regression toward the ≥0.90 target) — measured, not assumed, per ADR-17.

### 9. Top-K Retrieval

*(Modified — ADR-17: the gating threshold and its input both change from
Stage 8's cosine score to Stage 8.5's rerank score.)*

- **Input:** reranked results from Stage 8.5.
- **Processing:** apply `MIN_RERANK_SCORE` (a new threshold, on the
  cross-encoder's score — **not** cosine similarity, and not
  numerically comparable to `MIN_SIMILARITY_SCORE`) in addition to a final
  `top_n` cap, so low-relevance results are excluded even if fewer than
  `top_n` chunks remain.
- **Output:** filtered list of "usable" chunks (may be empty) — this is now
  the structural basis for Stage 10's no-context decision.
- **Configuration:**
  - Final `top_n`: **5** (kept equal to the pre-ADR-17 value to preserve
    Stage 10's ~4,000-char context budget; a candidate for QA to lower once
    reranking's precision improvement is measured)
  - `MIN_RERANK_SCORE`: **not yet set** — must be empirically tuned against
    `docs/RAG_EVALUATION.md`'s dataset once the reranker is implemented,
    following the same measure-first process `retriever.py`'s docstring
    documents for `MIN_SIMILARITY_SCORE`'s own 0.35→0.45 retuning. This is
    an implementation-phase task, not an architectural decision made in the
    abstract (ADR-17).
- **Failure modes:** threshold set too high/low is a tuning problem, not a
  runtime failure — surfaced via the evaluation suite's groundedness and
  `no_context_precision` metrics.
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

- **Input:** context string + citation map + `rewritten_query` (Stage 6.5's
  output — the standalone question, not necessarily the user's raw
  original wording; see ADR-16 for why the generation step uses the same
  rewritten text retrieval does).
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
  fabricate a citation not present in Stage 10's map). **(ADR-18)** For each
  *distinct* `document_id` among the resolved sources, check whether it still
  has any chunks in the vector store right now (`vector_store.count_chunks_for_document`) —
  demo documents (`store.is_demo_document_id`) are exempt, being permanent —
  and set `is_removed` accordingly (FR-042). This is a real check, not a
  stub: it exists because a document can be deleted (`DELETE /documents/{id}`)
  concurrently with an in-flight chat request that already retrieved chunks
  from it. If this check itself fails (vector-store hiccup), log server-side
  and fall back to `is_removed: False` for the affected source(s) rather than
  failing the whole response — the same graceful-degrade philosophy Stage
  6.5's rewrite-failure fallback already established.
- **Output:** `sources[]` array: `{document_id, document_name, page_or_chunk,
  snippet, is_removed}`, matching `docs/DATA_MODEL.md` → SourceReference and
  `docs/API.md`'s `/chat` response schema.
- **Technology:** plain Python (regex on bracket markers); one Qdrant count
  query per distinct cited document for the `is_removed` check.
- **Failure modes:** none beyond the fallbacks above; this stage cannot
  reference a chunk absent from Stage 10's map (FR-041 is enforced
  structurally, not just by convention).
- **Validation:** unit test asserts every citation in `sources[]` maps to a
  `chunk_id` that was actually present in the prompt for that request; a
  second test deletes a cited document mid-request (or mocks the count to
  0) and asserts `is_removed: true` on exactly that source.

## Streaming Progress Reporting (ADR-18)

`POST /chat` reports real-time progress by yielding one NDJSON event as each
stage boundary below is actually crossed — see ADR-18 for the full wire
format, error taxonomy, and frontend consumption design. This section only
maps stage numbers to the four UI-visible progress labels:

| UI stage | Pipeline stages covered |
|---|---|
| `SEARCHING` | 6.5 (query rewrite) → 7 (query embedding) → 8 (candidate-pool vector search) |
| `RETRIEVING` | 8.5 (rerank) → 9 (threshold + cap) |
| `GENERATING` | 10 (context construction) → 11 (prompt) → 12 (LLM call) |
| `VALIDATING` | 13 (answer) → 14 (source attribution, including the new FR-042 existence check above) |

No stage's internal logic, ordering, scoring, or thresholding changes because
of this — the yields sit *between* existing steps, purely for progress
visibility.

## Configuration Summary

| Parameter | Value | Rationale |
|---|---|---|
| Chunk size | 800 characters | Balances context precision vs. chunk count on a 5MB/file cap |
| Chunk overlap | 120 characters (15%) | Reduces boundary information loss without excessive duplication |
| Embedding model | `BAAI/bge-small-en-v1.5` (384-dim) | Zero-cost, no rate limit (ADR-06); corrected from the stale `all-MiniLM-L6-v2` entry this table previously carried |
| Distance metric | Cosine similarity | Standard for normalized sentence embeddings |
| Candidate-pool Top-K (Stage 8) | 20 | Wide enough recall for the reranker to have real choices among (ADR-17) |
| Min similarity threshold (Stage 8, cheap pre-filter) | 0.45 | Empirically tuned for BGE against `docs/RAG_EVALUATION.md` dataset (`retriever.py` docstring); no longer the final relevance gate (ADR-17) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Zero-cost, zero new dependency, local CPU (ADR-17) |
| Min rerank threshold (Stage 9, final gate) | *TBD — empirical* | Replaces cosine threshold as the no-context arbiter (ADR-17) |
| Final Top-N (Stage 9, to LLM) | 5 | Preserves existing context budget; QA may lower after reranking (ADR-17) |
| Query rewriting | Groq, 2nd call, `temperature≈0.0`, `max_tokens≈100` | Resolves follow-up pronouns before embedding/generation (ADR-16) |
| LLM | Groq `qwen/qwen3.8-27b` | Free, fast, no card required, non-reasoning (ADR-08) |
| LLM temperature | 0.1–0.2 | Favor grounded/extractive answers |
| Context budget | ≈5 chunks × 800 chars ≈ 4,000 chars | Comfortably inside Groq free-tier TPM limits |

## Grounding Strategy

Groundedness is enforced at three independent layers, so a failure in one
does not silently produce an ungrounded answer:

1. **Retrieval gate (Stage 8–10):** Stage 8's similarity threshold is now a
   cheap pre-filter only; the actual gate is Stage 9's rerank-score
   threshold (ADR-17), which is expected to be meaningfully more precise
   than cosine similarity alone at telling "topically adjacent" apart from
   "actually answers this." Below-threshold retrieval never reaches the LLM
   at all, same as before.
2. **Prompt instruction (Stage 11):** explicit instruction to answer only
   from context and to decline if insufficient.
3. **Citation fallback (Stage 14):** attribution is derived only from chunks
   structurally present in that request's prompt — a citation cannot
   reference anything the model wasn't actually given.

Measured effectiveness of this strategy is the subject of
`docs/RAG_EVALUATION.md` (groundedness and hallucination metrics).
