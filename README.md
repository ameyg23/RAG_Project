# RAG Chatbot

> **Status: implemented and tested locally, not yet deployed.** Every
> feature below is real and verified (132 backend tests, 23 frontend tests,
> a real evaluation run against live Groq — see Evaluation below). Public
> deployment (`ROADMAP.md` Phase 21) is deliberately paused pending further
> UI changes; there is no live URL yet. Nothing in this file is aspirational
> — see `ROADMAP.md` for exact per-phase status.

## Project Overview

A portfolio-grade Retrieval-Augmented Generation (RAG) chatbot: a visitor
can chat against a pre-loaded demo knowledge base with zero setup, or
upload their own documents (PDF/DOCX/TXT/MD) and chat against those
instead. Every answer is grounded in retrieved source chunks and shows
visible citations back to the originating document — the system is
designed to say "I don't have enough information" rather than fabricate an
answer when the knowledge base doesn't actually contain it.

## Problem Statement

A generic LLM chat interface can't answer questions about documents it was
never trained on, and a naive "stuff the whole document in the prompt"
approach doesn't scale past a few pages and doesn't tell you *where* an
answer came from. This project demonstrates a real, evaluable RAG pipeline
— chunking, local embeddings, vector retrieval, grounded generation, and
citation attribution — solving both problems on entirely free-tier
infrastructure.

## Features

All of the below are implemented and covered by passing tests (see
Testing), not planned:

- Demo knowledge base, ready to query with no setup
- Upload your own documents (PDF/DOCX/TXT/MD, ≤5MB each, ≤5 files per
  request)
- Chat with source-cited, grounded answers — citations show the originating
  document name and locator (page/chunk)
- A genuine "no answer" path: a question with no relevant content returns a
  fixed, honest response instead of a hallucinated one, and never calls the
  LLM for that request
