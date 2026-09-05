# Planning Validation Report

Final planning-phase deliverable. Confirms every prior deliverable exists,
satisfies its acceptance criteria, and agrees with every other deliverable.

> **Post-planning amendment (Phase 10):** this report's "Tech stack
> agreement" check below refers to `llama-3.3-70b-versatile`, the model
> planned at the time. Live verification against Groq's real API during
> implementation found that model had been removed from Groq's catalog;
> it was replaced with `qwen/qwen3.8-27b` (see ADR-08 in
> `docs/ARCHITECTURE_DECISIONS.md` for the full reasoning and evidence).
> This is left as a historical record of the planning-time decision rather
> than silently rewritten — every other document has been updated to the
> current model name.

## Deliverable Checklist

Requirements
[x] Complete — `docs/REQUIREMENTS.md`. All FR-/NFR- IDs unique, each with an
acceptance criterion; V1 exclusions listed explicitly (§12); no requirement
implies a paid service.

Architecture
[x] Complete — `ARCHITECTURE.md`. High-level, frontend, backend, RAG,
ingestion, query, knowledge-base, storage, deployment architecture, and
security boundaries all covered, with 4 Mermaid diagrams (system overview,
ingestion sequence, query sequence, deployment).

Technology decisions
[x] Complete — `docs/ARCHITECTURE_DECISIONS.md`. 15 ADRs, each with
Decision/Options/Selected/Reason/Advantages/Disadvantages/Cost/Migration.
Covers all 15 required areas (React+Vite, CSS, FastAPI, Python, LangChain,
embedding model, vector DB, LLM, frontend hosting, backend hosting, storage
strategy, persistence strategy, document processing, KB isolation, API-key
management).

RAG pipeline
[x] Complete — `docs/RAG_PIPELINE.md`. All 14 stages (extraction through
source attribution), each with input/processing/output/technology/failure
modes/validation method; full configuration table; explicit grounding
strategy.

Data model
[x] Complete — `docs/DATA_MODEL.md`. All 9 required entities defined
(KnowledgeBase, Document, DocumentChunk, Embedding, ChatSession, ChatMessage,
SourceReference, EvaluationCase, EvaluationResult), including the two
entities explicitly designed *not* to have server-side persistence
(ChatSession, ChatMessage) with the reasoning stated inline.

API contract
[x] Complete — `docs/API.md`. All 7 required endpoints plus `GET /health`,
each with method/URL/purpose/request/response/status codes/validation/error
responses/auth/rate-limit notes and example JSON bodies. No secret values in
any example.

UI/UX
[x] Complete — `docs/UI_UX.md`. All 13 required screens/states, each with
sees/actions/disabled/loading/error behavior; closes with an explicit
per-criterion checklist.

Document processing
[x] Complete — `docs/DOCUMENT_PROCESSING.md`. Formats, size/count limits,
validation order, extraction, empty/corrupted handling, full status state
machine (diagram + transition table), explicit no-retry policy,
PROCESSING-time user behavior, demo-KB seeding process.

Security
[x] Complete — `docs/SECURITY.md`. All 11 required threat areas covered,
each with Risk/Mitigation/V1 implementation/Future improvement; closes with
an explicit per-criterion checklist.

Testing
[x] Complete — `docs/TEST_STRATEGY.md`. Four test levels with named example
tests, explicit scenario coverage for all 10 required areas, and an explicit
statement separating evaluation from CI-gated testing.

RAG evaluation
[x] Complete — `docs/RAG_EVALUATION.md` + `evaluation/` scaffold
(`dataset/`, `scripts/`, `results/`, `README.md`). All 13 required sections
present; dataset structure defined without fabricating demo content that
doesn't exist yet; no metric asserted as already measured.

Deployment
[x] Complete — `docs/DEPLOYMENT.md`. Frontend/backend/vector/document
storage/LLM sections each with cost model; cold starts, persistence risks,
CORS, env vars, secret management, deployment sequence, key rotation, and
billing-avoidance all covered.

Environment configuration
[x] Complete — `docs/ENVIRONMENT.md` + `.env.example`. Every variable
documented (name/purpose/required/placeholder/location/secret-or-not); no
real credential present; local vs. production distinguished.

Roadmap
[x] Complete — `ROADMAP.md`. All 24 required phases (0–23), each with
objective/prerequisites/tasks/files/validation/definition-of-done, plus an
explicit dependency graph.

Agents
[x] Complete — `.claude/agents/` (architect, frontend, backend, rag, qa,
security, devops, documentation). Each with role/responsibilities/files it
may and should not modify/inputs/outputs/validation responsibilities/when to
invoke.

README
[x] Complete — `README.md`. All 15 required placeholder sections present;
no feature claimed as implemented (explicit status banner at the top).

---

## Cross-Document Consistency Checks Performed

