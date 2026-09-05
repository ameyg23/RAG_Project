# RAG Evaluation Plan

Distinct from `docs/TEST_STRATEGY.md`: this document measures **quality**
(is the RAG pipeline actually good?), not correctness (does the code do what
it's supposed to?). No evaluation has been run yet — this document defines
the plan only. Every metric/threshold below is a **target**, not a result.

## 1. What Is Being Evaluated

The end-to-end RAG pipeline's retrieval and generation quality, as observed
through the public `/chat` API — primarily against the **demo knowledge
base**, since it is the only knowledge base guaranteed to exist with fixed,
reproducible content (a user-uploaded KB is arbitrary and can't anchor a
repeatable evaluation dataset).

## 2. Why It Is Being Evaluated

`docs/REQUIREMENTS.md` NFR-007 requires a measurable groundedness/relevance
threshold. Without this, "the RAG works" is an unverified claim. Evaluation
turns the three-layer grounding strategy defined in `docs/RAG_PIPELINE.md`
(retrieval gate, prompt instruction, citation fallback) from a design intent
into something with a measured pass rate.

## 3. Evaluation Dataset Structure

A set of `EvaluationCase` records (schema: `docs/DATA_MODEL.md` §8) stored as
JSON files under `evaluation/dataset/`, one file per case or a small number
of grouped files. Each case specifies `question`, `expected_answer_summary`
(a human-written gist, not an exact-match string), `expected_source_documents`,
and a `category`:

- `answerable` — a question the demo KB's content genuinely answers.
- `no_context` — a question genuinely unrelated to the demo KB's content.
- `adversarial` — a question where retrieved context will be topically
  close but insufficient to actually answer it (tests hallucination
  resistance specifically).

**Dependency:** real cases can only be written once the demo knowledge
base's actual content is finalized (the questions must be grounded in real
documents, not invented). This document defines the *structure*; populating
`evaluation/dataset/` with real cases is a later implementation task (see
`ROADMAP.md` phase 18).

## 4. Retrieval Evaluation

For `category=answerable` cases: check whether at least one document in
`expected_source_documents` appears among the top-K chunks retrieved
internally for that question.

**Metric:** `retrieval_hit_rate` = % of answerable cases where
`retrieval_hit = true`.

## 5. Source Evaluation

For cases where retrieval hit: check whether the `sources[]` array in the
**actual `/chat` API response** correctly names the expected document —
i.e. the citation survived end-to-end through Stage 14 (`docs/RAG_PIPELINE.md`)
and reached the client, not just that retrieval found it internally.

**Metric:** `source_accuracy_rate` = % of retrieval-hit cases where the
correct document is actually cited in the response.

## 6. Groundedness Evaluation

For `answerable` cases: score whether every claim in `actual_answer` is
supported by the cited source snippets.

**Method (V1):** LLM-as-judge — a second, separate prompt sent to the same
free Groq model, given the question, the answer, and the cited source
snippets, asking it to rate 0–1 how well the answer is supported by the
sources. There is no budget in V1 for human annotation at scale.

**Known limitation, stated explicitly:** the judge model can itself be
wrong — a groundedness score in V1 is a useful signal, not ground truth.
This limitation is documented here rather than glossed over.

**Metric:** `mean_groundedness_score` across answerable cases.

## 7. Answer Relevance Evaluation

For `answerable` cases: does `actual_answer` actually address the question
asked (on-topic), independent of whether it's grounded? Same LLM-as-judge
method as §6, separate prompt/score, same stated limitation.

**Metric:** `mean_relevance_score` across answerable cases.

## 8. Hallucination Evaluation

For `category=adversarial` cases specifically: check that the answer does
**not** confidently fabricate a response. Passing means either:
(a) the no-context path was triggered, or
(b) an answer was given, but its groundedness score (§6) remains high — i.e.
no unsupported claim slipped through despite the context being only
topically adjacent.

**Metric:** `hallucination_rate` = % of adversarial cases where neither (a)
nor (b) holds (i.e. a confident, ungrounded answer was produced).

## 9. No-Context Evaluation

For `category=no_context` cases: assert the response is **exactly** the
fixed "not enough information in this knowledge base" text with an empty
`sources[]` array, and — as in `docs/TEST_STRATEGY.md`'s equivalent
structural test — that the LLM was never called for that request (verified
via a mocked-client assertion when this suite is run against a test
deployment, or via response-latency/logging signal when run against a live
deployment where mocking isn't possible).

**Metric:** `no_context_precision` = % of no_context cases correctly
refused.

## 10. Metrics Summary

| Metric | Definition |
|---|---|
| `retrieval_hit_rate` | % of `answerable` cases whose expected source appears in top-K |
| `source_accuracy_rate` | % of retrieval-hit cases where the response correctly cites the expected document |
| `mean_groundedness_score` | Average LLM-judge groundedness score (0–1) over `answerable` cases |
| `mean_relevance_score` | Average LLM-judge relevance score (0–1) over `answerable` cases |
| `no_context_precision` | % of `no_context` cases correctly refused with the fixed response |
| `hallucination_rate` | % of `adversarial` cases producing a confident, ungrounded answer |

## 11. Pass/Fail Criteria (Initial Targets — Not Yet Measured)

| Metric | Initial target |
|---|---|
| `retrieval_hit_rate` | ≥ 0.80 |
| `mean_groundedness_score` | ≥ 0.70 |
| `no_context_precision` | ≥ 0.90 |
| `hallucination_rate` | ≤ 0.10 |

These are honest starting targets to be revisited once the first real
evaluation run produces baseline numbers — **no run has occurred yet, and no
claim is made that these thresholds are currently met.**

## 12. How Results Are Generated

A script, `evaluation/scripts/run_evaluation.py` (not yet implemented — see
`ROADMAP.md` phase 18), will:

1. Read all `EvaluationCase` records from `evaluation/dataset/`.
2. For each case, call the real, running backend's `POST /chat` endpoint
   over HTTP (black-box — never imports backend internals).
3. Compute the metrics in §10 (including the LLM-as-judge calls for §6–7).
4. Write one `EvaluationResult` record per case (schema: `docs/DATA_MODEL.md`
   §9) plus an aggregate summary to `evaluation/results/<run_id>.json`.
5. Print a human-readable pass/fail summary against §11's targets.

## 13. Where Evaluation Code Lives

Entirely under `evaluation/` (`dataset/`, `scripts/`, `results/`), with
**no import dependency on `backend/` application code** — it only ever
calls the deployed or locally-running API over HTTP. This is what makes
evaluation runnable independently of the frontend and independently of
backend internals, satisfying the acceptance criterion below.

## Proposed Structure

```
evaluation/
├── dataset/     # EvaluationCase JSON files (populated once demo KB content is final)
├── scripts/     # run_evaluation.py and any judge-prompt templates
├── results/     # generated EvaluationResult JSON per run (not committed content at planning time)
└── README.md    # how to run the suite
```

## Acceptance Criteria Check

- **Evaluation has a clear purpose:** §1–2.
- **Metrics are defined:** §10.
- **Test data is defined:** §3 defines the structure; real content is an
  implementation-phase task, not fabricated here.
- **No fabricated metrics are planned:** §11 explicitly states these are
  targets, not results — no evaluation has been run.
- **Evaluation can be run independently of the frontend:** §13 — HTTP-only,
  no frontend or backend-internal dependency.
