from pathlib import Path
from unittest.mock import MagicMock

import pytest
from qdrant_client import QdrantClient

from ingestion.chunk import chunk_document
from ingestion.embed import embed_query, embed_texts
from ingestion.extract import extract_and_clean
from retrieval import reranker, vector_store
from retrieval.retriever import (
    MIN_RERANK_SCORE,
    RetrievedChunk,
    apply_rerank_threshold,
    retrieve,
)

DEMO_CONTENT = Path(__file__).parent.parent / "demo_content"
FIXTURES = Path(__file__).parent / "fixtures"
DEMO_FILES = [
    "01_employee_handbook.md",
    "02_product_faq.md",
    "03_onboarding_guide.md",
    "04_security_policy.md",
]


@pytest.fixture(autouse=True)
def fresh_in_memory_client():
    vector_store.set_client(QdrantClient(":memory:"))
    yield


@pytest.fixture(autouse=True)
def restore_real_model():
    # Every test either explicitly injects a mock model or relies on the
    # real one - either way, never let one test's set_model() leak into the
    # next (module-level singleton, same reasoning as generation.set_client()
    # test isolation elsewhere in this suite).
    yield
    reranker.set_model(None)


def _make_chunk(chunk_id: str, text: str, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        score=score,
        chunk_id=chunk_id,
        document_id="doc",
        knowledge_base_id="kb_demo",
        document_name="doc.md",
        chunk_index=0,
        page=None,
        text=text,
    )


def _ingest_all_demo_content():
    for i, filename in enumerate(DEMO_FILES):
        units = extract_and_clean(str(DEMO_CONTENT / filename), "md")
        chunks = chunk_document(
            units, document_id=f"doc-{i}", knowledge_base_id="kb_demo", document_name=filename
        )
        vectors = embed_texts([c.text for c in chunks])
        vector_store.upsert_chunks(chunks, vectors)


def test_rerank_empty_candidates_never_loads_the_model():
    # Loading CrossEncoder is a real (slow, first-download) cost - an empty
    # candidate list must short-circuit before touching get_model() at all,
    # not just return an empty list after loading it for nothing.
    original_get_model = reranker.get_model

    def _fail_if_called():
        raise AssertionError("get_model() should not be called for an empty candidate list")

    reranker.get_model = _fail_if_called  # type: ignore[assignment]
    try:
        assert reranker.rerank("anything", []) == []
    finally:
        reranker.get_model = original_get_model  # restore the real module-level function


def test_rerank_reorders_by_new_score_and_discards_cosine_order():
    c1 = _make_chunk("c1", "low relevance text", score=0.9)
    c2 = _make_chunk("c2", "high relevance text", score=0.5)
    c3 = _make_chunk("c3", "medium relevance text", score=0.7)

    mock_model = MagicMock()
    # Cross-encoder scores intentionally invert the input (cosine-based) order.
    mock_model.predict.return_value = [0.1, 0.9, 0.5]
    reranker.set_model(mock_model)

    result = reranker.rerank("a question", [c1, c2, c3])

    assert [c.chunk_id for c in result] == ["c2", "c3", "c1"]
    assert [c.score for c in result] == [0.9, 0.5, 0.1]

    (call_args,), _ = mock_model.predict.call_args
    assert call_args == [
        ("a question", "low relevance text"),
        ("a question", "high relevance text"),
        ("a question", "medium relevance text"),
    ]


def test_rerank_preserves_chunk_identity_other_than_score():
    c1 = _make_chunk("c1", "some text", score=0.9)
    mock_model = MagicMock()
    mock_model.predict.return_value = [3.5]
    reranker.set_model(mock_model)

    (result,) = reranker.rerank("q", [c1])

    assert result.score == 3.5
    assert result.chunk_id == c1.chunk_id
    assert result.document_id == c1.document_id
    assert result.document_name == c1.document_name
    assert result.text == c1.text
    assert result is not c1  # a new instance, not a mutation of the original


def test_rerank_real_model_scores_ontopic_higher_than_offtopic_no_context_cases():
    # Empirical validation for retriever.py's MIN_RERANK_SCORE docstring
    # (ADR-17's acceptance check): the two no-context control cases that
    # motivated the reranker must score well below MIN_RERANK_SCORE, while a
    # real suggested question's top candidate scores well above it.
    _ingest_all_demo_content()

    def top_rerank_score(question: str) -> float:
        query_vector = embed_query(question)
        candidates = retrieve(query_vector, knowledge_base_id="kb_demo")
        assert candidates, f"expected Stage 8 pre-filter to pass some candidates for {question!r}"
        reranked = reranker.rerank(question, candidates)
        return reranked[0].score

    genuine_score = top_rerank_score("How many days of PTO do full-time employees accrue per year?")
    weather_score = top_rerank_score("What is the weather forecast for tomorrow?")
    tax_score = top_rerank_score("How do I file my personal income taxes?")

    assert genuine_score > MIN_RERANK_SCORE
    assert weather_score < MIN_RERANK_SCORE
    assert tax_score < MIN_RERANK_SCORE


def test_resume_fixture_survives_full_funnel_with_reranking():
    # ADR-17 validation requirement: the short fact-list document that
    # motivated the BGE embedding-model migration must still retrieve
    # correctly through the new retrieve -> rerank -> threshold funnel, not
    # just through Stage 8's cosine retrieve() alone (retriever.py's
    # existing test_retrieval_succeeds_on_short_fact_list_document only
    # covers that earlier stage). This is retriever.py's documented tightest
    # real margin (-10.311 vs. MIN_RERANK_SCORE=-10.5).
    units = extract_and_clean(str(FIXTURES / "synthetic_resume.md"), "md")
    chunks = chunk_document(
        units,
        document_id="doc-resume",
        knowledge_base_id="kb_resume",
        document_name="synthetic_resume.md",
    )
    vectors = embed_texts([c.text for c in chunks])
    vector_store.upsert_chunks(chunks, vectors)

    question = "What programming languages does this person know?"
    query_vector = embed_query(question)
    candidates = retrieve(query_vector, knowledge_base_id="kb_resume")
    reranked = reranker.rerank(question, candidates)
    usable = apply_rerank_threshold(reranked)

    assert usable
    assert any("Python" in c.text for c in usable)
