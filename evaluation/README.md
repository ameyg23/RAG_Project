# Evaluation

Measures RAG *quality* (retrieval hit rate, groundedness, relevance,
hallucination rate, no-context precision) — distinct from the correctness
tests in `docs/TEST_STRATEGY.md`. Full plan: `docs/RAG_EVALUATION.md`.

No evaluation has been run yet; this directory is currently a planning-phase
scaffold, not a working suite.

## Structure

- `dataset/` — hand-written `EvaluationCase` records (JSON), covering
  `answerable`, `no_context`, and `adversarial` categories. Populated once
  the demo knowledge base's content is finalized.
- `scripts/` — `run_evaluation.py` (not yet implemented) calls a running
  backend's `POST /chat` over HTTP and computes the metrics defined in
  `docs/RAG_EVALUATION.md`.
- `results/` — generated `EvaluationResult` JSON per run, plus a
  human-readable summary. Not committed content at planning time.

## Running It (once implemented)

```
python scripts/run_evaluation.py --target http://localhost:8000
```

Runs independently of the frontend and does not import backend application
code — it only calls the public API over HTTP.
