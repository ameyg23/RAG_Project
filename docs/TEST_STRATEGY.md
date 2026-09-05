# Test Strategy

Defines testing at four levels, plus explicit scenario coverage per
functional area. Complements — but is distinct from — RAG quality
evaluation (`docs/RAG_EVALUATION.md`), which is never a CI pass/fail gate on
every commit (it depends on live free-tier LLM calls and is run on a slower
cadence).

## 1. Unit Testing

Scope: pure functions and small modules, no network calls.

- **Extraction** (`docs/RAG_PIPELINE.md` §1) — one test per format (PDF,
  DOCX, TXT, MD) against a small fixture file; assert correct text and,
  for PDF, correct per-page splitting.
- **Cleaning** (§2) — assert idempotence (cleaning already-clean text is a
  no-op) and that whitespace/control-character normalization doesn't alter
  meaningful content.
- **Chunking** (§3) — assert every chunk ≤ 800 chars + tolerance, assert
  120-char overlap is present between consecutive chunks, assert
  concatenating chunks (minus overlap) reconstructs the cleaned input.
- **Embedding** (§5/§7) — assert output vector dimensionality is 384, assert
  determinism (same input text → same vector, byte-for-byte or within
  floating-point tolerance).
- **Citation-marker parsing** (§14) — assert bracket markers (`[1]`, `[2]`)
  in a model's answer resolve to the correct chunk metadata; assert the
  fallback (all context chunks cited) triggers when no markers are present.
- **Pydantic schema validation** — one test per request/response model in
  `docs/API.md`, covering both valid and invalid payload shapes.

## 2. API / Integration Testing

Scope: one FastAPI test client run per endpoint in `docs/API.md`, using a
mocked Groq adapter and a real (local/dockerized or a disposable Qdrant
Cloud test cluster) vector store — mocking happens at the adapter interface
(`retrieval/vector_store.py`, `retrieval/generation.py`), not at raw HTTP,
so tests exercise real request/response wiring without depending on live
external quota.

Per endpoint:
- `GET /health` — happy path (`ok`) and degraded path (vector store
  unreachable, mocked).
- `GET /knowledge-bases` — returns demo KB always; returns user KB only
  when a valid session token owns one.
- `GET /knowledge-bases/{id}/documents` — happy path, `403` (wrong session),
  `404` (unknown id).
- `POST /documents/upload` — happy path (1–5 valid files), and one test per
  validation failure: 0 files, 6 files, oversized file, wrong type — assert
  the **whole batch** is rejected (no partial acceptance) per the documented
  validation order (count → size → type).
- `GET /documents/{id}/status` — happy path for each status value, `403`,
  `404`.
- `DELETE /documents/{id}` — happy path (chunks removed from vector store,
  verified via a follow-up query), `403` for wrong session, `403`
  unconditionally for any `kb_demo` document, `404`.
- `POST /chat` — happy path (grounded answer with sources), no-context path
  (empty `sources[]`, fixed answer text), `400` (empty message), `403`
  (session mismatch), `404` (unknown KB), `502` (mocked Groq client raises),
  `503` (KB with zero ready documents).

## 3. RAG Testing

Scope: retrieval and grounding behavior specifically, using seeded test
knowledge bases (not the demo KB, to keep RAG tests independent of demo
content changes).

- **Retrieval precision** — given a known question and a seeded KB
  containing the answer, assert the expected document appears in the
  top-K results.
- **Similarity-threshold behavior** — seed a KB with only off-topic content
  relative to a probe question; assert the 0.35 minimum-similarity cutoff
  (`docs/RAG_PIPELINE.md` §9) excludes all results, triggering the
  no-context path.
- **Citation-to-context consistency** — assert every citation returned in
  `sources[]` corresponds to a chunk that was structurally present in that
  request's prompt (regression test for the Stage 14 guarantee in
  `docs/RAG_PIPELINE.md` — a citation must never reference a chunk absent
  from context, even if a future change to the prompt-construction code
  introduces a bug).

Broader groundedness/relevance/hallucination measurement (which requires
judging answer quality, not just structural correctness) is the subject of
`docs/RAG_EVALUATION.md`, not this test suite.

## 4. End-to-End Testing

Scope: a small number of full user journeys, driven over HTTP against a
running backend (and, where practical, a built frontend or headless
browser), matching `docs/REQUIREMENTS.md` §3:

