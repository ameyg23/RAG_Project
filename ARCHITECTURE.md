# System Architecture

Companion to `docs/ARCHITECTURE_DECISIONS.md` (why) and `docs/REQUIREMENTS.md`
(what). This document describes the resulting system (how it fits together).

## 1. High-Level Architecture

```mermaid
flowchart LR
    subgraph Client["Browser (visitor)"]
        UI["React + Vite SPA\n(Cloudflare Pages)"]
    end

    subgraph Backend["FastAPI Backend (Render free)"]
        API["REST API layer"]
        ING["Ingestion pipeline"]
        RET["Retrieval + generation pipeline"]
        EMB["Local embedding model\n(sentence-transformers)"]
    end

    subgraph External["External free-tier services"]
        VDB[("Qdrant Cloud\nvector store")]
        LLM["Groq API\n(qwen/qwen3.8-27b)"]
    end

    UI -- "HTTPS: upload, status, chat" --> API
    API --> ING
    API --> RET
    ING --> EMB
    RET --> EMB
    ING -- "upsert chunks+metadata" --> VDB
    RET -- "similarity search (KB-filtered)" --> VDB
    RET -- "grounded prompt" --> LLM
    LLM -- "answer" --> RET
    RET -- "answer + citations" --> API
    API -- "JSON" --> UI
```

No component other than the FastAPI backend ever holds an LLM or vector-DB
API key (ADR-15). The browser only ever talks to the backend.

## 2. Frontend Architecture

- **Framework:** React + Vite SPA, vanilla CSS (ADR-01, ADR-02).
- **View structure:** single page with three coordinated regions —
  Knowledge-Base Selector, Chat panel, Upload/Documents panel (see
  `docs/UI_UX.md` for full state definitions).
- **State management:** local component state + a small shared context for
  `activeKnowledgeBaseId` and `sessionToken`; no external state library
  needed at this scale.
- **Session identity:** an anonymous session token is issued by the backend
  on first contact (`GET /health` or first upload) and stored in
  `localStorage`; sent as a header (`X-Session-Token`) on every subsequent
  request that touches a user-owned knowledge base.
- **Networking:** a single typed API client wrapping `fetch`, matching
  `docs/API.md` exactly.
- **Build output:** static `dist/` deployed to Cloudflare Pages (ADR-09); no
  server-side rendering.

## 3. Backend Architecture

FastAPI app organized by responsibility, not by HTTP verb:

```
backend/
  main.py                # FastAPI app, router registration, CORS config
  api/
    health.py             # GET /health
    knowledge_bases.py     # GET /knowledge-bases, GET .../documents
    documents.py           # POST /documents/upload, GET/DELETE /documents/{id}
    chat.py                # POST /chat
  ingestion/
    extract.py             # text extraction per file type
    chunk.py               # LangChain text splitters (ADR-05)
    embed.py                # sentence-transformers wrapper (ADR-06)
    pipeline.py             # orchestrates extract→chunk→embed→upsert, BackgroundTasks (ADR-13)
  retrieval/
    vector_store.py         # Qdrant client adapter (ADR-07, ADR-14)
    query_rewrite.py         # Stage 6.5: Groq call resolving follow-ups against
                              # client-supplied history, not persisted (ADR-16)
    retriever.py             # similarity search + threshold/cap + KB filter
    generation.py             # prompt construction + Groq call (ADR-08)
  models/
    schemas.py               # Pydantic request/response models (source of docs/API.md)
  config.py                  # env var loading (ADR-15)
```

Request lifecycle for a chat request: `api/chat.py` → `retrieval/retriever.py`
(embed query, filtered search) → `retrieval/generation.py` (build prompt,
call Groq) → response assembled with citations back through `api/chat.py`.

## 4. RAG Architecture

See `docs/RAG_PIPELINE.md` for the full stage-by-stage specification. In
brief: documents are extracted, cleaned, chunked (LangChain
`RecursiveCharacterTextSplitter`), embedded locally (MiniLM), and upserted
into Qdrant with metadata payload (`knowledge_base_id`, `document_id`,
`document_name`, `page`/`chunk_index`). A chat query is embedded the same
way, searched against Qdrant filtered to the active `knowledge_base_id`,
top-K chunks are assembled into a grounded prompt, and Groq generates an
answer that the backend pairs with citations derived from the chunks
actually included in the prompt (FR-041).

## 5. Document Ingestion Architecture

```mermaid
sequenceDiagram
    participant U as Browser
    participant A as FastAPI /documents/upload
    participant T as BackgroundTask
    participant E as Extraction+Chunking
    participant M as Embedding (MiniLM)
    participant Q as Qdrant

    U->>A: POST files (<=5, <=5MB each)
    A->>A: validate type/size/count (FR-010..012)
    A-->>U: 202 Accepted, status=UPLOADED per file
    A->>T: enqueue background task per file
    T->>E: extract text, clean, split into chunks
    alt extraction fails / empty text
        E-->>T: error
        T->>T: mark document FAILED (FR-053)
    else success
        E->>M: embed each chunk
        M->>Q: upsert(vector, payload={kb_id, doc_id, name, locator})
        Q-->>T: ack
        T->>T: mark document READY
    end
    U->>A: GET /documents/{id}/status (poll)
    A-->>U: current status
```

## 6. Query Architecture

*(Updated for ADR-16 — query rewriting — and ADR-18 — streamed progress
reporting. ADR-17 briefly added a reranking stage between vector search and
generation; it was reverted (see `docs/ARCHITECTURE_DECISIONS.md` ADR-17's
"Reverted" note — a Render free-tier 512MB RAM constraint), so the diagram
below reflects retrieval going straight from Qdrant search to threshold/cap
with no reranker in between. ADR-18 adds NDJSON progress events (`A-->>U`
lines) at each stage boundary.)*

