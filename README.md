# RAG Chatbot

> **Status: Planning phase.** No application code exists yet. This README is
> a skeleton — every section below is a placeholder to be filled in as the
> phases in `ROADMAP.md` complete. Nothing in this file should be read as a
> claim that a feature is built or working. See `docs/PLANNING_REVIEW.md`
> for the current state of the planning phase.

## Project Overview

*(Placeholder — fill in once Phase 23 completes.)* A short, plain-language
description of what this project is and why it exists.

## Problem Statement

*(Placeholder.)* What problem this project demonstrates a solution to.

## Features

*(Placeholder — do not list a feature here until it is actually implemented
and verified, per the Documentation Agent's responsibilities in
`.claude/agents/documentation.md`.)*

Planned V1 scope (see `docs/REQUIREMENTS.md` and `docs/PLANNING_REVIEW.md`
→ "Recommended V1" for the authoritative list):
- Demo knowledge base, ready to query with no setup
- Upload your own documents (PDF/DOCX/TXT/MD, ≤5MB each, ≤5 files)
- Chat with source-cited, grounded answers
- Per-session knowledge-base isolation

## Architecture

*(Placeholder.)* See `ARCHITECTURE.md` for the full system architecture with
diagrams, and `docs/ARCHITECTURE_DECISIONS.md` for the reasoning behind
every technology choice.

## Tech Stack

*(Summary only — see `docs/ARCHITECTURE_DECISIONS.md` for full rationale.)*

| Layer | Choice |
|---|---|
| Frontend | React + Vite, vanilla CSS |
| Backend | FastAPI (Python) |
| Embeddings | Local `sentence-transformers/all-MiniLM-L6-v2` |
| Vector DB | Qdrant Cloud (free tier) |
| LLM | Groq (`llama-3.3-70b-versatile`, free tier) |
| Frontend hosting | Cloudflare Pages |
| Backend hosting | Render (free web service) |

## Screenshots

*(Placeholder — add once a real UI exists, Phase 16 onward.)*

## Demo

*(Placeholder — add the live URL once deployed, Phase 21/22. No link exists
yet.)*

## Setup

*(Placeholder — verified, step-by-step local setup instructions will be
added once Phase 1 (Repository Setup) completes. Will include: prerequisites,
clone, install, environment variables, run frontend, run backend.)*

## Environment Variables

*(Placeholder.)* See `docs/ENVIRONMENT.md` for the full, authoritative list
and `.env.example` for a template. No real credentials are ever committed.

## RAG Explanation

*(Placeholder.)* See `docs/RAG_PIPELINE.md` for the complete stage-by-stage
pipeline (extraction → chunking → embedding → retrieval → grounded
generation → citation).

## Evaluation

*(Placeholder — real numbers only, added once Phase 18 produces an actual
evaluation run.)* See `docs/RAG_EVALUATION.md` for methodology and
`evaluation/results/` for raw output once it exists. No metric is ever
estimated or fabricated here.

## Testing

*(Placeholder.)* See `docs/TEST_STRATEGY.md` for the full test strategy
across unit, API/integration, RAG, and end-to-end levels.

## Deployment

*(Placeholder.)* See `docs/DEPLOYMENT.md` for the zero-cost deployment plan
and exact provider setup steps.

## Limitations

*(Placeholder — will be filled in honestly once the system is built,
including known V1 constraints such as: Render free-tier cold starts,
Qdrant free-cluster inactivity suspension, no user accounts, no
cross-session chat history, no automatic retry for failed document
processing. See `docs/REQUIREMENTS.md` §12 for the full exclusions list.)*

## Future Improvements

*(Placeholder.)* Candidate future work is tracked per-ADR in
`docs/ARCHITECTURE_DECISIONS.md` under each decision's "Future migration"
section, and per-threat in `docs/SECURITY.md` under "Future improvement".