- **Tech stack agreement:** every mention of the stack (React+Vite/vanilla
  CSS, FastAPI/Python, LangChain loaders+splitters only, local MiniLM
  embeddings, Qdrant Cloud free tier, Groq `llama-3.3-70b-versatile`,
  Cloudflare Pages, Render free tier) across `ARCHITECTURE.md`,
  `docs/ARCHITECTURE_DECISIONS.md`, `docs/RAG_PIPELINE.md`,
  `docs/DEPLOYMENT.md`, and `README.md` is identical — no document proposes
  a different provider or model.
- **API ↔ Architecture agreement:** every endpoint in `docs/API.md` maps to
  a component in `ARCHITECTURE.md` §3's file layout; every status code
  referenced in `docs/UI_UX.md` §13 and `docs/TEST_STRATEGY.md` §2 traces
  back to a code defined in `docs/API.md`.
- **Data model ↔ RAG pipeline agreement:** `docs/DATA_MODEL.md`'s
  DocumentChunk/Embedding fields match the metadata produced by
  `docs/RAG_PIPELINE.md` Stage 4 exactly (`chunk_id`, `document_id`,
  `knowledge_base_id`, `document_name`, `chunk_index`, `page`).
- **Roadmap ↔ Requirements agreement:** every FR-/NFR- ID in
  `docs/REQUIREMENTS.md` is addressed by at least one roadmap phase (ingestion
  phases 5–12 cover FR-020–042; upload phases 13–14 cover FR-010–015,
  FR-050–056; phase 15 covers NFR-004; phase 20 covers NFR-005/006).
- **Configuration value agreement:** chunk size (800/120 overlap), top-K (5),
  similarity threshold (0.35), and temperature (0.1–0.2) appear identically
  in `docs/RAG_PIPELINE.md`, `docs/DOCUMENT_PROCESSING.md`, and
  `docs/TEST_STRATEGY.md` — no document restates them with a different
  number.
- **Path/filename consistency:** the demo-KB seed script and evaluation
  script paths (`backend/scripts/seed_demo_kb.py`,
  `evaluation/scripts/run_evaluation.py`) were found inconsistent across
  three files during this review and have been corrected in place
  (`ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/DOCUMENT_PROCESSING.md`,
  `ROADMAP.md`, `.claude/agents/qa.md`) to use one canonical name each.
