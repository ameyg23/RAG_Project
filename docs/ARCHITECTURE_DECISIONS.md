# Architecture Decision Records

Each ADR follows: Decision → Options Considered → Selected Option → Reason →
Advantages → Disadvantages → Free-tier/Cost Implications → Future Migration.

All decisions are constrained by NFR-001 (zero required cost) from
`docs/REQUIREMENTS.md`.

---

## ADR-01: Frontend Framework — React + Vite

**Options considered:** React+Vite, Next.js, plain HTML/JS, SvelteKit.

**Selected:** React + Vite (SPA, client-side routing not required — single page
with view switching).

**Reason:** React has the largest talent pool for a portfolio piece a
recruiter may inspect; Vite gives near-instant dev server start and a small,
fast production build with zero config, which matters for a static-hosting
deployment target.

**Advantages:** Huge ecosystem, fast HMR, trivial static export (`vite build`
→ static `dist/`), no server-side rendering complexity to host for free.

**Disadvantages:** SPA-only means no SSR/SEO benefit; not needed here since
the app is a tool, not content to be indexed.

**Free-tier implications:** Static output deploys to any static host at
$0 (see ADR-09).

**Future migration:** Could move to Next.js if SSR or SEO becomes a
requirement; component logic is portable.

---

## ADR-02: Styling — Vanilla CSS

**Options considered:** Vanilla CSS, Tailwind, CSS-in-JS (styled-components),
component library (MUI/Chakra).

**Selected:** Vanilla CSS (plain `.css` files, CSS custom properties for
theming).

**Reason:** No build-time dependency, no bundle-size cost, no framework
lock-in; the UI surface (docs/UI_UX.md) is small enough that a utility
framework's main benefit (speed of authoring) doesn't outweigh its added
tooling.

**Advantages:** Zero extra dependencies, full control, smallest possible CSS
payload, easiest to review in a portfolio context ("I wrote this CSS").

**Disadvantages:** More manual work than Tailwind for consistent spacing/
color; requires discipline (a small design-token stylesheet) to avoid drift.

**Free-tier implications:** None — no cost dimension.

**Future migration:** Tailwind could be layered in later without rewriting
component structure.

---

## ADR-03: Backend Framework — FastAPI

**Options considered:** FastAPI, Flask, Django REST Framework, Node/Express.

**Selected:** FastAPI (Python).

**Reason:** Native async support (needed for calling external LLM/vector-DB
APIs without blocking), automatic OpenAPI schema generation (keeps
`docs/API.md` verifiable against real code), and first-class Pydantic
validation for upload/chat payloads (NFR-006).

**Advantages:** Async I/O, built-in request validation, automatic docs at
`/docs`, small footprint suited to a free-tier instance with limited RAM.

**Disadvantages:** Smaller plugin ecosystem than Django; no built-in ORM/admin
(not needed — this project has no relational persistence requirement beyond
the vector DB's own metadata store).

**Free-tier implications:** Runs comfortably inside Render's free instance
memory ceiling; async I/O reduces wasted compute time while waiting on the
LLM/vector-DB, which matters on a CPU/RAM-capped free instance.

**Future migration:** None anticipated; FastAPI scales to paid tiers
unchanged.

---

## ADR-04: Language — Python

**Options considered:** Python, Node.js/TypeScript (single-language stack).

**Selected:** Python for the backend; JavaScript/TypeScript for the frontend
(polyglot, not single-language).

**Reason:** The RAG ecosystem (embedding libraries, PDF/DOCX extraction,
LangChain, evaluation tooling) is most mature and best documented in Python.
A single-language Node RAG stack is possible but trades away that maturity
for consistency the project doesn't need (frontend and backend are already
separate deployables).

**Advantages:** Access to `sentence-transformers`, `pypdf`, `python-docx`,
LangChain, and RAG evaluation libraries without reimplementation.

**Disadvantages:** Two languages to maintain; mitigated by a clean HTTP
boundary (docs/API.md) so each side is independently simple.

**Free-tier implications:** None beyond ADR-03.

**Future migration:** N/A.

---

## ADR-05: Orchestration — LangChain (used selectively)

**Options considered:** Full LangChain framework, LlamaIndex, no framework
(hand-rolled pipeline).

**Selected:** LangChain, used only for document loaders and text splitters
(`RecursiveCharacterTextSplitter`, `PyPDFLoader`, `Docx2txtLoader`) — **not**
its higher-level chains/agents.

**Reason:** Document loading and chunking are solved, well-tested problems;
reimplementing PDF/DOCX parsing edge cases (multi-column layout, embedded
fonts) is wasted effort. However, retrieval → prompt → LLM call is written
directly against the vector DB and LLM SDKs, because LangChain's chain
abstractions add indirection that makes `docs/RAG_PIPELINE.md` harder to
verify line-by-line, and increases cold-start import time on a free-tier
instance.

**Advantages:** Mature loaders/splitters save implementation time and handle
many format edge cases; direct pipeline code stays simple, debuggable, and
fast to import.

