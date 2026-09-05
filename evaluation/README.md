# Evaluation

Measures RAG *quality* (retrieval hit rate, groundedness, relevance,
hallucination rate, no-context precision) — distinct from the correctness
tests in `docs/TEST_STRATEGY.md`. Full plan: `docs/RAG_EVALUATION.md`.

A working suite, run for real against the live backend and live Groq. See
`evaluation/results/20260905T201415Z.json` for the latest run and
`ROADMAP.md` Phase 18's status note for the honest caveats.

## Structure

- `dataset/demo_kb_cases.json` — 23 hand-written `EvaluationCase` records,
  each verified against the actual demo document text: 15 `answerable`, 5
  `no_context`, 3 `adversarial`.
- `scripts/run_evaluation.py` — calls the running backend's `POST /chat`
  over HTTP and computes the metrics defined in `docs/RAG_EVALUATION.md`;
  no import dependency on `backend/` application code (§13). Uses the same
  free Groq model as the backend as an LLM-as-judge for groundedness and
  relevance scoring.
- `results/` — one `EvaluationResult` JSON file per run, plus an aggregate
  summary and pass/fail vs. `docs/RAG_EVALUATION.md` §11's targets.

## Running It

Requires the backend running locally (or reachable at `--target`) and
`GROQ_API_KEY` either set in the environment or present in `backend/.env`
(the script reads it from there if not already set). Uses the same Python
environment as the backend (`backend/.venv`) — `httpx` and `groq` are
already installed there via `backend/requirements-dev.txt` /
`requirements.txt`.

```
cd evaluation/scripts
../../backend/.venv/Scripts/python.exe run_evaluation.py --target http://localhost:8000
```

Runs independently of the frontend and does not import backend application
code — it only calls the public API over HTTP.
