"""Runs the RAG quality evaluation suite defined in docs/RAG_EVALUATION.md.

HTTP-only against a real, running backend (docs/RAG_EVALUATION.md §13) - this
file has no import dependency on backend/ application code. NO_CONTEXT_RESPONSE
and the judge LLM model name are therefore duplicated here rather than
imported; keep them in sync with backend/retrieval/generation.py and
backend/config.py if either changes.

Usage:
    python run_evaluation.py [--target http://localhost:8000]

Requires GROQ_API_KEY (read from backend/.env if not already set in the
environment) to run the LLM-as-judge groundedness/relevance calls.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from groq import Groq, RateLimitError

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "evaluation" / "dataset"
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"
BACKEND_ENV_PATH = REPO_ROOT / "backend" / ".env"

# Must match backend/retrieval/generation.py's NO_CONTEXT_RESPONSE exactly.
NO_CONTEXT_RESPONSE = (
    "I don't have enough information in this knowledge base to answer that question."
)

# Must match backend/config.py's LLM_MODEL_NAME default (ADR-08) - the same
# free Groq model is reused as the judge, per docs/RAG_EVALUATION.md §6.
JUDGE_MODEL = "qwen/qwen3.8-27b"

GROUNDEDNESS_THRESHOLD = 0.70  # docs/RAG_EVALUATION.md §11, also used per-case here
RELEVANCE_PASS_THRESHOLD = 0.70  # not a top-level metric threshold in §11, kept consistent

PASS_TARGETS = {
    "retrieval_hit_rate": 0.80,
    "mean_groundedness_score": 0.70,
    "no_context_precision": 0.90,
    "hallucination_rate": ("<=", 0.10),
}


def load_dataset() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(DATASET_DIR.glob("*.json")):
        cases.extend(json.loads(path.read_text(encoding="utf-8")))
    return cases


def load_groq_api_key() -> str:
    import os

    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"]
    if BACKEND_ENV_PATH.exists():
        for line in BACKEND_ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GROQ_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit(
        "GROQ_API_KEY not set in the environment and not found in backend/.env - "
        "the LLM-as-judge steps cannot run without it."
    )


def call_chat(client: httpx.Client, knowledge_base_id: str, message: str) -> tuple[dict, float]:
    start = time.perf_counter()
    response = client.post(
        "/chat",
        json={"knowledge_base_id": knowledge_base_id, "message": message},
    )
    elapsed = time.perf_counter() - start
    response.raise_for_status()
    return response.json(), elapsed


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _judge(groq_client: Groq, prompt: str) -> tuple[float, str]:
    """Calls the judge model, returns (score, reasoning). Falls back to a
    score of 0.0 with the raw text as reasoning if the model didn't return
    parseable JSON - never silently invents a score."""
    # Groq's free-tier OTPM (output tokens/minute) limit is easily hit when
    # running ~20+ judge calls back to back - retry with backoff rather than
    # failing the whole run over a transient per-minute quota window.
    for attempt in range(5):
        try:
            completion = groq_client.chat.completions.create(
                model=JUDGE_MODEL,
                # "/no_think" is a Qwen3 control token that disables its
                # extended reasoning trace - without it, the OTPM limit is
                # exhausted by hidden reasoning tokens alone.
                messages=[{"role": "user", "content": prompt + "\n/no_think"}],
                temperature=0,
                max_tokens=200,
            )
            break
        except RateLimitError:
            if attempt == 4:
                raise
            time.sleep(15)
    raw = completion.choices[0].message.content or ""
    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        return 0.0, f"UNPARSEABLE_JUDGE_OUTPUT: {raw[:300]}"
    try:
        parsed = json.loads(match.group(0))
        score = float(parsed["score"])
        score = max(0.0, min(1.0, score))
        return score, str(parsed.get("reasoning", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 0.0, f"UNPARSEABLE_JUDGE_OUTPUT: {raw[:300]}"


def judge_groundedness(
    groq_client: Groq, question: str, answer: str, sources: list[dict]
) -> tuple[float, str]:
    snippets = "\n\n".join(
        f"[{s['document_name']}] {s['snippet']}" for s in sources
    ) or "(no sources were cited)"
    prompt = f"""You are grading whether an AI assistant's answer is fully supported by \
the source excerpts it cited. Do not use outside knowledge - grade grounding \
against these excerpts only.