1. **Explore the demo** — land on the app, ask a suggested question, see a
   cited answer.
2. **Upload and chat** — upload a valid document, poll until `READY`, ask a
   question answered from it.
3. **Inspect sources** — ask a question, verify the returned citation's
   document name and locator match the actual seeded content.
4. **Recover from a bad upload** — attempt an oversized/wrong-type upload,
   verify the rejection message, then submit a valid one successfully.

Kept intentionally minimal (four scenarios) rather than exhaustive, given
this project's scale — deeper coverage lives in the API/integration and RAG
test layers above.

## Scenario Coverage by Functional Area

**File validation** (FR-010, FR-011, FR-012, FR-050–052): oversized file
(6MB), wrong type (`.exe`), 6 files in one request, boundary cases (exactly
5 files, exactly 5,242,880 bytes).

**Upload** (FR-010, FR-013): successful multi-file upload; first upload
from a fresh session correctly creates/derives that session's
`knowledge_base_id`.

**Processing** (FR-014, FR-053, `docs/DOCUMENT_PROCESSING.md`): full
`UPLOADED → PROCESSING → READY` transition; `PROCESSING → FAILED` for a
corrupted file and for a scanned/empty-text PDF, each asserting the correct
distinct `failure_reason` string.

**Retrieval** (`docs/RAG_PIPELINE.md` §7–9): correct top-K ordering by
score; threshold correctly excludes low-relevance chunks even when
`top_k` would otherwise be satisfied by weak matches.

**Source attribution** (FR-040, FR-041, FR-042): citation locator
correctness (right page/chunk); citation set never exceeds the chunks
actually placed in context; a citation to a subsequently deleted document
renders with `is_removed: true` rather than erroring.

**Chat** (FR-020–023): a chat request is always scoped to exactly one
`knowledge_base_id`; assert no server-side chat-message store exists at all
(a structural/architecture test — e.g. asserting no such table/collection
is queried or written by the `/chat` handler), consistent with FR-023.

**No-context questions** (FR-022): a question with no relevant content in
the active KB returns the fixed "not enough information" response, and the
**mocked LLM client is asserted to never have been invoked** for that
request (verifies the retrieval-gate short-circuit in
`docs/RAG_PIPELINE.md` §10, not just the returned text).

**Hallucination handling:** an adversarial case (retrieved context
topically close but insufficient to actually answer) is primarily validated
through `docs/RAG_EVALUATION.md`'s groundedness/hallucination metrics, not
unit tests — this test suite only asserts the structural guarantees
(retrieval gate, citation-to-context consistency) that make hallucination
*detectable*, not the semantic judgment of whether a given answer is
actually grounded.

**LLM failures** (FR-054): mocked Groq client raises timeout, connection
error, and malformed-response cases; assert each maps to the sanitized
`502 LLM_UNAVAILABLE` response, never a raw exception.

**Knowledge-base isolation** (NFR-004, ADR-14): seed two knowledge bases
(A and B) with **near-duplicate, semantically similar content** (not just
unrelated content — a trivial test would pass even with a broken filter);
assert a query scoped to KB A never returns a chunk whose payload
`knowledge_base_id` is B, and vice versa.

## Evaluation Strategy (Explicit Separation)

RAG *quality* (groundedness, answer relevance, hallucination rate,
no-context precision) is **not measured by this test suite**. It is defined
and measured entirely in `docs/RAG_EVALUATION.md` and the `evaluation/`
directory, which:

- Runs against a real, running backend over HTTP (black-box), not by
  importing backend internals.
- Depends on live LLM calls (Groq) and is therefore rate-limit-sensitive —
  it is run on a separate, slower cadence (e.g. before a release, not on
  every commit), never as a required CI gate.
- Produces scored results, not pass/fail unit assertions — see
  `docs/RAG_EVALUATION.md` for metrics and thresholds.

## Acceptance Criteria Check

- **Every major functional requirement has test coverage planned:** every
  FR/NFR ID referenced above traces to at least one test in one of the four
  levels.
- **Negative cases are included:** every endpoint's documented error status
  codes have a corresponding test; every document-processing failure mode
  has a corresponding test.
- **RAG-specific testing is included:** §3 covers retrieval precision,
  threshold behavior, and citation-consistency specifically.
- **Evaluation is separate from normal application functionality:** see
  the explicit separation section above — evaluation never blocks a normal
  test run and is not scored as pass/fail unit assertions.
