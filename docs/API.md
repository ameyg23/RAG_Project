# API Contract

All endpoints are served by the FastAPI backend (`ARCHITECTURE.md` §3). No
endpoint requires authentication in the traditional sense; user-KB endpoints
require a session token (ADR-14, ADR-15). All request/response bodies are
JSON unless noted. All error responses share the shape:

```json
{ "error": { "code": "STRING_CODE", "message": "Human-readable, no internals" } }
```

(see `docs/SECURITY.md` for the error-sanitization rule this satisfies).

---

## `GET /health`

**Purpose:** liveness check; also the first place a session token is issued
if the client has none.

**Auth:** none required.

**Request:** no body. Optional header `X-Session-Token` if the client
already has one.

**Response 200:**
```json
{
  "status": "ok",
  "session_token": "3f1b1e0a-...-c9",
  "vector_store": "connected"
}
```

**Response 200 (degraded):**
```json
{
  "status": "degraded",
  "session_token": "3f1b1e0a-...-c9",
  "vector_store": "unreachable"
}
```

**Status codes:** `200` always (degraded state is signaled in the body, not
via HTTP status, since the endpoint itself succeeded). No error responses.

**Rate limiting:** none in V1 (cheap, side-effect-free beyond token issuance).

---

## `GET /knowledge-bases`

**Purpose:** list knowledge bases visible to the caller — always includes
the demo KB, plus the caller's own KB if it has been created.

**Auth:** `X-Session-Token` optional; if present and it owns a KB, that KB is
included.

**Request:** no body.

**Response 200:**
```json
{
  "knowledge_bases": [
    {
      "knowledge_base_id": "kb_demo",
      "kind": "demo",
      "name": "Demo: Company Handbook",
      "document_count": 4,
      "suggested_questions": [
        "How many days of PTO do full-time employees accrue per year?",
        "What pricing tiers does Beacon offer?"
      ]
    },
    {
      "knowledge_base_id": "kb_user_9c2a...",
      "kind": "user",
      "name": "Your documents",
      "document_count": 2,
      "suggested_questions": []
    }
  ]
}
```

**Status codes:** `200` only.

**Validation:** none (read-only, no input).

**Rate limiting:** none in V1.

---

## `GET /knowledge-bases/{id}/documents`

**Purpose:** list documents (and their status) within one knowledge base.

**Auth:** demo KB readable by anyone; a `kb_user_*` ID requires
`X-Session-Token` matching the owning session.

**Request:** no body. Path param `id`.

**Response 200:**
```json
{
  "knowledge_base_id": "kb_user_9c2a...",
  "documents": [
    {
      "document_id": "d1f0...",
      "filename": "handbook.pdf",
      "file_type": "pdf",
      "size_bytes": 2148213,
      "status": "READY",
      "failure_reason": null,
      "uploaded_at": "2026-09-04T18:02:11Z",
      "chunk_count": 12
    }
  ]
}
```

**Status codes:**
- `200` success
- `403` — session token does not own this `kb_user_*` ID
- `404` — unknown `knowledge_base_id`

**Error response example (403):**
```json
{ "error": { "code": "FORBIDDEN_KNOWLEDGE_BASE", "message": "You do not have access to this knowledge base." } }
```

**Rate limiting:** none in V1.

---

## `POST /documents/upload`

**Purpose:** upload 1–5 files to (implicitly create, if first upload) the
caller's user knowledge base.

**Auth:** requires `X-Session-Token` (issued via `/health` if missing —
client is expected to have called `/health` first; if the header is absent,
the backend issues a new token and returns it in the response so the client
can persist it, rather than hard-failing).

**Request:** `multipart/form-data`, field name `files`, 1–5 file parts.

**Response 202:**
```json
{
  "session_token": "3f1b1e0a-...-c9",
  "knowledge_base_id": "kb_user_9c2a...",
  "documents": [
    { "document_id": "d1f0...", "filename": "handbook.pdf", "status": "UPLOADED" },
    { "document_id": "d2a1...", "filename": "notes.txt", "status": "UPLOADED" }
  ]
}
```