- Per-session knowledge-base isolation (your uploads are never visible to
  another visitor's session)

## Architecture

See `ARCHITECTURE.md` for the full system diagram and every subsystem's
responsibilities, and `docs/ARCHITECTURE_DECISIONS.md` for the reasoning
behind each technology choice. In short: a React SPA talks only to a
FastAPI backend over a small JSON API; the backend owns every external
credential (Groq, Qdrant) and the browser never sees either. Document
ingestion (extract → clean → chunk → embed → store) and the chat path
(embed query → retrieve → ground → generate → cite) are two independent
pipelines sharing the same embedding model and vector store — see
`docs/RAG_PIPELINE.md` for the complete 14-stage breakdown.

## Tech Stack

*(Summary only — see `docs/ARCHITECTURE_DECISIONS.md` for full rationale.)*

| Layer | Choice |
|---|---|
| Frontend | React + Vite, vanilla CSS |
| Backend | FastAPI (Python) |
| Embeddings | Local `sentence-transformers/all-MiniLM-L6-v2` (384-dim, no external API) |
| Vector DB | Qdrant Cloud (free tier) |
| LLM | Groq (`qwen/qwen3.8-27b`, free tier) |
| Frontend hosting | Cloudflare Pages (planned — not yet deployed, see Deployment) |
| Backend hosting | Render, free web service (planned — not yet deployed, see Deployment) |

## Screenshots

*(Placeholder — a real local UI exists and has been manually tested, but no
screenshot could be captured this session: the Claude-in-Chrome browser
automation tool failed to connect. Run the app locally per Setup below to
see it directly, or add screenshots here once that tooling works or the app
is deployed.)*

## Demo

Not yet deployed — see the status note at the top of this file.
Deployment (`ROADMAP.md` Phase 21) is deliberately paused pending further
UI changes; there is no live URL. In the meantime, follow Setup below to
run the full app locally.

## Setup

Verified end-to-end against a true fresh-clone snapshot of this repository
(`git archive`, a clean venv, and `npm ci` — not just re-run against an
already-set-up machine).

**Prerequisites:** Python 3.13, Node 20+, free accounts at
[console.groq.com](https://console.groq.com) and
[cloud.qdrant.io](https://cloud.qdrant.io) (no credit card required for
either).

```bash
git clone <this-repo-url>
cd RAG

# Backend
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # or requirements.txt for a runtime-only install
cp ../.env.example .env   # then fill in GROQ_API_KEY, QDRANT_URL, QDRANT_API_KEY
.venv/Scripts/python -m uvicorn main:app --reload
# → verify: curl http://localhost:8000/health returns {"status": "ok", ...}

# In a second terminal: seed the demo knowledge base (one-time)
cd backend
.venv/Scripts/python scripts/seed_demo_kb.py

# Frontend (in a third terminal)
cd frontend
npm ci
cp .env.example .env   # VITE_API_BASE_URL=http://localhost:8000 is already the default
npm run dev
# → open http://localhost:5173
```

On macOS/Linux, use `.venv/bin/...` instead of `.venv/Scripts/...`.

## Environment Variables

Full list, including which are secret and which are safe to expose: see
`docs/ENVIRONMENT.md` and `.env.example` (backend) /
`frontend/.env.example`. No real credentials are ever committed to this
repository.

## RAG Explanation

See `docs/RAG_PIPELINE.md` for the complete 14-stage pipeline. Summary:

- **Ingestion:** extract text (PDF/DOCX/TXT/MD) → clean/normalize → chunk
  (800 chars, 120-char overlap) → embed locally → upsert into Qdrant,
  scoped to a `knowledge_base_id`.
- **Chat:** embed the question with the same model → similarity search
  scoped to the active knowledge base only, with a minimum-similarity
  cutoff (0.35) that short-circuits to a fixed "not enough information"
  response *without ever calling the LLM* when nothing relevant is found →
  otherwise, build a grounded prompt (retrieved chunks framed as data, not
  instructions, to mitigate prompt injection) → call Groq → resolve
  `[N]`-style citation markers in the answer back to real chunk metadata,
  never fabricating a citation that wasn't actually in context.

## Evaluation

Real numbers from an actual run against the live backend and live Groq API
(not estimated) — full methodology in `docs/RAG_EVALUATION.md`, raw output
in `evaluation/results/20260905T201415Z.json`, dataset in
`evaluation/dataset/demo_kb_cases.json` (23 hand-verified cases: 15
answerable, 5 no-context, 3 adversarial):

| Metric | Result | Target (`docs/RAG_EVALUATION.md` §11) |
|---|---|---|
| `retrieval_hit_rate` | 1.0 | ≥ 0.80 |
| `mean_groundedness_score` | 1.0 | ≥ 0.70 |
| `mean_relevance_score` | 1.0 | — |
| `no_context_precision` | 1.0 | ≥ 0.90 |
| `hallucination_rate` | 0.0 | ≤ 0.10 |

**Two honest caveats**, also recorded in the results file: (1)
`retrieval_hit_rate` and `source_accuracy_rate` collapse to the same signal
here, since the evaluation script is intentionally HTTP-only (no
backend-internals import) and can't see chunks that were retrieved
internally but not ultimately cited; (2) 23 cases against 4 short demo
documents is a small, narrow benchmark — a perfect score demonstrates the
grounding strategy works *on this dataset*, not general-purpose robustness
at arbitrary scale.

## Testing

Full strategy across four levels (unit, API/integration, RAG-specific,
end-to-end) in `docs/TEST_STRATEGY.md`. Current real state: **132 backend
tests** (pytest, `ruff check` clean) and **23 frontend tests** (Vitest,
`oxlint` clean apart from 4 pre-existing non-blocking warnings), wired into
GitHub Actions CI (`.github/workflows/ci.yml`) on every push/PR — CI
excludes tests that call the real Groq API (tagged `@pytest.mark.live_groq`)
so it never depends on live LLM quota, and needs no cloud credentials
(Qdrant falls back to an in-memory instance when unconfigured). The
separate RAG *quality* evaluation suite (above) is deliberately never a CI
gate, since it depends on live LLM calls.

## Deployment

Full zero-cost plan (Cloudflare Pages + Render + Qdrant Cloud + Groq, all
free tiers, no card required anywhere) in `docs/DEPLOYMENT.md`. **Current
status: not yet deployed** — deliberately paused (see the status note at
the top of this file) until planned UI changes land; a `render.yaml`
Blueprint is already prepared at the repo root so the Render side deploys
in one step once that's ready to proceed.

## Limitations

Known V1 constraints, stated honestly rather than glossed over:

- **No user accounts** — sessions are anonymous and ephemeral; there is no
  login and no cross-session chat history (by design, see
  `docs/REQUIREMENTS.md` §12).
- **Uploaded documents are not durably retained** — a knowledge base is
  scoped to its session; nothing is represented to users as permanently
  stored.
- **Render free-tier cold starts** (once deployed): the backend sleeps
  after 15 minutes of inactivity; the next request pays a 30–60 second
  cold-start penalty. The UI is designed around this, but it hasn't been
  observed against a real deployed instance yet.
- **Qdrant free-cluster inactivity suspension**: a free cluster suspends
  after 7 days and is deleted after 28 days of inactivity. Recovery is a
  one-command reseed (`backend/scripts/seed_demo_kb.py`), deliberately not
  an automated keep-alive (see `docs/DEPLOYMENT.md`).
- **No rate limiting** — an accepted V1 risk (`docs/SECURITY.md`
  "Excessive Requests"); quota exhaustion degrades gracefully to a `502`
  rather than crashing, but isn't prevented.
- **16 known, unresolved dependency vulnerabilities** (down from 74) in
  `langchain`, `langchain-text-splitters`, `langchain-core`, `starlette`,
  and `transformers` — each requires a major/breaking version bump that
  was judged too risky to attempt without a dedicated regression budget;
  tracked explicitly rather than silently ignored (`ROADMAP.md` Phase 20).
- **No process-level sandboxing** around PDF/DOCX parsing of untrusted
  uploads — an accepted V1 risk, see `docs/SECURITY.md`.

## Future Improvements

Candidate future work is tracked per-decision in
`docs/ARCHITECTURE_DECISIONS.md` (each ADR's "Future migration" section)
and per-threat in `docs/SECURITY.md` ("Future improvement"). Notable ones:
rate limiting if abuse is observed in practice; automated dependency-update
PRs; resolving the remaining major-version dependency upgrades under a
proper regression-test budget; a Content-Security-Policy header on the
deployed frontend.
