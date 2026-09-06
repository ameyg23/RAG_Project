from unittest.mock import MagicMock

from retrieval.generation import set_client
from retrieval.query_rewrite import MAX_TOKENS, SYSTEM_PROMPT, TEMPERATURE, rewrite_query


def _mock_client_returning(content: str) -> MagicMock:
    client = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = content
    client.chat.completions.create.return_value = resp
    return client


def test_empty_history_skips_the_groq_call_entirely():
    # ADR-16 Option 4: a thread's first message has no referent to resolve -
    # this must be a genuine skip (no Groq call at all), not just a
    # pass-through after a wasted round-trip.
    mock_client = MagicMock()
    set_client(mock_client)

    result = rewrite_query("What is the company's vacation policy?", [])

    assert result == "What is the company's vacation policy?"
    mock_client.chat.completions.create.assert_not_called()


def test_rewrite_resolves_pronoun_against_history():
    mock_client = _mock_client_returning(
        "What is the engineering team's vacation day policy?"
    )
    set_client(mock_client)

    history = [
        {"role": "user", "content": "Tell me about the engineering team's benefits"},
        {
            "role": "assistant",
            "content": "Engineering employees get a 401(k) match [1] and full health coverage [2].",
        },
    ]

    result = rewrite_query("What about their vacation days?", history)

    assert result == "What is the engineering team's vacation day policy?"

    _, kwargs = mock_client.chat.completions.create.call_args
    messages = kwargs["messages"]
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1] == history[0]
    assert messages[2] == history[1]
    assert messages[-1] == {"role": "user", "content": "What about their vacation days?"}
    assert kwargs["temperature"] == TEMPERATURE
    assert kwargs["max_tokens"] == MAX_TOKENS


def test_rewrite_falls_back_to_raw_message_on_groq_failure():
    # A rewrite-call failure must never propagate as an error - it degrades
    # to today's (pre-ADR-16) behavior silently, per ADR-16's Failure
    # handling section.
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("simulated Groq outage")
    set_client(mock_client)

    history = [
        {"role": "user", "content": "Tell me about the engineering team's benefits"},
        {"role": "assistant", "content": "Engineering employees get a 401(k) match [1]."},
    ]

    result = rewrite_query("What about their vacation days?", history)

    assert result == "What about their vacation days?"


def test_rewrite_falls_back_when_groq_returns_empty_content():
    # generate() itself raises LLMUnavailableError on empty/malformed
    # content (retrieval/generation.py) - confirm that maps to the same
    # graceful fallback, not a propagated exception.
    mock_client = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = None
    mock_client.chat.completions.create.return_value = resp
    set_client(mock_client)

    result = rewrite_query("What about their vacation days?", [{"role": "user", "content": "hi"}])

    assert result == "What about their vacation days?"


def test_system_prompt_matches_adr16_intent():
    # Regression guard against someone gutting the prompt's key instructions
    # later, not a semantic test of model behavior.
    lower = SYSTEM_PROMPT.lower()
    assert "standalone" in lower
    assert "unchanged" in lower