**Status codes:**
- `202 Accepted` — files passed validation, processing started in background
- `400` — validation failure (see below); **no files are accepted** if any
  file in the batch fails validation — the whole batch is rejected so the
  client sees one clear error rather than partial success (simpler UX; see
  `docs/UI_UX.md` upload state)
- `413` — total request body exceeds server limit (defense-in-depth beyond
  per-file check)

**Validation (checked before any processing starts):**
- File count: 1–5 (else `400 TOO_MANY_FILES` / `NO_FILES_PROVIDED`)
- Per-file size: ≤ 5,242,880 bytes (else `400 FILE_TOO_LARGE`, includes
  filename)
- File type: extension/MIME must resolve to pdf/docx/txt/md (else `400
  UNSUPPORTED_FILE_TYPE`, includes filename and supported list)

**Error response example (400):**
```json
{
  "error": {
    "code": "FILE_TOO_LARGE",
    "message": "\"scan.pdf\" is 7.2MB; the limit is 5MB per file."
  }
}
```

**Rate limiting:** none enforced in V1 beyond the natural cost of Groq/Qdrant
free-tier caps; documented as a risk in `docs/SECURITY.md`.

---

## `GET /documents/{id}/status`

**Purpose:** poll a single document's processing status (FR-014).

**Auth:** same ownership rule as the documents-list endpoint.

**Request:** no body. Path param `id`.

**Response 200:**
```json
{
  "document_id": "d1f0...",
  "status": "PROCESSING",
  "failure_reason": null
}
```

**Response 200 (failed):**
```json
{
  "document_id": "d1f0...",
  "status": "FAILED",
  "failure_reason": "No extractable text found (file may be a scanned image)."
}
```

**Status codes:**
- `200` success
- `403` — not the owning session
- `404` — unknown `document_id`

**Rate limiting:** client is expected to poll at a bounded interval (e.g.
every 2s); documented as a client-side responsibility, no server throttle in
V1.

---

## `DELETE /documents/{id}`

**Purpose:** delete a user-uploaded document and its chunks (FR-015).

**Auth:** requires `X-Session-Token` matching the owning session; **the demo
KB's documents can never be deleted via this endpoint** (returns `403`
unconditionally for any `document_id` belonging to `kb_demo`).

**Request:** no body. Path param `id`.

**Response 200:**
```json
{ "document_id": "d1f0...", "deleted": true }
```

**Status codes:**
- `200` success — all chunks for this document removed from Qdrant
- `403` — not the owning session, or target belongs to the demo KB
- `404` — unknown `document_id`

**Rate limiting:** none in V1.

---

## `POST /chat`

**Purpose:** ask a question against exactly one knowledge base (FR-020,
FR-021).

**Auth:** demo KB requires no token; a `kb_user_*` target requires
`X-Session-Token` matching the owner.

**Response shape (ADR-18):** this endpoint streams. Everything checkable
*before* the RAG pipeline starts (unknown/forbidden `knowledge_base_id`,
empty KB, invalid `message`) is still a plain, non-streamed JSON error
response with a normal HTTP status — identical to before ADR-18, since none
of that needs progress reporting. Once those checks pass, the response is
`media_type: application/x-ndjson`, HTTP `200`, body = one JSON object per
line (`\n`-terminated), each carrying real-time pipeline progress ending in
exactly one terminal event (`COMPLETED` or `ERROR`). See ADR-18 for the full
design rationale, the stage-to-pipeline-code mapping, and the error taxonomy.

**Request:**
```json
{
  "knowledge_base_id": "kb_demo",
  "message": "What is the company's vacation policy?"
}
```

