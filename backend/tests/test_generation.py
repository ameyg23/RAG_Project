from unittest.mock import MagicMock

import groq
import httpx
import pytest

from config import settings
from retrieval.generation import TEMPERATURE, LLMUnavailableError, generate, set_client


def _mock_client_raising(exc):
    client = MagicMock()
    client.chat.completions.create.side_effect = exc
    return client


def test_timeout_maps_to_llm_unavailable():
    req = httpx.Request("POST", "https://api.groq.com/x")
    set_client(_mock_client_raising(groq.APITimeoutError(request=req)))
    with pytest.raises(LLMUnavailableError):
        generate([{"role": "user", "content": "hi"}])


def test_connection_error_maps_to_llm_unavailable():
    req = httpx.Request("POST", "https://api.groq.com/x")
    set_client(_mock_client_raising(groq.APIConnectionError(request=req)))
    with pytest.raises(LLMUnavailableError):
        generate([{"role": "user", "content": "hi"}])


def test_rate_limit_maps_to_llm_unavailable():
    req = httpx.Request("POST", "https://api.groq.com/x")
    resp = httpx.Response(429, request=req)
    set_client(
        _mock_client_raising(groq.RateLimitError("rate limited", response=resp, body=None))
    )
    with pytest.raises(LLMUnavailableError):
        generate([{"role": "user", "content": "hi"}])


def test_empty_response_maps_to_llm_unavailable():
    client = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = None
    client.chat.completions.create.return_value = resp
    set_client(client)
    with pytest.raises(LLMUnavailableError):
        generate([{"role": "user", "content": "hi"}])


def test_defaults_and_overrides_passed_through():
    client = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = "answer"
    client.chat.completions.create.return_value = resp
    set_client(client)

    generate([{"role": "user", "content": "hi"}])
    _, kwargs = client.chat.completions.create.call_args
    assert kwargs["model"] == settings.LLM_MODEL_NAME
    assert kwargs["temperature"] == TEMPERATURE

    generate([{"role": "user", "content": "hi"}], model="other-model", temperature=0.7)
    _, kwargs = client.chat.completions.create.call_args
    assert kwargs["model"] == "other-model"
    assert kwargs["temperature"] == 0.7


def test_real_live_call_against_groq():
    # Phase 10's actual Definition of Done: a real prompt built from real
    # demo content produces a real Groq answer. No mocking - this is the
    # only test in this file that touches the network.
    import retrieval.generation as generation_module

    generation_module._client = None  # force get_client() to build a fresh real client

    context = (
        "[1] Full-time employees accrue 15 days of paid time off (PTO) per "
        "calendar year, credited at a rate of 1.25 days per completed month "
        "of employment."
    )
    messages = [
        {
            "role": "system",
            "content": "Answer only from the provided context. Cite using [N] markers.",
        },
        {
            "role": "user",
            "content": (
                f"Context:\n{context}\n\nQuestion: How many vacation days do I get per year?"
            ),
        },
    ]

    answer = generate(messages)
    assert answer
    assert "15" in answer