QUESTION: {question}

CITED SOURCE EXCERPTS:
{snippets}

ANSWER TO GRADE: {answer}

Rate 0.0-1.0 how well every claim in the answer is supported by the cited \
excerpts (1.0 = fully supported, 0.0 = entirely unsupported/fabricated). \
Respond with ONLY a JSON object: {{"score": <number>, "reasoning": "<one sentence>"}}"""
    return _judge(groq_client, prompt)


def judge_relevance(groq_client: Groq, question: str, answer: str) -> tuple[float, str]:
    prompt = f"""You are grading whether an AI assistant's answer is on-topic for the \
question asked, independent of whether the answer is factually correct.

QUESTION: {question}

ANSWER TO GRADE: {answer}

Rate 0.0-1.0 how directly the answer addresses the question asked (1.0 = \
fully on-topic and responsive, 0.0 = does not address the question at all). \
Respond with ONLY a JSON object: {{"score": <number>, "reasoning": "<one sentence>"}}"""
    return _judge(groq_client, prompt)


def evaluate_case(client: httpx.Client, groq_client: Groq, case: dict) -> dict:
    response, elapsed = call_chat(client, case["knowledge_base_id"], case["question"])
    actual_answer = response["answer"]
    actual_sources = response["sources"]
    actual_source_names = []
    for s in actual_sources:
        if s["document_name"] not in actual_source_names:
            actual_source_names.append(s["document_name"])

    is_no_context_response = (
        actual_answer == NO_CONTEXT_RESPONSE and len(actual_sources) == 0
    )

    # docs/RAG_EVALUATION.md §4-5: an HTTP-only script cannot see chunks
    # retrieved internally, only what the final response actually cites -
    # retrieval_hit and source_accuracy are therefore computed from the same
    # signal (the response's sources[]) and will be numerically identical in
    # this implementation. Documented simplification, not a spec deviation
    # made silently.
    expected_docs = set(case["expected_source_documents"])
    retrieval_hit = bool(expected_docs & set(actual_source_names))
    source_accuracy = retrieval_hit  # degenerate given the above

    groundedness_score: float | None = None
    relevance_score: float | None = None
    groundedness_reasoning = ""
    relevance_reasoning = ""

    if case["category"] in ("answerable", "adversarial") and not is_no_context_response:
        groundedness_score, groundedness_reasoning = judge_groundedness(
            groq_client, case["question"], actual_answer, actual_sources
        )
        relevance_score, relevance_reasoning = judge_relevance(
            groq_client, case["question"], actual_answer
        )
    elif case["category"] in ("answerable", "adversarial") and is_no_context_response:
        # Declining is the maximally-grounded outcome when no answer is
        # given at all - there is no ungrounded claim to score against.
        groundedness_score, relevance_score = 1.0, 0.0
        groundedness_reasoning = "No answer was given (no-context short-circuit)."
        relevance_reasoning = "No answer was given, so it cannot address the question."

    if case["category"] == "answerable":
        passed = bool(
            retrieval_hit
            and groundedness_score is not None
            and groundedness_score >= GROUNDEDNESS_THRESHOLD
            and relevance_score is not None
            and relevance_score >= RELEVANCE_PASS_THRESHOLD
        )
    elif case["category"] == "no_context":
        passed = is_no_context_response
    else:  # adversarial
        confidently_ungrounded = (
            not is_no_context_response
            and groundedness_score is not None
            and groundedness_score < GROUNDEDNESS_THRESHOLD
        )
        passed = not confidently_ungrounded

    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "question": case["question"],
        "actual_answer": actual_answer,
        "actual_sources": actual_source_names,
        "retrieval_hit": retrieval_hit,
        "source_accuracy": source_accuracy,
        "is_no_context_response": is_no_context_response,
        "response_latency_seconds": round(elapsed, 3),
        "groundedness_score": groundedness_score,
        "groundedness_reasoning": groundedness_reasoning,
        "relevance_score": relevance_score,
        "relevance_reasoning": relevance_reasoning,
        "passed": passed,
    }


def compute_summary(results: list[dict]) -> dict:
    answerable = [r for r in results if r["category"] == "answerable"]
    no_context = [r for r in results if r["category"] == "no_context"]
    adversarial = [r for r in results if r["category"] == "adversarial"]

    def rate(items: list[dict], key: str) -> float | None:
        return sum(1 for r in items if r[key]) / len(items) if items else None

    def mean(items: list[dict], key: str) -> float | None:
        scored = [r[key] for r in items if r[key] is not None]
        return sum(scored) / len(scored) if scored else None

    retrieval_hit_rate = rate(answerable, "retrieval_hit")
    mean_groundedness_score = mean(answerable, "groundedness_score")
    mean_relevance_score = mean(answerable, "relevance_score")
    no_context_precision = rate(no_context, "is_no_context_response")
    hallucination_rate = (
        1 - rate(adversarial, "passed") if adversarial and rate(adversarial, "passed") is not None
        else None
    )

    def target_met(value: float | None, target) -> bool | None:
        if value is None:
            return None
        if isinstance(target, tuple):
            op, threshold = target
            return value <= threshold if op == "<=" else value >= threshold
        return value >= target

    return {
        "case_counts": {
            "total": len(results),
            "answerable": len(answerable),
            "no_context": len(no_context),
            "adversarial": len(adversarial),
        },
        "metrics": {
            "retrieval_hit_rate": retrieval_hit_rate,
            "mean_groundedness_score": mean_groundedness_score,
            "mean_relevance_score": mean_relevance_score,
            "no_context_precision": no_context_precision,
            "hallucination_rate": hallucination_rate,
        },
        "pass_fail_vs_targets": {
            "retrieval_hit_rate": target_met(retrieval_hit_rate, PASS_TARGETS["retrieval_hit_rate"]),
            "mean_groundedness_score": target_met(
                mean_groundedness_score, PASS_TARGETS["mean_groundedness_score"]
            ),
            "no_context_precision": target_met(
                no_context_precision, PASS_TARGETS["no_context_precision"]
            ),
            "hallucination_rate": target_met(hallucination_rate, PASS_TARGETS["hallucination_rate"]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="http://localhost:8000")
    args = parser.parse_args()

    cases = load_dataset()
    if not cases:
        raise SystemExit(f"No evaluation cases found under {DATASET_DIR}")

    groq_client = Groq(api_key=load_groq_api_key())
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    results = []
    with httpx.Client(base_url=args.target, timeout=60.0) as client:
        for i, case in enumerate(cases, start=1):
            print(f"[{i}/{len(cases)}] {case['case_id']} ({case['category']}) ...", file=sys.stderr)
            results.append(evaluate_case(client, groq_client, case))

    summary = compute_summary(results)
    output = {
        "run_id": run_id,
        "target": args.target,
        "judge_model": JUDGE_MODEL,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "results": results,
        "known_limitations": [
            "retrieval_hit_rate and source_accuracy_rate are computed from the same "
            "signal (the /chat response's sources[]) since this script is HTTP-only "
            "and has no visibility into internally-retrieved top-K chunks that were "
            "not ultimately cited (docs/RAG_EVALUATION.md §13). They are therefore "
            "numerically identical in this run, not independently measured.",
            "groundedness_score and relevance_score are LLM-as-judge outputs from the "
            "same free Groq model under evaluation - a useful signal, not ground "
            "truth (docs/RAG_EVALUATION.md §6).",
        ],
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{run_id}.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"\nWrote {out_path}")
    print(f"\nCase counts: {summary['case_counts']}")
    print("\nMetrics:")
    for k, v in summary["metrics"].items():
        print(f"  {k}: {v}")
    print("\nPass/fail vs docs/RAG_EVALUATION.md §11 targets:")
    for k, v in summary["pass_fail_vs_targets"].items():
        print(f"  {k}: {'PASS' if v else 'FAIL' if v is False else 'N/A'}")


if __name__ == "__main__":
    main()