**Request (follow-up turn, with conversation history — ADR-16):**
```json
{
  "knowledge_base_id": "kb_demo",
  "message": "What about their vacation days?",
  "conversation_history": [
    { "role": "user", "content": "Tell me about the engineering team's benefits" },
    { "role": "assistant", "content": "Engineering employees get a 401(k) match [1] and full health coverage [2]." }
  ]
}
```
- `conversation_history` (optional, default `[]`): recent prior turns of
  *this same thread*, each `{ "role": "user" | "assistant", "content": string }`.
  Sent by the frontend so the backend can resolve a follow-up question
  (e.g. a pronoun like "their"/"it") into a standalone query before
  retrieval — see `docs/RAG_PIPELINE.md` Stage 6.5 and ADR-16. The backend
  does **not** persist this field anywhere; it is used only for the
  duration of handling this one request, consistent with this project's
  stateless-backend design (ADR-12) — it is not a new form of server-side
  chat memory, and does not enable memory across browser sessions/devices
  (`docs/REQUIREMENTS.md` §12 is unaffected).
- **Client convention:** the frontend sends the last 3 exchanges (≤6
  entries) preceding the current `message`, which itself stays a separate
  top-level field, not part of the array.
- **Server validation (NFR-006):** hard cap of 8 entries regardless of what
  is sent; each entry's `content` capped at 2,000 characters, same limit as
  `message`.
- **Omitted or empty `conversation_history`** (e.g. the first message of a
  thread) skips Stage 6.5 entirely — behavior is identical to today's
  single-field request.

**Response 200 (streamed NDJSON, grounded answer) — one line per event,
shown here expanded for readability:**
```json
{"stage": "SEARCHING"}
{"stage": "RETRIEVING"}
{"stage": "GENERATING"}
{"stage": "VALIDATING"}
{"stage": "COMPLETED", "answer": "Employees accrue 15 days of PTO per year [1], which can roll over up to 5 days into the next year [2].", "sources": [
  {
    "document_id": "demo-doc-1",
    "document_name": "Employee Handbook 2026.pdf",
    "locator": "page 8",
    "snippet": "Full-time employees accrue 15 days of paid time off annually...",
    "is_removed": false
  },
  {
    "document_id": "demo-doc-1",
    "document_name": "Employee Handbook 2026.pdf",
    "locator": "page 9",
    "snippet": "Unused PTO may roll over, up to a maximum of 5 days...",
    "is_removed": false
  }
]}
```
`is_removed` (FR-042, ADR-18): `true` if the cited document's chunks were no
longer present in the vector store by the time the `VALIDATING` stage ran
(e.g. deleted via `DELETE /documents/{id}` while this request was in
flight) — checked for real per distinct cited `document_id`, not a stub.

**Response 200 (streamed NDJSON, no-context, FR-022):** identical stage
sequence, terminal event:
```json
{"stage": "COMPLETED", "answer": "I don't have enough information in this knowledge base to answer that question.", "sources": []}
```

**Response 200 (streamed NDJSON, mid-stream failure, ADR-18):** the stage
sequence up to the point of failure, then a terminal `ERROR` event instead of
`COMPLETED` — HTTP status stays `200` (it was already sent before the
failure occurred), so retryable-vs-not is carried in the event body itself,
not the HTTP status:
```json
{"stage": "SEARCHING"}
{"stage": "RETRIEVING"}
{"stage": "GENERATING"}
{"stage": "ERROR", "code": "LLM_UNAVAILABLE", "message": "The answer service is temporarily unavailable. Please try again shortly.", "retryable": true}
```

**Status codes:**
- `200` — always for every case above, including a mid-stream `ERROR` event
  (see ADR-18 — an already-started stream cannot change its HTTP status)
- `400` — empty/whitespace-only `message`, or missing `knowledge_base_id`
  (checked before the stream opens — no body is streamed)
- `403` — session token does not own the requested `kb_user_*` (checked
  before the stream opens)
- `404` — unknown `knowledge_base_id` (checked before the stream opens)
- `503` — the requested knowledge base has zero ready documents (FR-056),
  distinguished from the empty-*retrieval* case above (which is a normal
  streamed `200`/`COMPLETED`) — checked before the stream opens
- LLM/vector-DB dependency failure/timeout (FR-054/FR-055) is no longer a
  `502` — it is a mid-stream `{"stage": "ERROR", "code": "LLM_UNAVAILABLE" | "VECTOR_STORE_UNAVAILABLE", "retryable": true}` event (ADR-18), since by
  the time either dependency is called the stream has already started with
  HTTP `200`.