- **Environment variable agreement:** `CORS_ALLOWED_ORIGIN`,
  `GROQ_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `EMBEDDING_MODEL_NAME`,
  `PORT` (backend) and `VITE_API_BASE_URL` (frontend) are used identically
  across `docs/ENVIRONMENT.md`, `.env.example`, `docs/DEPLOYMENT.md`, and
  `docs/SECURITY.md`.
- **No secrets present:** confirmed no real API key, URL with embedded
  credentials, or account identifier appears in any file written during
  this planning phase — every example value is an obvious placeholder.
- **No feature falsely marked complete:** `README.md` carries an explicit
  "planning phase, no code exists yet" banner; `docs/RAG_EVALUATION.md` and
  `evaluation/` explicitly state no evaluation has been run and no metric is
  a real result; `ROADMAP.md` phases are unchecked.

---

## Open Questions

1. **No `CLAUDE.md` existed in this repository at planning time.** This
   entire specification was derived from the deliverable brief supplied for
   this planning phase (a zero-cost RAG chatbot with a demo KB, user
   uploads, chat, and citations) rather than from a project-specific
   `CLAUDE.md`. If a `CLAUDE.md` is added later with different or additional
   requirements, every deliverable listed above must be reconciled against
   it — treat this report's "Complete" checkmarks as valid against *this*
   assumed brief, not as unconditionally final.
2. **Demo knowledge-base content is not yet chosen.** `docs/REQUIREMENTS.md`
   and `ROADMAP.md` Phase 4 require selecting real source documents; this
   must be public-domain or self-authored content, since no licensed
   third-party content may be redistributed in the repository.
3. **Groq and Gemini free-tier limits change over time** (documents in
   `docs/DEPLOYMENT.md` verified 2026-09) — re-verify current numbers
   immediately before Phase 21 (Deployment), not just at planning time.
4. **Exact demo-KB suggested questions** depend on the content chosen in
   (2) and cannot be finalized until then.
5. **Whether groundedness/relevance evaluation (docs/RAG_EVALUATION.md §6-7)
   using Groq-as-judge will fit within Groq's free daily request quota**
   alongside normal demo traffic is untested — if the evaluation set proves
   too large for the combined quota, the evaluation cadence (already
   documented as "not every commit") may need to be reduced further, or the
   evaluation set kept intentionally small (≤25 cases as scoped).

## Risks

**Technical:**
- Local CPU embedding inference (ADR-06) adds latency on Render's free-tier
  CPU, compounding with cold-start delay on a document's first-ever
  embedding call after a sleep cycle.
- FastAPI `BackgroundTasks` (ADR-13) runs in the same process as the web
  server — a large/slow document could momentarily compete with concurrent
  request handling on a single free-tier CPU core.

**Deployment/persistence:**
- Qdrant Cloud free-cluster inactivity suspension (7 days) / deletion (28
  days) is the single largest operational risk in this plan (ADR-07,
  `docs/DEPLOYMENT.md`). Mitigated for the demo KB via a one-command reseed
  script; **not** mitigated for user-uploaded KBs, which are simply lost —
  acceptable only because no persistence guarantee is promised to anonymous
  sessions.
- Render's 750 free instance-hours/month is close to a single always-on
  service's ~730 hours/month; running any second free service on the same
  account risks exceeding the cap.

**Cost:**
- No paid service is required for V1 (verified in `docs/DEPLOYMENT.md`'s
  acceptance check), but every provider's free-tier terms can change
  unilaterally at any time — this plan has no defense against a provider
  discontinuing its free tier entirely, beyond ADR-level portability
  (each external dependency is swappable behind one adapter).

**Security:**
- Prompt injection via uploaded document content is mitigated, not solved
  (`docs/SECURITY.md`) — this is an industry-wide open problem, not a gap
  specific to this project's design.
- No rate limiting in V1 (`docs/API.md`, `docs/SECURITY.md`) means a single
  bad actor could exhaust the shared Groq/Qdrant free quota for all
  visitors; accepted as a V1 risk given the project's portfolio scale.

**Implementation:**
- The LangChain-for-loaders-only boundary (ADR-05) requires discipline to
  maintain — it would be easy to accidentally reach for a LangChain chain/
  agent abstraction later and blur the boundary this plan deliberately drew.
- Groq-as-judge for groundedness/relevance evaluation (see Open Question 5)
  is a heavier-weight evaluation method than originally scoped and may need
  revisiting if it proves quota-expensive.

## Recommended V1

Exactly what `docs/REQUIREMENTS.md` §1–11 specifies: a demo knowledge base
answerable with zero setup; user upload of 1–5 files (PDF/DOCX/TXT/MD, ≤5MB
each) into a session-private knowledge base; chat scoped to exactly one
active knowledge base at a time; every answer either grounded with visible
citations or the explicit no-context response; the full error-handling
matrix in `docs/REQUIREMENTS.md` §9; the entire stack running on free-tier
infrastructure with no payment method entered anywhere.

## Explicitly Deferred

Everything listed in `docs/REQUIREMENTS.md` §12: user authentication/
accounts, cross-session or cross-device chat history, cross-knowledge-base
search, in-place document editing, original-file re-download, streaming
token-by-token responses, any paid tier of any provider, an admin/analytics
dashboard, file formats beyond PDF/DOCX/TXT/MD, and automatic retry/backoff
for failed document processing.

---

## Final Planning Gate

1. **Every acceptance criterion checked:** ✓ — see Deliverable Checklist
   above; each deliverable's own acceptance-criteria section was verified
   present and satisfied during review.
2. **All documents agree with each other:** ✓ — see Cross-Document
   Consistency Checks; the one inconsistency found (script path naming) was
   corrected during this review, not merely noted.
3. **Technology stack is consistent:** ✓ — verified across all documents
   that reference it (see above).
4. **API contract matches architecture:** ✓ — `docs/API.md` endpoints map
   1:1 to `ARCHITECTURE.md` §3's component layout.
5. **Data model matches RAG pipeline:** ✓ — DocumentChunk/Embedding fields
   in `docs/DATA_MODEL.md` match `docs/RAG_PIPELINE.md` Stage 4's metadata
   exactly.
6. **Roadmap matches requirements:** ✓ — every FR-/NFR- ID is addressed by
   at least one roadmap phase.
7. **Deployment plan satisfies zero-cost requirement:** ✓ —
   `docs/DEPLOYMENT.md`'s own acceptance check confirms no paid service is
   required; no provider in this plan requires a payment method for the
   features used.
8. **No secrets present:** ✓ — verified across every file written in this
   planning phase.
9. **No implementation feature falsely marked complete:** ✓ — `README.md`
   is an explicit placeholder skeleton with a "planning phase" banner;
   `ROADMAP.md` phases are unchecked; `docs/RAG_EVALUATION.md`/`evaluation/`
   state plainly that no run has occurred.

**Gate result: PASSED.** The planning phase is complete under the
assumption documented in Open Question 1 (no `CLAUDE.md` existed; this
report's own scope is the deliverable brief supplied for this session).
Implementation may begin at `ROADMAP.md` Phase 1, subject to the Open
Questions above being addressed as they come due (notably: choosing real
demo-KB content before Phase 4).
