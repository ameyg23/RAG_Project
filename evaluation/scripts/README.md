# Evaluation Scripts

`run_evaluation.py` will live here (implementation task, see `ROADMAP.md`
phase 18 — not written yet, this is still the planning phase).

It will read `evaluation/dataset/*.json`, call the running backend's
`POST /chat` endpoint over HTTP, score each case per `docs/RAG_EVALUATION.md`
(including LLM-as-judge calls for groundedness/relevance), and write results
to `evaluation/results/<run_id>.json`.