**Error response example (403, pre-stream):**
```json
{ "error": { "code": "FORBIDDEN_KNOWLEDGE_BASE", "message": "You do not have access to this knowledge base." } }
```

**Validation:** `message` length capped (e.g. 2,000 characters) to bound
prompt size; enforced server-side regardless of any client-side limit
(NFR-006). `conversation_history`, if present, is capped at 8 entries and
2,000 characters per entry's `content`, same rationale (ADR-16).

**Rate limiting:** none enforced server-side in V1; Groq's own free-tier
limits are the practical ceiling (documented in `docs/DEPLOYMENT.md`), and
exhaustion surfaces as the `502` above.

---

## Error Code Reference

Every `error.code` value used across the endpoints above (added during Phase
3 implementation to make the shape in the header concrete — this table is
the authoritative list, kept in sync with `backend/errors.py` usage):

| Code | HTTP status | Used by |
|---|---|---|
| `NO_FILES_PROVIDED` | 400 | `POST /documents/upload` |
| `TOO_MANY_FILES` | 400 | `POST /documents/upload` |
| `FILE_TOO_LARGE` | 400 | `POST /documents/upload` |
| `REQUEST_TOO_LARGE` | 413 | Any endpoint — global `Content-Length`-based defense-in-depth (`docs/SECURITY.md` Excessive File Size), rejected before the body is read |
| `UNSUPPORTED_FILE_TYPE` | 400 | `POST /documents/upload` |
| `VALIDATION_ERROR` | 400 | Any endpoint — generic Pydantic request-shape validation failure (e.g. empty/oversized `POST /chat` message) |
| `FORBIDDEN_KNOWLEDGE_BASE` | 403 | `GET /knowledge-bases/{id}/documents`, `GET /documents/{id}/status`, `DELETE /documents/{id}`, `POST /chat` — session does not own the requested `kb_user_*`, or (delete only) the target is `kb_demo` |
| `KNOWLEDGE_BASE_NOT_FOUND` | 404 | `GET /knowledge-bases/{id}/documents`, `POST /chat` |
| `DOCUMENT_NOT_FOUND` | 404 | `GET /documents/{id}/status`, `DELETE /documents/{id}` |
| `EMPTY_KNOWLEDGE_BASE` | 503 | `POST /chat` — target KB has zero `READY` documents (FR-056); checked before the stream opens |
| `LLM_UNAVAILABLE` | 200 + mid-stream `{"stage": "ERROR", "retryable": true}` (ADR-18) | `POST /chat` — Groq dependency failure (FR-054). No longer a `502` — the stream has already started by the time Groq is called, so the HTTP status cannot change; the frontend maps this event to the exact same retryable-error UI a `502` used to (see ADR-18) |
| `VECTOR_STORE_UNAVAILABLE` | 200 + mid-stream `{"stage": "ERROR", "retryable": true}` (ADR-18) | `POST /chat` — embedding/retrieval/rerank stage failure, i.e. Qdrant unreachable after its own internal retries (FR-055), distinguished from `LLM_UNAVAILABLE` per FR-055's wording. New in ADR-18 — previously fell through uncaught to `INTERNAL_ERROR`/non-retryable, which did not satisfy FR-055 |
| `INTERNAL_ERROR` | 500 (pre-stream) or 200 + mid-stream `{"stage": "ERROR", "retryable": false}` (ADR-18, once `/chat` has started streaming) | Any endpoint — unexpected server error, sanitized per `docs/SECURITY.md` (Error Leakage); the global fallback for anything not covered by a more specific code above |

## Cross-Cutting Rules

- **No secret values ever appear in any request or response body** — this
  contract contains no API keys, and none of these endpoints accept one from
  the client (ADR-15).
- **CORS:** all endpoints restrict `Access-Control-Allow-Origin` to the
  deployed frontend origin (and `http://localhost:5173` in development) —
  see `docs/SECURITY.md`.
- **Consistency check:** every field in every response above corresponds to
  a field defined in `docs/DATA_MODEL.md`; every status transition
  referenced corresponds to `docs/DOCUMENT_PROCESSING.md`'s state machine.
