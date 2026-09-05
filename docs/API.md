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
      "document_count": 4
    },
    {
      "knowledge_base_id": "kb_user_9c2a...",
      "kind": "user",
      "name": "Your documents",
      "document_count": 2
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

**Request:**
```json
{
  "knowledge_base_id": "kb_demo",
  "message": "What is the company's vacation policy?"
}
```

**Response 200 (grounded answer):**
```json
{
  "answer": "Employees accrue 15 days of PTO per year [1], which can roll over up to 5 days into the next year [2].",
  "sources": [
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
  ]
}
```

**Response 200 (no-context, FR-022):**
```json
{
  "answer": "I don't have enough information in this knowledge base to answer that question.",
  "sources": []
}
```

**Status codes:**
- `200` — always, for both grounded and no-context answers (no-context is a
  valid, expected outcome, not an error)
- `400` — empty/whitespace-only `message`, or missing `knowledge_base_id`
- `403` — session token does not own the requested `kb_user_*`
- `404` — unknown `knowledge_base_id`
- `502` — LLM or vector-DB dependency failed/timed out (FR-054/FR-055)
- `503` — the requested knowledge base has zero ready documents (FR-056),
  distinguished from the empty-*retrieval* case above (which is a normal
  `200`)

**Error response example (502):**
```json
{ "error": { "code": "LLM_UNAVAILABLE", "message": "The answer service is temporarily unavailable. Please try again shortly." } }
```

**Validation:** `message` length capped (e.g. 2,000 characters) to bound
prompt size; enforced server-side regardless of any client-side limit
(NFR-006).

**Rate limiting:** none enforced server-side in V1; Groq's own free-tier
limits are the practical ceiling (documented in `docs/DEPLOYMENT.md`), and
exhaustion surfaces as the `502` above.

---

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