```mermaid
sequenceDiagram
    participant U as Browser
    participant A as FastAPI /chat
    participant R as Query Rewrite (Groq)
    participant M as Embedding (BGE)
    participant Q as Qdrant
    participant L as Groq LLM

    U->>A: POST {knowledge_base_id, message, conversation_history?} (pre-stream checks pass — FR-056/403/404/400 handled as plain JSON before this point, ADR-18)
    A-->>U: stream opens, 200
    A-->>U: {"stage": "SEARCHING"}
    alt conversation_history non-empty
        A->>R: rewrite(message, conversation_history)
        R-->>A: rewritten_query (or message unchanged on failure)
    else first turn
        A->>A: rewritten_query = message
    end
    A->>M: embed(rewritten_query)
    M->>Q: search(vector, filter: knowledge_base_id, top_k=5)
    Q-->>A: up to 5 candidate chunks + cosine scores, filtered by MIN_SIMILARITY_SCORE
    A-->>U: {"stage": "RETRIEVING"}
    A-->>U: {"stage": "GENERATING"}
    alt no chunks survived MIN_SIMILARITY_SCORE
        A->>A: NO_CONTEXT_RESPONSE, Groq never called (FR-022)
    else
        A->>A: build grounded prompt from usable chunks, question=rewritten_query
        A->>L: generate(prompt)
        L-->>A: answer text
    end
    A-->>U: {"stage": "VALIDATING"}
    A->>A: derive citations from chunks used in prompt (FR-041)
    A->>Q: count_chunks_for_document(doc_id) per distinct cited document (FR-042, ADR-18)
    Q-->>A: chunk counts -> is_removed per source
    A-->>U: {"stage": "COMPLETED", "answer": ..., "sources": [...]}
```

On any dependency failure (Groq or Qdrant) after the stream has opened, `A`
emits `{"stage": "ERROR", "code", "message", "retryable"}` instead of the
next stage/`COMPLETED` event and ends the stream there — see ADR-18 for the
full error taxonomy (HTTP status stays `200`; retryable-vs-not travels in
the event body).

## 7. Knowledge-Base Architecture

- One Qdrant collection, shared across all knowledge bases (ADR-14).
- Every point (chunk vector) carries a mandatory `knowledge_base_id` payload
  field; every query and every write path requires this parameter with no
  default — enforced in `retrieval/vector_store.py` as the single choke
  point through which all Qdrant access happens.
- Demo KB: fixed ID (e.g. `kb_demo`), globally readable, never writable via
  the public API — it is seeded only by an offline/deploy-time script
  (`backend/scripts/seed_demo_kb.py`, see `docs/DOCUMENT_PROCESSING.md`).
- User KB: ID derived from the session token (e.g. `kb_user_<session_uuid>`),
  writable/deletable only by requests carrying the matching session token.

## 8. Storage Architecture

| Data | Where it lives | Persistence | Notes |
|---|---|---|---|
| Chunk vectors + metadata | Qdrant Cloud | Persistent (subject to ADR-07 suspension risk) | Single source of truth |
| Raw uploaded file | Backend temp directory | Transient — deleted after ingestion (ADR-11) | Never served back to client |
| In-flight processing status | Backend process memory | Transient — lost on backend restart | Acceptable per ADR-12 |
| Session token / active KB | Browser `localStorage` | Persistent client-side only | No server-side session store |
| Chat message history | Browser memory/`localStorage` | Persistent client-side only | Never sent to a database (FR-023). A short recent window IS now transmitted per-request as `conversation_history` (ADR-16) for query rewriting, but the backend discards it after that one request — transmission, not persistence (see `docs/DATA_MODEL.md` §6 amendment) |

## 9. Deployment Architecture

```mermaid
flowchart TB
    subgraph GH["Git repository"]
        FE_SRC["frontend/"]
        BE_SRC["backend/"]
    end

    FE_SRC -- "Cloudflare Pages\nbuild: vite build" --> CFP["Cloudflare Pages\n(static hosting, free)"]
    BE_SRC -- "Render\nbuild: pip install" --> RND["Render free web service\n(FastAPI, sleeps after 15 min idle)"]

    CFP -- "HTTPS fetch\n(CORS-restricted to CFP origin)" --> RND
    RND -- "API key from env vars" --> GROQ["Groq API (free tier)"]
    RND -- "API key from env vars" --> QDR["Qdrant Cloud (free tier)"]

    Visitor(("Visitor browser")) --> CFP
```

Deployment sequence, environment variables, and cost model are fully
specified in `docs/DEPLOYMENT.md` and `docs/ENVIRONMENT.md`.

## 10. Security Boundaries

- **Trust boundary 1 — Browser ↔ Backend:** the only boundary the public
  crosses. All input validated server-side (NFR-006) regardless of any
  client-side validation. CORS restricts allowed origins to the deployed
  Cloudflare Pages domain (and `localhost` in dev).
- **Trust boundary 2 — Backend ↔ Groq/Qdrant:** secrets live only here
  (ADR-15); this boundary is never reachable from the browser.
- **Trust boundary 3 — Session isolation:** a session token authorizes
  access only to its own `kb_user_<id>` knowledge base; the demo KB is
  read-only to everyone and write-protected from the public API entirely.
- Full threat-by-threat treatment: `docs/SECURITY.md`.

## Cross-Reference

- Data shapes: `docs/DATA_MODEL.md`
- Endpoint contracts: `docs/API.md`
- UI states per component: `docs/UI_UX.md`
