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
