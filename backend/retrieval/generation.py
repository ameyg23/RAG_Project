"""Stage 12 of docs/RAG_PIPELINE.md: the raw Groq chat-completion call.

Scope boundary: system-prompt construction and the no-context short-circuit
are Phase 11's job (Stage 11) - this module is just the Groq call wrapper,
mapping every possible failure to a single retriable error (FR-054).
"""

from groq import Groq

from config import settings

TEMPERATURE = 0.1

_client: Groq | None = None


class LLMUnavailableError(Exception):
    """Raised for any Groq/network failure or malformed response. The
    message may carry real diagnostic detail internally - a later phase's
    API layer decides what's safe to show the client (sanitized
    502 LLM_UNAVAILABLE, docs/API.md / docs/SECURITY.md)."""


def get_client() -> Groq:
    """Lazily create and cache the Groq client, once per process."""
    global _client
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def set_client(client: Groq) -> None:
    """Test-only override."""
    global _client
    _client = client


def generate(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = TEMPERATURE,
    max_tokens: int = 500,
) -> str:
    try:
        response = get_client().chat.completions.create(
            model=model or settings.LLM_MODEL_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        raise LLMUnavailableError(f"Groq request failed: {type(exc).__name__}: {exc}") from exc

    content = response.choices[0].message.content
    if not content:
        raise LLMUnavailableError("Groq returned an empty/malformed response")

    return content.strip()