**Disadvantages:** Partial adoption means two mental models ("LangChain for
ingestion, plain code for retrieval") — acceptable given the boundary is
narrow and documented.

**Free-tier implications:** LangChain core + loaders add ~30–60MB of
installed dependencies; acceptable within Render's free build size limits,
but a reason to avoid pulling in its full `langchain` chains/agents/tools
surface (much larger, slower cold import).

**Future migration:** If chunking needs become more complex (semantic
chunking, hierarchical chunking), swap only the splitter implementation.

---

## ADR-06: Embedding Model — Local `sentence-transformers/all-MiniLM-L6-v2`

**Options considered:** OpenAI `text-embedding-3-small` (paid), Cohere embed
(free tier with rate limits), Google `text-embedding-004` (free tier),
local `sentence-transformers` model (CPU inference, no API).

**Selected:** Local `all-MiniLM-L6-v2` (384-dim), run in-process on the
FastAPI backend via CPU.

**Reason:** Every hosted embedding API — even "free tier" ones — imposes a
rate limit and a second account/API-key dependency (violates simplicity and
adds a new failure mode per NFR-005/FR-055 distinction). A local model has
**no rate limit, no quota, no additional secret**, and 384-dim vectors keep
Qdrant's free-tier storage ceiling (§ADR-07) comfortably under budget.

**Advantages:** Permanently free with no daily quota; no added external
dependency/secret; deterministic latency; works offline for local dev.

**Disadvantages:** CPU inference on a free-tier instance is slower than a
hosted GPU embedding API (seconds, not milliseconds, for a full document);
lower embedding quality than larger commercial models — mitigated because
retrieval only needs to rank chunks *within one small knowledge base*, not
across a massive corpus.

**Free-tier implications:** Zero marginal cost per embedding, ever. Adds
~80MB model download to the backend's first cold start (cached after that).

**Future migration:** Swap to a hosted embedding API by changing one function
(`embed_texts()`); chunk/metadata schema is embedding-model-agnostic aside
from vector dimension.

**Model note (documentation correction — this ADR was out of sync with the
running code until this pass):** the model actually deployed is
`BAAI/bge-small-en-v1.5`, not `all-MiniLM-L6-v2` — a swap made to fix
resume/short-document recall, with its own re-tuning of
`MIN_SIMILARITY_SCORE` (see `backend/retrieval/retriever.py`'s docstring for
the full empirical record: threshold moved from 0.35 to **0.45**, and vector
dimension stayed 384 by coincidence so `docs/DATA_MODEL.md`/`vector_store.py`
needed no dimension change, only a `drop_collection()` + re-seed since a
model swap invalidates existing vectors even at the same dimension). This
ADR's text above was never updated when that swap shipped; `docs/RAG_PIPELINE.md`
had the same gap and both are corrected as part of ADR-16/ADR-17 below,
since those touch the same sections. The reasoning above (no rate limit, no
quota, no added secret) still applies unchanged to BGE — only the specific
model name and threshold value were stale.

---

## ADR-07: Vector Database — Qdrant Cloud (Free Tier)

**Options considered:** Pinecone (free tier), Qdrant Cloud (free tier),
self-hosted Chroma/FAISS embedded in the backend process.

**Selected:** Qdrant Cloud free tier (1 cluster, 0.5 vCPU / 1GB RAM / 4GB
disk, ~1M vectors at 768-dim — far more than this project needs at 384-dim).

**Reason:** Render's free web service disk is **ephemeral** — it is wiped on
every redeploy and may reset on restart after a cold-start sleep cycle. A
vector store embedded in that filesystem (Chroma/FAISS local file) would
silently lose all user-uploaded knowledge bases on any redeploy. Qdrant Cloud
is a separate, persistent service, decoupling vector storage lifetime from
backend instance lifetime.

**Advantages:** True persistence independent of backend restarts; purpose-
built vector index (HNSW) with metadata filtering, needed for knowledge-base
isolation (NFR-004) via a `knowledge_base_id` payload filter on every query.

**Disadvantages:** Free Qdrant clusters **suspend after 7 days of
inactivity and are deleted after 28 days** — a real risk for a low-traffic
portfolio demo. Mitigated by: (a) keeping the demo KB re-ingestible from a
committed script (docs/DOCUMENT_PROCESSING.md), so a suspended cluster is a
one-command recovery, not data loss of anything irreplaceable, and (b)
documenting this explicitly so it is never mistaken for a bug. Also: a real
Qdrant Cloud server enforces a requirement that `qdrant-client`'s embedded
in-memory mode (used for this project's automated tests) does not —
filtering on a payload field with no index raises a 400 error server-side,
even though the identical code runs silently against in-memory Qdrant. This
was only caught by actually verifying against a live cluster (Phase 8/9's
work was initially marked done using in-memory tests only); `vector_store.py`
now creates keyword payload indexes on `knowledge_base_id` and `document_id`
at collection-creation time to fix this. **Lesson generalized:** in-memory/
embedded mode is a good, cheap substitute for CI test speed, but it is not
a perfect stand-in for the real server's behavior — anything genuinely
"done" against Qdrant should still get one live-cluster smoke test before
being trusted, which is exactly what surfaced this.

**Free-tier implications:** $0 as long as usage stays within 1GB RAM / 4GB
disk, which this project's expected scale (a handful of small KBs) will not
approach. See `docs/DEPLOYMENT.md` for the suspension-recovery procedure.

**Future migration:** Swap to self-hosted Qdrant or Pinecone by changing the
vector-store adapter only; retrieval interface (`upsert`, `query`, `delete`
by `knowledge_base_id`) is provider-agnostic in code.

---

## ADR-08: LLM Provider — Groq (`qwen/qwen3.8-27b`)

**Options considered:** OpenAI (paid), Anthropic (paid), Google Gemini (free
tier, low daily request quota), Groq (free tier, no card required).

**Selected:** Groq, `qwen/qwen3.8-27b`, as the primary answer-generation
model.

**Reason:** Groq's free tier requires no credit card, and its per-minute
limits (30 RPM) suit an interactive chat demo better than Gemini's stricter
per-model daily caps (as low as 100–250 requests/day on comparable models as
of the free-tier research done for this plan — see `docs/DEPLOYMENT.md`).
Groq's inference is also unusually fast, which matters given Render's
free-tier cold starts already add latency.

**Model note (updated after live verification):** this ADR originally
selected `llama-3.3-70b-versatile`, planned at design time. By the time
Phase 10 verified against Groq's real API (with actual credentials), that
model had been removed from Groq's catalog entirely — free-tier model
lineups on a fast-moving inference provider are not a stable target to
plan far in advance, so this was expected to need a real check at
implementation time, not a planning-time guess. Two live candidates were
compared directly against a real grounded-QA prompt using this project's
own demo content: `openai/gpt-oss-120b`/`-20b` turned out to be *reasoning*
models that spend a large, variable share of `max_tokens` on hidden
chain-of-thought before any visible answer appears (measured: 52 of 62
completion tokens on a trivial 1-word reply) — this materially changes
token-budget and latency assumptions and would need explicit handling.
`qwen/qwen3.8-27b` behaved as a plain instruction model — no hidden
reasoning tokens, correct grounded/cited output on the first try, fast
(69ms end-to-end in the live test). It was chosen for being the simpler,
more predictable fit for this project's extractive-answer design, not
because reasoning models are bad in general.

**Advantages:** No credit card to unlock; fast inference (low added
latency); direct (non-reasoning) output keeps prompt/response handling
simple and matches the extractive, low-temperature answer style this
project wants; 27B-parameter model quality is adequate for grounded,
extractive-style RAG answers over short retrieved contexts.

**Disadvantages:** Daily/organization-level request cap (documented in
`docs/DEPLOYMENT.md`) can be exhausted under sustained demo traffic; smaller
context window discipline is required (see `docs/RAG_PIPELINE.md` context
limits) to fit within Groq's tokens-per-minute cap; Groq's free-tier model
catalog can and does change without notice (this ADR itself is evidence),
so the configured model name must be re-verified against
`client.models.list()` before any future deployment, not assumed stable.

**Free-tier implications:** $0, no card. Rate-limit exhaustion produces a
user-visible "try again shortly" error (FR-054) rather than a bill.

**Future migration:** LLM calls are isolated behind a single
`generate_answer()` function; swapping to Gemini, a paid provider, or a
different Groq model changes one adapter and one environment variable
(`LLM_MODEL_NAME`, `docs/ENVIRONMENT.md`) — this ADR's own history is the
proof that this isolation was worth having.

---

## ADR-09: Frontend Hosting — Cloudflare Pages

**Options considered:** Vercel (free tier), Netlify (free tier), Cloudflare
Pages (free tier), GitHub Pages.

**Selected:** Cloudflare Pages.

**Reason:** Cloudflare Pages is the only option with **no bandwidth cap** on
its free tier — Vercel's Hobby tier caps free bandwidth at 100GB/month and
restricts commercial use; a portfolio project that might get shared/linked
publicly should not risk a bandwidth-based service interruption.

**Advantages:** Unlimited static bandwidth, global CDN, free SSL, generous
build minutes, straightforward Git-integrated deploys.

**Disadvantages:** Cloudflare Pages Functions (if ever needed for
edge logic) share the Workers free cap (100k requests/day) — irrelevant here
since all dynamic logic lives on the FastAPI backend, not on the frontend
host.

**Free-tier implications:** $0, effectively uncapped for this project's
expected traffic.

**Future migration:** Static output is host-agnostic; moving to Vercel/
Netlify is a config-only change.

---

## ADR-10: Backend Hosting — Render (Free Web Service)

**Options considered:** Render free tier, Fly.io free allowance, Railway
(no longer offers a free tier as of this research), a self-managed VM.

**Selected:** Render free web service.

**Reason:** Render supports native Python web services with zero
Dockerfile requirement, gives 750 free instance-hours/month (enough for a
single always-attempted service, since a month has ~730 hours), and needs no
credit card for the free tier.

**Advantages:** Simple Git-integrated deploy, native Python buildpack,
environment-variable secret management in the dashboard (ADR-15), no card
required.

**Disadvantages:** Free web services **spin down after 15 minutes of
inactivity**; the next request pays a **30–60 second cold-start penalty**.
This directly shapes NFR-002/NFR-003 and the UI's "waking up" state
(docs/UI_UX.md).

**Free-tier implications:** $0 as long as monthly instance-hours stay under
750; a single demo service under normal (non-viral) traffic will not
approach this.

**Future migration:** A paid Render "Starter" tier ($7/mo) removes the sleep
behavior with no code change if the project ever needs always-on latency.

---

## ADR-11: Storage Strategy — No Persistent Blob Storage for Raw Files

**Options considered:** Persist original uploaded files (S3/R2/Supabase
Storage free tier), or treat raw files as transient and persist only
extracted chunks.

**Selected:** Transient raw files. The original uploaded file exists only
in a temporary directory during ingestion (extraction → chunking →
embedding → upsert) and is deleted once ingestion completes or fails.
Persistent state is the chunk text + metadata inside Qdrant.

**Reason:** Adding a blob-storage provider is a fourth external service and a
fourth secret (violates NFR-005/simplicity) purely to support a V1 feature
(re-downloading the original file) that is explicitly excluded (§12 of
`docs/REQUIREMENTS.md`). Re-upload is an acceptable recovery path for a
portfolio-scale project.

**Advantages:** One fewer external dependency/account; no risk of orphaned
files; smaller security surface (no file serving endpoint to defend).

**Disadvantages:** A user cannot recover their original file if they lose
their local copy; this is disclosed explicitly in the UI (docs/UI_UX.md).

**Free-tier implications:** $0 — no storage service used at all.

**Future migration:** Add Cloudflare R2 (free egress, 10GB free storage) as
a blob store if "download original file" becomes an actual requirement.

---

## ADR-12: Persistence Strategy — Vector DB as the Single Source of Truth

**Decision:** There is no separate relational database. Document metadata
(filename, status, upload timestamp, knowledge_base_id) and chunk records
both live in Qdrant: chunk vectors carry this metadata as payload fields, and
document-level status is tracked as a synthetic "document record" pattern —
one or more chunk payload rows filtered by `document_id`, plus an
in-memory/process-local status map for documents still `PROCESSING` (not yet
embedded, so not yet in Qdrant).

**Options considered:** Add SQLite/Postgres (e.g. free Supabase/Neon tier)
for document/session metadata vs. push all metadata into Qdrant payloads.

**Selected:** Qdrant payloads only, plus an in-process status table for the
brief `PROCESSING` window.

**Reason:** A second datastore is a second persistence and consistency
problem (keeping a Postgres "documents" table in sync with Qdrant chunks) for
a project whose entire queryable state is already "chunks with metadata." The
one gap — status during processing, before any chunk exists — is short-lived
and acceptable to hold in memory (lost on backend restart, which simply
means an in-flight upload must be retried, a rare and low-cost failure mode
at this scale).

**Advantages:** One less service/account; no schema-sync bugs between two
stores.

**Disadvantages:** In-memory processing status does not survive a backend
restart mid-upload (rare, and covered by FR-053-style failure handling on
retry).

**Free-tier implications:** $0 — no additional database service.

**Future migration:** Introduce a managed Postgres free tier if session/
chat-history persistence (currently excluded, §12) is added later.

---

## ADR-13: Document Processing Approach — Synchronous-in-Request-Then-Background-Task

**Decision:** Upload endpoint validates and saves files to a temp path
synchronously, returns immediately with `UPLOADED` status per file, then
processes extraction → chunking → embedding → upsert as a FastAPI
`BackgroundTasks` job per file. Status is polled by the frontend
(`GET /documents/{id}/status`).

**Options considered:** Fully synchronous (block upload response until
embedding completes), background task (chosen), external task queue
(Celery + Redis).

**Reason:** A task queue (Celery/Redis) requires a third free-tier service
and adds operational complexity disproportionate to this project's scale.
FastAPI's built-in `BackgroundTasks` is sufficient for a handful of small
files processed within seconds, and keeps the upload request itself fast
(good UX, avoids Render's request timeout).

**Advantages:** No extra infrastructure; simple mental model; status
polling is a well-understood pattern (docs/DOCUMENT_PROCESSING.md).

**Disadvantages:** Background tasks run in the same process/worker as the
web server — a large file could momentarily compete with request handling
on a single free-tier CPU. Acceptable given the 5MB/5-file cap (NFR-002).

**Free-tier implications:** $0 — no queue/broker service needed.

**Future migration:** Swap to Celery+Redis (or a hosted queue) if file
volume/size limits are raised.

---

## ADR-14: Knowledge-Base Isolation — Session-Scoped `knowledge_base_id` + Vector-DB Payload Filter

**Decision:** Every uploaded-document knowledge base is identified by a
server-generated `knowledge_base_id` tied to an anonymous session token
(random UUID, set as an HttpOnly-equivalent value returned to the client and
sent back on every request — see `docs/SECURITY.md` for why HttpOnly cookies
vs. a client-held token were weighed). Every Qdrant write and query carries
this ID as a mandatory payload filter. The demo knowledge base uses a fixed,
well-known `knowledge_base_id` that every session can read but none can
write to.

**Options considered:** Separate Qdrant *collection* per knowledge base vs.
one shared collection with a payload filter field.

**Selected:** One shared collection, `knowledge_base_id` payload filter.

**Reason:** Qdrant's free tier is a single cluster; many small per-KB
collections add fixed per-collection overhead and make demo-KB re-seeding
scripts more complex than one collection with a filter. A payload filter is
enforced identically on every query path, which is easier to verify for
NFR-004 than trusting that every code path selects the right collection.

**Advantages:** Simple to reason about and test in isolation
(docs/TEST_STRATEGY.md includes an explicit KB-isolation test); no
per-collection resource ceiling to hit on the free cluster.

**Disadvantages:** A missing filter in one query path is a real risk (cross-
tenant leak) — mitigated by centralizing all Qdrant access through one
retrieval module that always requires `knowledge_base_id` as a parameter
(no optional/default value).

**Free-tier implications:** $0 — fits inside one free cluster regardless of
how many user sessions create knowledge bases (bounded by overall storage,
not by collection count).

**Future migration:** Migrate to per-tenant collections if per-KB resource
isolation or independent scaling is needed later.

---

## ADR-15: API-Key Management — Backend-Only Environment Variables

**Decision:** All secrets (Groq API key, Qdrant API key/URL) are read from
backend environment variables at process start (`os.environ`), set via
Render's dashboard secret storage. No secret is ever sent to, embedded in,
or requested from the frontend. The frontend only ever calls the FastAPI
backend, never Groq or Qdrant directly.

**Options considered:** Frontend calls LLM/vector-DB directly with a
restricted key vs. backend-only proxy (chosen).

**Reason:** No LLM or vector-DB free tier offers a frontend-safe, sufficiently
restricted key type for this use case; any key usable from the browser is
usable by anyone who reads the bundle. A backend proxy is the only pattern
that satisfies NFR-005 unconditionally.

**Advantages:** Secrets never leave the backend process; key rotation is a
one-place change (see `docs/DEPLOYMENT.md` → "How to replace an API key").

**Disadvantages:** All LLM/vector-DB traffic is proxied through the backend,
adding its latency/availability as a dependency for every chat request —
already true given ADR-03's design.

**Free-tier implications:** None — key management itself is free; this ADR
exists purely to satisfy the security requirement at zero cost.

**Future migration:** N/A — this pattern holds regardless of scale.

---

## ADR-16: Query Rewriting — Second Groq Call Against Client-Supplied, Non-Persisted Conversation History

**Decision:** Follow-up questions (e.g. "what about their vacation days?")
are resolved into a standalone, retrievable query by a second Groq
chat-completion call — same provider and model as ADR-08, a different
prompt — given the current message plus a short window of recent
conversation turns that the **frontend** includes in the `POST /chat`
request body as a new optional field, `conversation_history`. The backend
does not persist this field anywhere; it is read, used to produce one
rewritten query string, and discarded at the end of that single request.

**Options considered:**
1. No rewriting; rely on retrieval + prompt instructions alone (status quo).
2. Client-side heuristic rewriting (regex for pronouns/demonstratives).
3. Server-side LLM rewrite, gated by a client-side or server-side heuristic
   ("does this look like it needs history?").
4. Server-side LLM rewrite unconditionally whenever history is present
   (chosen), skipped only when history is empty.
5. A second, different LLM provider dedicated to rewriting.

**Selected:** Option 4 — a Groq call via a new `retrieval/query_rewrite.py`
module (Stage 6.5, see `docs/RAG_PIPELINE.md`), triggered whenever
`conversation_history` is non-empty; skipped entirely on a thread's first
message (nothing to resolve a pronoun against, and it saves a Groq call on
every thread's opening turn, which is also usually the highest-traffic case
for the demo KB's suggested-question buttons).

**Reason:** Option 1 doesn't fix the actual reported problem — a follow-up's
pronoun has no referent to embed against, so retrieval silently fails no
matter how good the embedding model or reranker is; this is a retrieval-input
problem, not a retrieval-quality problem, and none of the existing three
grounding layers (docs/RAG_PIPELINE.md "Grounding Strategy") address it.
Option 2 was rejected because reliably resolving "their"/"it"/"that"/"what
about X instead" requires actual language understanding — a regex will
under- or over-fire in ways that are silent and hard to test for
(a wrong-referent rewrite looks identical to a correct one until the wrong
chunks come back). Option 3 (heuristic-gated LLM call) was rejected for V1
specifically to avoid a second, independent failure surface: a false-negative
heuristic (deciding rewriting isn't needed when it actually is) degrades
correctness silently, whereas the chosen prompt already handles the "already
standalone" case explicitly ("rewrite it as a standalone question, or return
it unchanged if already standalone") — so the cost of "always try" versus
"only try when needed" is mostly one extra Groq round-trip, not extra
correctness risk, and Groq's measured latency (ADR-08: as low as ~70ms in
the live test) makes that trade acceptable at this project's scale. Option 5
was rejected for the same reason ADR-06 rejected a second embedding
provider: Groq's free tier is already the cheapest zero-card option in use,
and a second LLM provider is a second secret/account for no correctness
benefit NFR-005 would have to justify.

**Why this doesn't violate `docs/REQUIREMENTS.md` §12's exclusion of
"multi-turn conversation memory that persists across browser sessions or
devices":** nothing new is persisted server-side. `conversation_history` is
an ephemeral, per-request echo of state the frontend already holds in
memory (`SessionContext.jsx`'s `chatMessages`, confirmed already existing
and already never sent to the backend before this ADR). The backend remains
exactly as stateless across requests as ADR-12 established — this ADR adds a
field to one request's payload, not a new persistence layer. A closed
browser tab loses the conversation exactly as it does today (FR-023);
resuming a session on a different device still starts a blank thread, since
there is nowhere server-side this history could have been recovered from
even if the client wanted to.

**Request-shape change (docs/API.md, `backend/models/schemas.py`):**
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
- `conversation_history`: optional, defaults to `[]`. Each entry:
  `{ "role": "user" | "assistant", "content": string }`.
- **Frontend responsibility:** send the last **3 exchanges** (up to 6
  entries: 3 user + 3 assistant turns), taken from `chatMessages`
  *excluding* the just-typed current message (which stays in the separate
  `message` field, unchanged). 3 exchanges is a starting point, tunable by
  the frontend/QA agents without an API shape change.
- **Backend validation (defense-in-depth, NFR-006):** hard cap of 8 entries
  server-side regardless of what the client sends (a misbehaving/future
  client sending more must not blow the rewrite-prompt's token budget); each
  entry's `content` capped at 2,000 characters, mirroring `ChatRequest.message`'s
  existing validator in `backend/models/schemas.py`.
- Not a new persisted entity — `docs/DATA_MODEL.md` §6 (ChatMessage) is
  updated to note this field's shape without introducing a server-side
  ChatMessage record; §5 (ChatSession) is unchanged (still no message
  history in that map).

**Rewriting call / prompt approach:** a short, dedicated system prompt
("Given this conversation and a follow-up question, rewrite the follow-up
as a fully standalone question that can be understood without the history.
Preserve the user's original intent and phrasing style. If the follow-up is
already standalone, return it unchanged. Respond with only the rewritten
question, no explanation.") plus the history turns and the raw message as
the user turn. Reuses `generation.get_client()`/`generation.generate()`
(same Groq client, same model, `temperature≈0.0`, small `max_tokens≈100` —
the output is one short question, not an essay).

**Where the rewritten query is used — deviates from the naive default, see
Reason:** the rewritten, standalone query is used for **both** Stage 7's
query embedding **and** as the `QUESTION:` fed into Stage 11's generation
prompt — not retrieval-only. The pronoun-ambiguity problem that motivates
rewriting in the first place applies equally to the generation call: if
`generation.answer_question()` were handed the raw "what about their
vacation days?" alongside only the retrieved chunks (no history), the LLM
has the same missing-referent problem retrieval had, and Stage 11's system
prompt cannot resolve a referent that plain isn't in its input. The user
still sees their own original phrasing in the chat thread — the frontend
never displays the rewritten text, and the rewritten text is never appended
to `chatMessages` or echoed back in `conversation_history` on the *next*
turn (which re-sends the user's actual original messages) — this
specifically avoids "rewrite of a rewrite" drift compounding across a long
thread.

**Failure handling:** if the rewrite call itself fails (Groq timeout/rate
limit/malformed response — the same `LLMUnavailableError` class ADR-08's
generation call can raise), the request does **not** hard-fail with a 502.
It falls back to using the raw `message` as both the retrieval query and the
generation question (i.e. behaves exactly as it did before this ADR),
logged server-side per NFR-009. Reason: the rewrite call is an internal
retrieval-quality enhancement, not the user-facing "give me an answer"
dependency `docs/API.md`'s `502 LLM_UNAVAILABLE` contract already exists
for (Stage 12's generation call); degrading gracefully to today's behavior
on a rewrite hiccup is strictly better than turning a solvable problem into
a hard error the client must retry.

**Advantages:** fixes the reported UX gap directly at its source (the
retrieval input, not retrieval quality); reuses an already-integrated,
already-free provider (no new secret, no new account, NFR-005 unaffected);
the prompt's own "return unchanged if already standalone" instruction makes
this safe to call unconditionally without a separate need-detection step.

**Disadvantages:** one additional Groq round-trip per non-opening chat turn
— added latency (bounded by Groq's documented speed, ADR-08) and added
consumption against Groq's free-tier 30 RPM/day caps (now up to 2 Groq calls
per turn instead of 1 for any thread beyond its first message); a "rewrite
drift" risk over a very long thread is mitigated by always re-deriving the
rewrite from the user's original messages (never chaining rewritten text
into history), not eliminated for pathologically long threads (out of scope
at this project's demo scale).

**Free-tier implications:** $0 — same Groq account/key as ADR-08, no new
service. The practical risk is hitting Groq's existing rate ceiling sooner
under sustained multi-turn traffic; this was already a documented risk in
ADR-08 and is not a new *kind* of cost, just a higher rate of an existing one.

**Future migration:** if Groq's rate limit becomes a real constraint,
options are (a) a cheap heuristic pre-filter to skip rewriting on
obviously-standalone messages (Option 3 above, deferred rather than
rejected outright), or (b) a smaller/local rewriting model if one proves
adequate — `query_rewrite.py` isolates this behind one function the same
way `generation.generate()` isolates the LLM provider (ADR-08's own
migration path), so either change is contained to one module.

---

## ADR-17: Reranking — Local Cross-Encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`)

**REVERTED (2026-09-06):** the deployed Render free-tier instance (512MB
RAM) OOM-crashed under a real, live `/chat` request — confirmed directly:
`/health` and `/chat` both returned 502 mid-request, then Render
auto-restarted the process. Root cause: loading both the embedding model
(`BAAI/bge-small-en-v1.5`) *and* this ADR's reranker
(`cross-encoder/ms-marco-MiniLM-L-6-v2`) into memory at once, on top of the
CPU-torch/transformers/FastAPI overhead already established in ADR-03/06,
exceeds 512MB — the exact risk this ADR's own "Disadvantages" section
flagged as "expected to still fit... but not verified in this ADR." The
user was given the real tradeoffs (pay for Render Standard's 2GB RAM
instead of the free tier; invest in a bigger free ONNX/quantized-model
rewrite; or drop reranking and keep only embedding-based retrieval) and
explicitly chose to drop reranking and stay on the free tier, accepting
the `no_context_precision` regression this ADR had fixed (1.0 back down to
its pre-ADR-17 baseline of 0.6, `evaluation/results/20260906T052601Z.json`)
as a known, accepted consequence of that choice rather than a bug. The
revert removed `backend/retrieval/reranker.py` entirely, reverted
`retriever.py`'s `TOP_K` (20→5) and removed `TOP_N`/`MIN_RERANK_SCORE`/
`apply_rerank_threshold()`, and removed the Stage 8.5 rerank call from
`api/chat.py`'s orchestration — `MIN_SIMILARITY_SCORE` (unchanged at 0.45)
is once again the sole, final retrieval gate. Query rewriting (ADR-16) and
NDJSON streaming (ADR-18) were untouched by this revert — both are fully
independent of reranking. The rest of this ADR's content is preserved
below as the historical record of what was tried and why, per this
project's established practice of not deleting superseded decisions.

**Decision:** retrieval widens its initial candidate pool from Qdrant, a
local cross-encoder reranks that pool, and only the reranked top-N chunks
reach the LLM — inserted as a new Stage 8.5 in `docs/RAG_PIPELINE.md`,
between Similarity Search (Stage 8) and Top-K Retrieval (Stage 9, whose
threshold-and-cap logic now operates on rerank scores instead of raw cosine
scores).

**Options considered:**
1. No reranker; keep tuning `MIN_SIMILARITY_SCORE` alone.
2. A hosted reranking API (Cohere Rerank free tier, Jina Reranker free tier).
3. A local cross-encoder via `sentence-transformers`'s `CrossEncoder` class
   (chosen).
4. A second, larger local reranker model (e.g. a `bge-reranker` variant).

**Selected:** Option 3 — `cross-encoder/ms-marco-MiniLM-L-6-v2`, run
in-process on the same CPU the embedding model already runs on, via
`sentence-transformers`'s `CrossEncoder` class (already an installed
dependency per `requirements.txt` — `sentence-transformers==3.3.1` ships
`CrossEncoder` alongside `SentenceTransformer`; **zero new package**).

**Reason:** Option 1 was already tried and hit a real ceiling — the
`no_context_precision` regression documented in `backend/retrieval/retriever.py`'s
docstring is explicitly *not* fixable by threshold tuning alone (raising
`MIN_SIMILARITY_SCORE` past the offending no-context cases' scores would
gut resume-fixture recall first). Option 2 was rejected for the same reason
ADR-06 rejected hosted embedding APIs: every hosted reranking free tier
imposes its own rate limit, its own account, and its own secret (NFR-005),
purely to replace a computation this project's existing dependency already
provides for free with no rate limit at all. Option 4 was rejected as
premature — `ms-marco-MiniLM-L-6-v2` is the standard, well-documented
default cross-encoder for this exact use case (reranking bi-encoder
retrieval output), small enough (~80MB, comparable to ADR-06's BGE
download) to be a safe first choice on a free-tier CPU instance, and this
project's retrieval funnel is small (candidate pools of ~20 short chunks
per query) — a bigger model is a tuning lever to reach for only if
evaluation shows this one underperforms, not a default.

**Why a cross-encoder specifically fixes the `no_context_precision` gap
(architectural expectation, not yet measured — see Validation below):** a
bi-encoder (BGE) embeds the query and each chunk independently, so its
cosine similarity is fundamentally a coarse *topical/lexical proximity*
signal — this is exactly why "What is the weather forecast for tomorrow?"
(0.48) and "How do I file my personal income taxes?" (0.61) score high
enough to pass `MIN_SIMILARITY_SCORE=0.45` against a company handbook: they
share enough surface vocabulary/topic-adjacency (schedules, money, dates)
with real chunks to look deceptively relevant to a model that never compares
the query and chunk *together*. A cross-encoder jointly attends over the
full `(query, chunk)` pair token-by-token in one forward pass, which is a
strictly more discriminating signal for "does this specific chunk actually
answer this specific question" — the exact judgment a bi-encoder's
independent-vector design cannot make. This is why the RAG agent flagged
"a reranker" as the fix (`retriever.py`'s docstring, "Flagged for
Architect/QA follow-up (e.g. a reranker)") rather than further threshold
tuning.

**Retrieval funnel (starting numbers — tunable by RAG/QA against
`evaluation/scripts/run_evaluation.py`, not final):**
- Stage 8 (Similarity Search): widen from today's `top_k=5` to
  **`top_k=20`** candidates, still gated by the existing
  `MIN_SIMILARITY_SCORE=0.45` as a **cheap pre-filter** — its job changes
  from "the final relevance gate" to "cut obvious noise before the more
  expensive cross-encoder runs on it," which is still a real filtering step
  since `count_chunks_for_knowledge_base` can return dozens of chunks from a
  KB that has nothing to do with the question.
- Stage 8.5 (Reranking, new): `CrossEncoder.predict([(rewritten_query, chunk.text) for chunk in candidates])`
  over the ≤20 survivors of Stage 8; re-sort descending by rerank score.
  The reranker scores the **rewritten** query from ADR-16 (not the raw,
  possibly-ambiguous original message) against each candidate — the
  referent-resolution problem ADR-16 exists to fix applies to the
  reranker's judgment exactly as it does to embedding and generation.
- Stage 9 (Top-K Retrieval, modified): apply a **new** `MIN_RERANK_SCORE`
  threshold to the reranked list, then cap at a final **`top_n=5`** (kept
  equal to today's value to preserve Stage 10's ~4,000-char/5-chunk context
  budget unchanged; QA may find 3 sufficient once reranking improves
  precision, but that's a follow-up tuning question, not this ADR's call).
  Below-threshold → the same empty-list short-circuit Stage 10 already
  implements (no chunks reach the LLM, no code-path change needed there).

**How this changes the no-context decision:** `MIN_RERANK_SCORE` — not
`MIN_SIMILARITY_SCORE` — becomes the actual final arbiter of "is there
real, on-topic content for this question." `MIN_SIMILARITY_SCORE` survives
only as Stage 8's cheap pre-filter (its purpose: bound how many candidates
the more expensive cross-encoder step has to score, not decide relevance).
The exact `MIN_RERANK_SCORE` numeric value is **not specified here** — a
cross-encoder's raw output range is not a bounded, cross-model-comparable
similarity like cosine is (it depends on the model's training objective and
whether a sigmoid is applied), so, exactly like `MIN_SIMILARITY_SCORE=0.45`'s
own history (`retriever.py`'s docstring), this must be empirically measured
against real demo-KB and no-context-control scores before being hardcoded —
this is the RAG/QA implementation pass's job, not an architectural decision
made in the abstract.

**Model loading:** load `CrossEncoder(...)` once per process at first use
(module-level singleton, mirroring `embed.py`'s `get_model()` and
`generation.py`'s `get_client()` pattern) — never per-request, for the same
cold-start-cost reason ADR-06 already established.

**Validation:** this ADR's expectation that reranking closes the
`no_context_precision` gap must be confirmed, not assumed — re-run
`evaluation/scripts/run_evaluation.py` after implementation and compare
against `evaluation/results/20260906T052601Z.json`'s baseline
(`no_context_precision: 0.6`) as the RAG/QA agents' acceptance check.
Latency added by the cross-encoder step (≤20 short-passage forward passes
on Render's free-tier CPU) should also be measured directly rather than
assumed acceptable, per this project's established practice of verifying
real behavior over live infrastructure (ADR-07, ADR-08's own lessons).

**Advantages:** zero new dependency, zero new secret/account, zero added
recurring cost; directly targets a documented, measured quality gap rather
than a speculative one; isolated behind one new module
(`retrieval/reranker.py`), same "swap one function" portability pattern as
ADR-06/ADR-08.

**Disadvantages:** added CPU latency per chat request (unmeasured until
implemented — flagged above); a second model to keep loaded in the free-tier
instance's limited RAM alongside the embedding model, Qdrant client, and
Groq client (all currently small models; expected to still fit Render's
free-tier ceiling per ADR-03/ADR-10, but not verified in this ADR); one more
empirically-tuned magic number (`MIN_RERANK_SCORE`) for a future
maintainer to understand, mitigated by requiring the same documented
empirical-tuning-note convention `retriever.py` already establishes for
`MIN_SIMILARITY_SCORE`.

**Free-tier implications:** $0 — local CPU inference, no API, no rate
limit, same free-tier profile as ADR-06's embedding model.

**Future migration:** swap the cross-encoder model name, or replace the
local `CrossEncoder` call with a hosted reranking API, by changing
`retrieval/reranker.py` only; the funnel shape (widen → rerank → cap)
is provider-agnostic in the same way `vector_store.py`'s adapter boundary
already isolates Qdrant (ADR-07's own migration path).

---

## ADR-18: Real-Time Chat Progress — Chunked NDJSON Streaming over `POST /chat`

**Decision:** `POST /chat` changes from a single synchronous JSON response to
a chunked, newline-delimited-JSON (NDJSON) streaming response. The backend
yields one small JSON object per real pipeline milestone as it actually
completes (query rewrite/embed/retrieve, rerank/threshold, generation,
post-generation checks), and a final object carrying the same `answer`/
`sources[]` payload the endpoint has always returned. The frontend replaces
its generic "Thinking…" spinner with one of four real-progress labels
(`SEARCHING`/`RETRIEVING`/`GENERATING`/`VALIDATING`) that track genuine
backend execution time, not a fake timer.

**Options considered:**
1. A separate `GET /chat/{job_id}/progress` endpoint the frontend polls
   (job-table pattern).
2. WebSocket connection for the chat request.
3. Server-Sent Events via the browser's native `EventSource`.
4. Chunked NDJSON body over the existing `POST /chat`, read via
   `fetch()` + `response.body.getReader()` (chosen).

**Selected:** Option 4.

**Reason:** Option 1 requires inventing server-side job state (an in-memory
job table keyed by a new id, a second endpoint, a client polling loop) purely
to narrate a single request that already completes in a few seconds
end-to-end — disproportionate complexity for this project's scale, and a
second persistence concern ADR-12 deliberately avoided elsewhere. Option 2
adds a new connection lifecycle (open/close/reconnect handling) and, on most
minimal setups, a new server-side dependency, for no benefit over a one-shot
stream when there is exactly one logical exchange per chat turn. Option 3 is
the common naive suggestion here but does not actually work for this
endpoint: `EventSource` only issues `GET` requests and cannot carry a custom
request body or the `X-Session-Token` header this app already depends on for
user-KB auth (ADR-14) — `/chat` needs to send `knowledge_base_id`/`message`/
`conversation_history` as a POST body, which `EventSource` structurally
cannot do. Option 4 needs **zero new dependency on either side** — Starlette's
`StreamingResponse` (already inside the installed `fastapi`/`uvicorn` stack,
ADR-03) and the browser's native `fetch` streaming body reader are both
already available — and keeps the single-request/single-response mental
model this project's other ADRs consistently prefer (ADR-02/05/11/13):
one code path, no job-state, no new protocol.

**Wire format:** `media_type="application/x-ndjson"`; one JSON object per
line (`\n`-terminated), each `{"stage": "..."}` plus any stage-specific
fields:

```
{"stage": "SEARCHING"}
{"stage": "RETRIEVING"}
{"stage": "GENERATING"}
{"stage": "VALIDATING"}
{"stage": "COMPLETED", "answer": "...", "sources": [ { "document_id": ..., "document_name": ..., "locator": ..., "snippet": ..., "is_removed": false } ]}
```

Mid-stream failure (HTTP status is already 200 and cannot change once
streaming has begun, so the error is signaled in-band):

```
{"stage": "ERROR", "code": "LLM_UNAVAILABLE", "message": "The answer service is temporarily unavailable. Please try again shortly.", "retryable": true}
{"stage": "ERROR", "code": "VECTOR_STORE_UNAVAILABLE", "message": "The knowledge base search is temporarily unavailable. Please try again shortly.", "retryable": true}
{"stage": "ERROR", "code": "INTERNAL_ERROR", "message": "An unexpected error occurred. Please try again shortly.", "retryable": false}
```

A request that fails validation **before** any pipeline stage begins
(unknown `knowledge_base_id`, forbidden `kb_user_*`, empty KB, empty/oversized
`message`) is unaffected by any of this: it never opens a stream at all —
`chat.py` performs exactly the same checks it does today and raises the same
`ApiError` → plain `404`/`403`/`503`/`400` JSON response, since nothing about
those needs progress reporting (they're known before any real work starts).

**Stage-to-pipeline mapping (`docs/RAG_PIPELINE.md` stage numbers):**

| UI stage | Label | Backend work covered | Code location |
|---|---|---|---|
| `SEARCHING` | "Searching documents…" | Stage 6.5 (query rewrite) + Stage 7 (embed) + Stage 8 (candidate-pool vector search) | `chat.py`: `query_rewrite.rewrite_query`, `embed_query`, `retriever.retrieve` |
| `RETRIEVING` | "Retrieving relevant information…" | Stage 9 (`MIN_SIMILARITY_SCORE` threshold + cap — ADR-17's reranking step was reverted; see ADR-17's "Reverted" note) | `chat.py`: `retriever.retrieve` |
| `GENERATING` | "Generating answer…" | Stage 10 (context construction) + Stage 11 (prompt) + Stage 12 (Groq call) | `generation.answer_question` |
| `VALIDATING` | "Checking sources…" | Stage 14 (citation resolution) + **new**: per-cited-document existence check | `generation.build_sources` + new `chat.py` helper (see below) |

Each stage event is yielded *before* its corresponding work begins and the
next event is yielded only once that work's real result is available — a
50ms rerank flashes the `RETRIEVING` label past almost instantly; a slow Groq
completion holds `GENERATING` on screen for exactly as long as the real call
takes. No `sleep`/timer of any kind is introduced anywhere in this design.

**What "VALIDATING" actually does (closes a real, pre-existing gap —
FR-042):** investigation confirmed there is **no existing distinct
post-generation validation step** in the current pipeline —
`generation.build_sources()` hardcodes `"is_removed": False` on every source,
unconditionally, always has (`retrieval/generation.py` line 158). Yet
`docs/DATA_MODEL.md` §7 and `docs/REQUIREMENTS.md` FR-042 already specify
real semantics for this exact field: *"if the underlying document has been
deleted after an answer was generated, the citation still renders but is
marked as referring to a removed document."* This is a genuine, already-
specified requirement that was simply never implemented — the frontend's
`chat-source--removed` CSS/JSX (`ChatPanel.jsx`) has been dead code waiting
for a backend that actually sets `is_removed: true`. Rather than inventing a
fake "validating" stage, this ADR uses the real opportunity: `VALIDATING`
now performs one cheap, real check per **distinct** cited `document_id`:

```
for each distinct document_id in sources:
    if is_demo_document_id(document_id):        # store.py — permanent, never removed
        exists = True
    else:
        exists = vector_store.count_chunks_for_document(document_id, knowledge_base_id=kb_id) > 0
    mark every source row for that document_id with is_removed = not exists
```

This directly answers "did the source this answer cites still exist by the
time we finished generating?" — a real race (`DELETE /documents/{id}` running
concurrently with an in-flight chat request that already retrieved chunks
from that document moments earlier) that the current single-shot request
already cannot detect. Both helper functions already exist
(`vector_store.count_chunks_for_document`, `store.is_demo_document_id`) —
**zero new backend dependency**. Typical cost: 0–5 extra Qdrant count calls
per chat turn (one per distinct cited document, almost always ≤5 per
Stage 9's `TOP_N=5` cap). If this check itself fails (Qdrant hiccup), it is
caught and logged server-side, falling back to `is_removed: False` for the
affected source(s) — the same graceful-degrade-rather-than-hard-fail
philosophy ADR-16 already established for query rewriting: a diagnostic
enhancement's own failure must never turn an otherwise-successful answer
into an error.

**Error taxonomy (preserves today's retryable/non-retryable behavior
exactly, see Frontend section below):**

| Raised where | Event `code` | `retryable` | Equivalent to today's… |
|---|---|---|---|
| `generation.answer_question` raises `LLMUnavailableError` | `LLM_UNAVAILABLE` | `true` | `502 LLM_UNAVAILABLE` (FR-054) |
| `embed_query`/`retriever.retrieve`/`reranker.rerank`/`apply_rerank_threshold` raise (Qdrant exhausted its own internal retries, or any exception in that stage) | `VECTOR_STORE_UNAVAILABLE` | `true` | **New — closes a latent FR-055 gap.** FR-055 already requires vector-DB failures to surface as *retryable*, distinguished from an LLM failure, but `chat.py` today has no explicit handling for this at all — an uncaught exception there currently falls through to the global `500 INTERNAL_ERROR` handler, which today's frontend treats as **non-retryable** (`status !== 502/0`). This ADR's restructuring of `chat.py` into explicit per-stage try/except blocks (needed anyway, to emit a clean stream-terminating event instead of an abrupt disconnect) is the natural place to finally implement FR-055 as specified. |
| Anything else unexpected | `INTERNAL_ERROR` | `false` | `500 INTERNAL_ERROR` (unchanged fallback) |

**Frontend error handling — additive, not a rewrite of `errorDisplay()`:**
`ApiError` (`frontend/src/api/client.js`) gains one new optional 4th
constructor argument, `retryable`, defaulting to `undefined`. `errorDisplay()`
(`ChatPanel.jsx`) changes by exactly one line:
`const retryable = err.retryable ?? (err.status === 502 || err.status === 0)`.
Every existing call site (`/health`, `/knowledge-bases`, `/documents/*`, and
`/chat`'s own pre-stream 400/403/404/503 paths) never passes a 4th argument,
so `err.retryable` is `undefined` there and `??` falls through to exactly
today's status-based check — **zero behavior change** for every
already-tested error path. Only the new streaming error events construct
`ApiError` with an explicit `retryable` boolean, carried over the wire
verbatim from the table above instead of being inferred from an HTTP status
that no longer exists once the 200 response has started streaming.

**Concurrency/cancellation (frontend-only, no backend state needed — the
backend stays exactly as stateless as ADR-12 established):** `ChatPanel.jsx`
keeps a `requestIdRef` (incrementing counter) and an `abortControllerRef`.
Before starting any new streamed request: abort the previous
`AbortController` (if one exists), increment `requestIdRef`, create a fresh
`AbortController`, and pass its `signal` into `fetch()`. The `onStage`
callback and the final resolve/reject handling both re-check
`requestIdRef.current === myRequestId` before touching React state — belt
and suspenders on top of the abort itself, since an already-buffered NDJSON
line read a moment before `abort()` took effect could otherwise still fire
one stale `onStage` call. A cancelled/superseded request's status is removed
from the UI the instant `abort()`/the id-check fires — it never renders a
stage from an older request once a newer one has started, and an aborted
fetch's `AbortError` is treated as a silent no-op (no error banner — the
request was deliberately superseded, not genuinely failed). Note: today's
`isSending` guard already prevents the composer/submit/retry/suggestion-card
paths from firing a second request while one is in flight, so this mechanism
is defense-in-depth against fast-double-click/StrictMode-style races rather
than a scenario reachable through the normal UI today — cheap insurance,
built exactly to the letter of the stated requirement. Aborting only stops
the **client from displaying further updates**; it does not attempt to
cancel backend compute already in flight (e.g., a Groq call already sent) —
identical in kind to today's behavior where an abandoned tab's pending
`fetch()` promise simply resolves into nothing once nobody is listening.

**Cold-start interaction:** `COLD_START_DELAY_MS`/"Waking up the server…"
is kept, but re-targeted: the existing 5-second timer now clears on the
**first stage event received** (not just at the end of the whole request,
as today). This is a strictly better signal than before — Render free-tier
spin-up (ADR-10) blocks the TCP/HTTP connection itself, so it delays literally
every byte including the very first `SEARCHING` event; "no stage event yet
after 5s" is a more accurate cold-start proxy than today's "still `isSending`
after 5s" (which could not distinguish a real cold start from a merely slow
pipeline before this ADR, since no progress signal existed to tell them
apart). Once real progress is visible, the cold-start message becomes rarer
to see at all — it now only ever appears during the genuine pre-connection
spin-up window, disappearing the instant the first real stage streams in,
rather than potentially lingering through a slow-but-not-actually-cold
request as it could before.

**What does not change:** the final `answer`/`sources[]` field shapes
(`docs/DATA_MODEL.md` §7, `docs/API.md`); `errorDisplay()`'s retryable logic
for every already-existing error path; demo-vs-user-KB behavior (pre-stream
validation is untouched, and `is_demo_document_id` keeps demo sources
permanently non-removed); source rendering/dedup in `ChatPanel.jsx`; and no
retrieval/generation/reranking logic is reordered or altered — every yield
point sits *between* existing steps, never inside or around their scoring/
thresholding.

**Advantages:** zero new dependency on either side; narrates genuine backend
execution time (a fast stage flashes by, a slow one stays visible exactly as
long as it takes); finally implements two already-specified requirements
that had silently regressed to no-ops (FR-042's removed-document marker,
FR-055's retryable vector-store error); preserves every existing
error-handling/rendering behavior via one additive field.

**Disadvantages:** `POST /chat`'s wire contract is a breaking change for any
caller expecting the old single-JSON-body shape — this project's own test
suite (`backend/tests/test_api.py`) and evaluation harness
(`evaluation/scripts/run_evaluation.py`, via `httpx`) both currently assert
a single `.json()` body and must be updated in the same implementation pass
to parse the NDJSON stream and read the `COMPLETED` event's payload (a small,
mechanical change — read the response as text/lines, `json.loads` each
line, use the last `COMPLETED`/`ERROR` event — not a redesign of either
tool). Chosen over a content-negotiated dual-response-path endpoint (branch
on `Accept`/a query flag to serve old-style JSON to old callers) because a
permanent second code path is exactly the kind of complexity ADR-02/05/11/13
already reject elsewhere in this project for a single-consumer API with no
external third-party clients to protect.

**Free-tier implications:** $0 — no new external service, no new package;
same Groq/Qdrant free-tier accounts and call volumes as today (the new
`VECTOR_STORE_UNAVAILABLE`/FR-042 paths add at most a handful of extra Qdrant
`count` calls per turn, negligible against Qdrant's free-tier ceiling,
ADR-07). Deployment-time verification still owed before Phase 21: confirm
Render's free-tier request path does not buffer a chunked/`StreamingResponse`
body (no reverse-proxy/gzip layer currently sits in front of it —
`backend/main.py` adds no compression middleware — but per this project's
established practice of verifying real infrastructure behavior rather than
assuming it, ADR-07/08's own lesson, this should get one live smoke test
once `render.yaml`/deployment exists, not be assumed).

**Future migration:** if a future feature needs true mid-flight
cancellation of backend compute (not just the frontend ceasing to display
updates), the generator-based structure this ADR introduces is already the
right shape to add a `request.is_disconnected()` check between stages
(Starlette feature) — not required for this ADR's stated goal (progress
*display*), so deliberately left out of scope here.

**Files touched by the subsequent implementation pass:**
- Backend: `backend/api/chat.py` (generator-based streaming orchestration,
  per-stage try/except, `StreamingResponse`), `backend/retrieval/generation.py`
  (`build_sources` stays pure; the new existence-check helper can live in
  either `chat.py` or a small addition to `retrieval/generation.py` —
  implementer's call), no changes needed to `retriever.py`/`reranker.py`
  themselves (only how their outputs are wrapped in `chat.py`).
- Backend tests/eval: `backend/tests/test_api.py`, `evaluation/scripts/run_evaluation.py`
  (both must switch from reading one JSON body to reading the NDJSON stream
  and extracting the `COMPLETED`/`ERROR` event — required, not optional).
- Frontend: `frontend/src/api/client.js` (`ApiError`'s new optional
  `retryable` param; new `sendChatMessageStreaming` function alongside/
  replacing `sendChatMessage`), `frontend/src/components/ChatPanel.jsx`
  (`currentStage` state replacing `isSending`-only status text, the
  `requestIdRef`/`abortControllerRef` concurrency guard, the retargeted
  cold-start timer), `frontend/src/components/ChatPanel.test.jsx` (mocks
  currently stub `sendChatMessage` as a plain resolving/rejecting promise —
  must be updated to simulate a staged stream and assert `onStage` sequencing).
- Docs (this pass): `docs/API.md` (`POST /chat` contract),
  `docs/RAG_PIPELINE.md` (Stage 14 amendment + streaming-stage cross-reference),
  `ARCHITECTURE.md` §6 (sequence diagram).

---

## ADR-19: Backend Hosting — Google Cloud Run (supersedes ADR-10's Render)

**SUPERSEDED (2026-09-06), back to Render — see ADR-20:** the user
explicitly chose not to take on a Google Cloud account for this project and
asked instead for the actual root cause (memory, not platform) to be fixed
so the app could stay on Render. ADR-20 replaces the embedding runtime
(sentence-transformers/torch → fastembed/ONNX Runtime), which turned out to
be the real fix this ADR's own "Why this happened" section was one
diagnostic step short of: it correctly identified that the *embedding
model* (not the reranker) was the memory driver, but concluded the fix had
to be a bigger-RAM platform, without separately testing whether a
non-PyTorch runtime for that same model would fit Render's free tier
instead. It does. Backend hosting reverts to Render (`render.yaml`,
already prepared and untouched this whole time); `backend/Dockerfile` and
this ADR's content are preserved below, unused for now, as a documented
option if a future memory increase (e.g. reranking coming back) ever
outgrows Render's free tier again — per this project's established practice
of not deleting superseded infrastructure decisions.

**Decision:** Move the backend off Render's free web service onto Google
Cloud Run, deployed via Cloud Run's "continuously deploy from a repository"
flow (Cloud Build reading a new `backend/Dockerfile`), rather than staying
on Render's native-Python buildpack. `render.yaml` is left in the repository
unchanged, as a documented paid-tier fallback (Render Standard, if the user
ever chooses to pay for more RAM there instead) — not deleted, per this
project's established practice of preserving superseded infrastructure as a
recorded option rather than erasing it.

**Why this happened — evidence, not speculation:** ADR-17's revert already
established that Render's free-tier **512MB RAM ceiling** was the real
constraint (loading the embedding model alongside a reranker OOM-crashed the
process). Removing the reranker was expected to bring the process back
under that ceiling. It did not. After the revert, repeated live testing
against the deployed Render free instance showed: `GET /health` reliably
returns `200` (the process is up and idle), but a real `POST /chat` request
— which must load `BAAI/bge-small-en-v1.5` via `sentence-transformers`/
CPU-`torch` to embed the query, on top of FastAPI/uvicorn/Groq-client/
Qdrant-client overhead already resident — reliably returns a `502` shortly
after the request starts, then the instance restarts. This confirms the
embedding model alone (not the now-removed reranker) is enough to exceed
512MB under real request load, once actual inference memory (not just
import-time weight loading) is accounted for. **The problem is Render's
free-tier RAM ceiling itself, not any one model choice this project made on
top of it** — no amount of further application-level memory tuning changes
a hard 512MB platform limit.

**Options considered:**
1. Stay on Render free tier; try to shrink memory further (smaller embedding
   model, quantization, lazy-unload-after-request).
2. Pay for Render Standard (2GB+ RAM, ~$7-25/mo) — rejected outright, since
   NFR-001 (zero cost) is a hard project requirement, not a preference.
3. Move to a different free-tier PaaS with more RAM headroom and no card
   required (Fly.io free allowance, Google Cloud Run, Google Cloud Run
   equivalents).
4. Google Cloud Run (chosen).

**Selected:** Option 4 — Google Cloud Run.

**Reason:** Cloud Run's free tier allows configuring container memory up to
32GB per instance (no fixed 512MB ceiling like Render free), while still
being genuinely free: ~180,000 vCPU-seconds and ~360,000 GiB-seconds of
free compute per month, plus 2 million free requests/month, with **no
credit card required to use the free tier**. At a chosen 1GiB/1vCPU
allocation (see below), that free compute allowance comfortably covers a
low-traffic portfolio demo — far more headroom than Render free's 512MB
ever gave this specific workload, which is the exact dimension that broke.
Option 1 was rejected because it treats a hard platform ceiling as a tuning
problem when live evidence (above) already shows the current, already-
reverted-once configuration doesn't fit — further shrinking now risks
degrading answer quality (a smaller embedding model) to chase a limit that
a different free tier simply doesn't impose. Option 3's Fly.io alternative
was not pursued once Cloud Run's memory/compute free-tier numbers were
confirmed sufficient and no worse in card-free terms.

**What changes:**
- New `backend/Dockerfile` and `backend/.dockerignore` (this ADR's
  implementation) — Cloud Run's "deploy from a repository" flow requires a
  Dockerfile (unlike Render's native Python buildpack); Cloud Build reads
  it directly, no local Docker/`gcloud` install needed by anyone deploying
  this project.
- Build context / source location must point at `backend/`, not the repo
  root — the Dockerfile lives inside `backend/` (monorepo layout, same
  reason `render.yaml` sets `rootDir: backend`).
- Same 3 required secrets (`GROQ_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`)
  plus `CORS_ALLOWED_ORIGIN`, now set in Cloud Run's console instead of
  Render's dashboard — no code change (ADR-15's backend-only environment
  variable pattern is provider-agnostic by design).
- `$PORT` is still read dynamically by `uvicorn` at container start (Cloud
  Run's own convention, coincidentally identical to Render's) — no
  application code changes.
- `OMP_NUM_THREADS`/`MKL_NUM_THREADS`/`OPENBLAS_NUM_THREADS=1` — the same
  BLAS-thread-pool cap `render.yaml` already carried — is set as `ENV` in
  `backend/Dockerfile` directly instead of in a provider dashboard, since
  Cloud Run's console env vars would need to be re-entered by the user
  anyway and baking the (non-secret) values into the image is one less
  manual step for a value that never changes per-deploy.

**What does not change:** the RAG pipeline, ingestion, retrieval, and
generation code are completely untouched — this is purely an infrastructure
swap. `render.yaml` stays in the repository, functional and accurate, as a
documented paid-tier path (Render Standard) if the user ever prefers Render
enough to pay for it. Qdrant Cloud (ADR-07) and Groq (ADR-08) are unchanged;
Cloudflare Pages (ADR-09) frontend hosting is unchanged — only
`VITE_API_BASE_URL` will need updating once the Cloud Run service URL
exists (`docs/DEPLOYMENT.md`).

**Cold starts:** Cloud Run's scale-to-zero (`min-instances=0`, recommended
here to stay within free-tier compute-second allowances) has the same
category of cold-start behavior Render's free tier already had — the
frontend's existing "waking up" UX handling (`docs/UI_UX.md`, built during
earlier phases for exactly this Render behavior) applies unchanged and
needs no rework. `min-instances=1` remains available if the user later
wants to eliminate cold starts, at the cost of continuous billing outside
the free tier — documented as a tradeoff, not a recommendation.

**Advantages:** genuinely free tier at real headroom for this workload's
actual measured memory need (evidenced above, not assumed); no card
required; same Dockerfile-based deploy works identically if the user later
wants to self-host or move to another container platform (Cloud Run,
unlike Render's buildpack, is a standard OCI image — strictly more portable,
not less); no application code changes, only infrastructure/docs.

**Disadvantages:** requires a `Dockerfile`/`.dockerignore` that didn't
previously exist (small, one-time authoring cost); Cloud Run's free-tier
compute-second accounting is usage-metered rather than Render's flat
instance-hours model, so very bursty/heavy traffic (unlikely for a
portfolio demo) could in theory approach the free allowance faster than
Render's simpler 750-hour figure — monitored per `docs/DEPLOYMENT.md`'s
Cloud Run section, same spirit as the existing Qdrant suspension-risk
monitoring practice (ADR-07).

**Free-tier implications:** $0, no card entered, provided free-tier compute-
second/request allowances aren't exceeded (unlikely at this traffic scale;
monitored per `docs/DEPLOYMENT.md`).

**Future migration:** if free-tier compute is ever actually exceeded, the
options are the same shape as Render's own future-migration note — pay for
more Cloud Run compute, or move the same `backend/Dockerfile` to any other
OCI-compatible free tier (Fly.io, etc.) with no application code change,
since the container image itself is the portable unit.

**Files touched by this ADR's implementation:** `backend/Dockerfile` (new),
`backend/.dockerignore` (new), `docs/DEPLOYMENT.md` (new Cloud Run section,
Render section marked superseded), `docs/ENVIRONMENT.md` (Cloud Run env var
notes), `ARCHITECTURE.md` §1/§9 (deployment diagrams). `render.yaml` is
explicitly untouched (kept as the documented paid-tier fallback).

---

## ADR-20: Embedding Runtime — fastembed/ONNX Runtime (supersedes ADR-06's
sentence-transformers/torch; reverts ADR-19 back to Render)

**Decision:** Run the local embedding model (`BAAI/bge-small-en-v1.5`,
unchanged, ADR-06) via `fastembed` — Qdrant's own embedding library, which
loads a quantized ONNX build of the same model through `onnxruntime` —
instead of `sentence-transformers`/PyTorch. No other part of the RAG
pipeline changes: same model weights (a quantized export of the same
checkpoint), same 384-dim vector space, same manually-applied BGE
query-instruction prefix (`embed.py`'s `QUERY_INSTRUCTION_PREFIX`), same
public `embed_texts()`/`embed_query()` function signatures used by every
call site (`ingestion/pipeline.py`, `scripts/seed_demo_kb.py`,
`api/chat.py`).

**Why this happened — evidence, not speculation:** ADR-19 correctly
diagnosed that the embedding model alone (not the already-reverted
reranker, ADR-17) was enough to exceed Render free tier's 512MB RAM ceiling
under real `/chat` request load, and concluded from that evidence that the
fix had to be a bigger-RAM hosting platform (Google Cloud Run). The user
explicitly declined that path — no interest in creating/managing a Google
Cloud account for a portfolio project — and asked instead whether the
actual memory driver could be reduced directly. It could: PyTorch itself
(not the model weights) was never isolated as a variable in ADR-19's
investigation. Measured directly this session: loading the fastembed model
and running a real query embedding plus an 8-chunk batch embed in the same
process totals **~191MB RSS** (18MB baseline → 175MB after model load →
191MB after real inference) — comfortably under the 512MB ceiling with
room for FastAPI/uvicorn/Groq-client/Qdrant-client overhead on top, which
is the same overhead ADR-19 observed already resident alongside the
torch-based model when Render 502'd. A genuinely fresh `pip install -r
requirements.txt` into an empty venv (verified this session) now pulls in
`fastembed`+`onnxruntime` and nothing else in that dependency family — no
`torch`, no `transformers`, no `sentence-transformers` — confirming this
isn't a partial reduction that still carries the old weight transitively.

**Options considered:**
1. Keep `sentence-transformers`/torch; shrink further (smaller model,
   quantization, lazy-unload-after-request) — this is exactly ADR-19's
   rejected Option 1, and for the same reason: still carries PyTorch's own
   base memory cost regardless of model size, which the measurement above
   shows is not actually necessary to pay at all.
2. Move embeddings to a free hosted API, dropping local inference entirely
   — rejected: reverses ADR-06's "local embeddings, no external API/rate
   limit" decision, and the fastembed measurement above shows the ADR-06
   goal is achievable without that tradeoff.
3. `fastembed`/ONNX Runtime, same model (chosen).

**Selected:** Option 3.

**Reason:** Directly addresses the measured root cause (PyTorch's own
resident memory footprint, not model size or reranking) with the smallest
possible blast radius — one module (`backend/ingestion/embed.py`) and one
dependency line (`backend/requirements.txt`) change; every other pipeline
stage, the Qdrant collection's vector dimensionality, and every call site's
function signature are untouched. Keeps ADR-06's "local, no external API"
property intact, unlike Option 2. Lets backend hosting revert to Render
(the user's stated preference) instead of adopting a new cloud provider
account purely to work around a dependency choice.

**What changes:**
- `backend/requirements.txt`: removed `torch==2.14.0+cpu` (and its
  `--extra-index-url` CPU-wheel pin) and `sentence-transformers==3.3.1`;
  added `fastembed==0.8.0`.
- `backend/ingestion/embed.py`: `get_model()` now constructs a fastembed
  `TextEmbedding(model_name=..., threads=1)` instead of a
  `SentenceTransformer`; `embed_texts()` calls fastembed's `.embed()`
  instead of `.encode()`. `threads=1` mirrors the existing
  `OMP_NUM_THREADS=1`-style BLAS-thread-pool cap already applied elsewhere
  around this model (`render.yaml`, `backend/Dockerfile`) — one more
  thread pool would add memory for negligible speed gain on a single
  shared free-tier vCPU. The query-instruction prefix is still applied
  manually in `embed_query()`, not via fastembed's own model-specific
  `query_embed()` method, so this exact, already-evaluated prefix behavior
  is unchanged by the runtime swap rather than depending on fastembed's own
  (undocumented, per-model) prefix logic.
- Backend hosting reverts to Render (`render.yaml`); ADR-19's Cloud Run
  path (`backend/Dockerfile`) is kept, unused, as a documented fallback —
  see ADR-19's superseded note.
- **Demo KB reseeded:** `backend/scripts/seed_demo_kb.py` was re-run
  against the live Qdrant Cloud cluster this session so `kb_demo`'s stored
  chunk vectors are embedded with the new fastembed runtime, matching the
  runtime that will embed future queries against them (same 23 chunks,
  same deterministic point IDs — an idempotent overwrite, not new data).
  Any other knowledge base (a user's uploaded-session KB) is embedded
  fresh at upload time either way, so no reseed is needed there.

**What does not change:** the RAG pipeline's stages, chunking, retrieval
thresholds, prompt construction, generation, and citation logic are
completely untouched — this is purely a swap of which library performs the
embedding computation, not what is computed. `docs/RAG_EVALUATION.md`'s
methodology is unchanged; a fresh evaluation run to confirm quality holds
under the new runtime was attempted this session but blocked by Groq's
free-tier daily token quota being exhausted mid-run (a real, observed `429
rate_limit_exceeded` from Groq, unrelated to this change) — see
`docs/RAG_EVALUATION.md`/`README.md` for the honest current state of that
re-validation. What *is* independently verified this session: all 8
`test_embed.py` unit tests (dimensionality, determinism, prefix
correctness, semantic-similarity ordering on real demo content) and the
full backend suite (157 tests) pass unchanged against the new runtime, and
one live end-to-end `/chat` call against the reseeded demo KB returned the
correct grounded, cited answer.

**Advantages:** removes the single largest dependency (and its transitive
`transformers`/`safetensors`/CUDA-adjacent tooling) from the backend
entirely; measured ~191MB RSS in the same scenario that previously
OOM'd/502'd on Render; keeps the project on Render (no new cloud account);
keeps ADR-06's "local, no external API" property; smaller Docker/venv
install footprint as a side effect (faster CI/build installs too).

**Disadvantages:** `fastembed`'s ONNX export is a quantized version of the
original checkpoint, not the exact same floating-point weights
`sentence-transformers` loaded — a theoretical (not measured-significant
here) precision difference in embedding vectors; per fastembed's own model
card, `BAAI/bge-small-en-v1.5` is documented as a model where the
query-instruction prefix is "not so necessary," a milder claim than the
original model card's own recommendation — this project keeps applying the
prefix regardless (see "What changes" above) rather than relying on that
weaker guidance, so this is a difference in documentation confidence, not
in this project's actual behavior.

**Free-tier implications:** $0, no card entered anywhere — unchanged.

**Future migration:** if a future feature (e.g. reranking returning, ADR-17)
pushes memory back over Render's free-tier ceiling even with this lighter
runtime, ADR-19's Cloud Run path is preserved and ready (`backend/Dockerfile`
already exists, untouched) as the next fallback before considering a paid
Render tier.

**Files touched by this ADR's implementation:** `backend/requirements.txt`,
`backend/ingestion/embed.py`, `backend/scripts/seed_demo_kb.py` (re-run
against live Qdrant, not code-changed), `docs/DEPLOYMENT.md` (Render section
restored as current), `docs/RAG_PIPELINE.md` (embedding stage description),
`ROADMAP.md` (Phase 21 status note), `README.md` (tech stack, evaluation,
limitations).
