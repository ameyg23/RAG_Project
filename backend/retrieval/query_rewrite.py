"""Stage 6.5 of docs/RAG_PIPELINE.md: query rewriting (ADR-16).

Resolves a follow-up chat message (e.g. "what about their vacation days?")
into a standalone, retrieval-ready query using the same Groq client/model
generation.py already uses (a second call, different prompt) — see ADR-16
for why this reuses Groq rather than adding a second LLM provider.

Where the output is used (deviates from a retrieval-only default — see
ADR-16 "Where the rewritten query is used"): the rewritten query returned
here is used for **both** Stage 7's query embedding **and** Stage 11's
`QUESTION:` field in the generation prompt — the referent-ambiguity problem
this stage exists to fix applies equally to the LLM's own answer-generation
call, not just to retrieval.

Failure handling: a Groq failure here must never turn into the request's
502 LLM_UNAVAILABLE contract (that belongs to Stage 12's generation call,
per docs/API.md) — this stage is an internal retrieval-quality enhancement,
so any failure (timeout, rate limit, malformed response) falls back to
returning the raw `message` unchanged, exactly as if this stage didn't
exist for this one request.
"""

from retrieval.generation import LLMUnavailableError, generate

# Low temperature, short output: the desired result is one rewritten
# question, not an essay — matches docs/RAG_PIPELINE.md Stage 6.5's
# configuration exactly.
TEMPERATURE = 0.0
MAX_TOKENS = 100

# Verbatim from ADR-16's "Rewriting call / prompt approach".
SYSTEM_PROMPT = (
    "Given this conversation and a follow-up question, rewrite the follow-up "
    "as a fully standalone question that can be understood without the history. "
    "Preserve the user's original intent and phrasing style. If the follow-up is "
    "already standalone, return it unchanged. Respond with only the rewritten "
    "question, no explanation."
)


def rewrite_query(message: str, conversation_history: list[dict[str, str]]) -> str:
    """Stage 6.5: rewrite `message` into a standalone query given prior turns.

    `conversation_history` is a list of `{"role": "user"|"assistant",
    "content": str}` dicts (already validated/capped by
    models.schemas.ChatRequest before reaching here — this function does not
    re-validate length/count).

    Skipped entirely (no Groq call at all) when `conversation_history` is
    empty — a thread's first message has no referent to resolve, and this
    also saves a Groq call on the highest-traffic case (suggested-question
    buttons, ADR-16).
    """
    if not conversation_history:
        return message

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(
        {"role": turn["role"], "content": turn["content"]} for turn in conversation_history
    )
    messages.append({"role": "user", "content": message})

    try:
        rewritten = generate(messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS)
    except LLMUnavailableError:
        return message

    return rewritten or message
