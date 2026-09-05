from pathlib import Path
from unittest.mock import MagicMock

import pytest
from qdrant_client import QdrantClient

from ingestion.chunk import chunk_document
from ingestion.embed import embed_texts
from ingestion.extract import extract_and_clean
from retrieval import vector_store

DEMO_CONTENT = Path(__file__).parent.parent / "demo_content"


@pytest.fixture(autouse=True)
def fresh_in_memory_client():
    """Every test gets its own isolated in-memory Qdrant instance."""
    vector_store.set_client(QdrantClient(":memory:"))
    yield


def test_ensure_collection_creates_required_payload_indexes():
    # Regression guard for a real bug found by verifying against a live
    # Qdrant Cloud cluster: the server (unlike the in-memory mode used
    # everywhere else in this file) rejects a filter on a field with no
    # payload index at all. In-memory Qdrant silently no-ops index
    # creation and never enforces it, so it can't catch a future removal
    # of these calls by itself — this test verifies the calls actually
    # happen, using a mock, since that's observable regardless of backend.
    mock_client = MagicMock()
    mock_client.collection_exists.return_value = False
    vector_store.set_client(mock_client)

    vector_store.ensure_collection()

    mock_client.create_collection.assert_called_once()
    indexed_fields = {
        call.kwargs.get("field_name") for call in mock_client.create_payload_index.call_args_list
    }
    assert indexed_fields == {"knowledge_base_id", "document_id"}


def _chunks_and_vectors(filename, *, document_id, knowledge_base_id, document_name=None):
    units = extract_and_clean(str(DEMO_CONTENT / filename), "md")
    chunks = chunk_document(
        units,
        document_id=document_id,
        knowledge_base_id=knowledge_base_id,
        document_name=document_name or filename,
    )
    vectors = embed_texts([c.text for c in chunks])
    return chunks, vectors


def test_round_trip_count():
    chunks, vectors = _chunks_and_vectors(
        "01_employee_handbook.md", document_id="doc-h", knowledge_base_id="kb_demo"
    )
    vector_store.upsert_chunks(chunks, vectors)
    assert vector_store.count_chunks_for_document("doc-h", knowledge_base_id="kb_demo") == len(
        chunks
    )


def test_query_returns_relevant_document():
    handbook_chunks, handbook_vectors = _chunks_and_vectors(
        "01_employee_handbook.md", document_id="doc-handbook", knowledge_base_id="kb_demo"
    )
    security_chunks, security_vectors = _chunks_and_vectors(
        "04_security_policy.md", document_id="doc-security", knowledge_base_id="kb_demo"
    )
    vector_store.upsert_chunks(handbook_chunks, handbook_vectors)
    vector_store.upsert_chunks(security_chunks, security_vectors)

    (query_vector,) = embed_texts(["How many vacation days do I get?"])
    results = vector_store.query(query_vector, knowledge_base_id="kb_demo", top_k=3)

    assert results
    assert results[0]["document_id"] == "doc-handbook"


def test_knowledge_base_isolation_with_near_duplicate_content():
    # Adversarial by design: identical text upserted under two different
    # knowledge_base_id values. A broken/missing filter would still "work"
    # against dissimilar content, so this must use the same text to prove
    # isolation is enforced by the filter, not by content difference.
    shared_text = (
        "Full-time employees accrue 15 days of paid time off per year, "
        "with up to 5 unused days rolling over to the next year."
    )
    (vector,) = embed_texts([shared_text])

    from ingestion.chunk import DocumentChunk

    chunk_a = DocumentChunk(
        chunk_id="doc-a_0",
        document_id="doc-a",
        knowledge_base_id="kb_a",
        document_name="a.md",
        chunk_index=0,
        page=None,
        text=shared_text,
    )
    chunk_b = DocumentChunk(
        chunk_id="doc-b_0",
        document_id="doc-b",
        knowledge_base_id="kb_b",
        document_name="b.md",
        chunk_index=0,
        page=None,
        text=shared_text,
    )
    vector_store.upsert_chunks([chunk_a], [vector])
    vector_store.upsert_chunks([chunk_b], [vector])

    results_a = vector_store.query(vector, knowledge_base_id="kb_a", top_k=10)
    results_b = vector_store.query(vector, knowledge_base_id="kb_b", top_k=10)

    assert results_a
    assert all(r["knowledge_base_id"] == "kb_a" for r in results_a)
    assert results_b
    assert all(r["knowledge_base_id"] == "kb_b" for r in results_b)


def test_idempotent_upsert():
    chunks, vectors = _chunks_and_vectors(
        "03_onboarding_guide.md", document_id="doc-onb", knowledge_base_id="kb_demo"
    )
    one_chunk = chunks[:1]
    one_vector = vectors[:1]

    vector_store.upsert_chunks(one_chunk, one_vector)
    vector_store.upsert_chunks(one_chunk, one_vector)  # same chunk_id again

    assert vector_store.count_chunks_for_document("doc-onb", knowledge_base_id="kb_demo") == 1


def test_delete_removes_only_target_document():
    chunks_1, vectors_1 = _chunks_and_vectors(
        "02_product_faq.md", document_id="doc-faq", knowledge_base_id="kb_demo"
    )
    chunks_2, vectors_2 = _chunks_and_vectors(
        "04_security_policy.md", document_id="doc-sec", knowledge_base_id="kb_demo"
    )
    vector_store.upsert_chunks(chunks_1, vectors_1)
    vector_store.upsert_chunks(chunks_2, vectors_2)

    vector_store.delete_document("doc-faq", knowledge_base_id="kb_demo")

    assert vector_store.count_chunks_for_document("doc-faq", knowledge_base_id="kb_demo") == 0
    assert vector_store.count_chunks_for_document(
        "doc-sec", knowledge_base_id="kb_demo"
    ) == len(chunks_2)


def test_query_requires_knowledge_base_id():
    with pytest.raises(ValueError):
        vector_store.query([0.0] * 384, knowledge_base_id="")


def test_upsert_requires_knowledge_base_id_on_every_chunk():
    from ingestion.chunk import DocumentChunk

    bad_chunk = DocumentChunk(
        chunk_id="x_0",
        document_id="x",
        knowledge_base_id="",
        document_name="x.md",
        chunk_index=0,
        page=None,
        text="text",
    )
    with pytest.raises(ValueError):
        vector_store.upsert_chunks([bad_chunk], [[0.0] * 384])


def test_delete_requires_knowledge_base_id():
    with pytest.raises(ValueError):
        vector_store.delete_document("doc-1", knowledge_base_id="")


def test_count_chunks_for_knowledge_base_zero_when_empty():
    assert vector_store.count_chunks_for_knowledge_base("kb_nothing_here") == 0


def test_count_chunks_for_knowledge_base_counts_across_documents():
    chunks_1, vectors_1 = _chunks_and_vectors(
        "01_employee_handbook.md", document_id="doc-h", knowledge_base_id="kb_demo"
    )
    chunks_2, vectors_2 = _chunks_and_vectors(
        "02_product_faq.md", document_id="doc-faq", knowledge_base_id="kb_demo"
    )
    vector_store.upsert_chunks(chunks_1, vectors_1)
    vector_store.upsert_chunks(chunks_2, vectors_2)

    assert vector_store.count_chunks_for_knowledge_base("kb_demo") == len(chunks_1) + len(chunks_2)


def test_count_chunks_for_knowledge_base_requires_knowledge_base_id():
    with pytest.raises(ValueError):
        vector_store.count_chunks_for_knowledge_base("")


def test_with_retry_succeeds_after_transient_failures(monkeypatch):
    # Reproduces the exact real-world pattern seen live: a transient
    # connection blip resolving on retry, not a permanent failure.
    monkeypatch.setattr(vector_store.time, "sleep", lambda _seconds: None)
    call_count = {"n": 0}

    def flaky():
        call_count["n"] += 1
        if call_count["n"] < vector_store.MAX_QDRANT_ATTEMPTS:
            raise ConnectionError("simulated transient blip")
        return "ok"

    assert vector_store._with_retry(flaky) == "ok"
    assert call_count["n"] == vector_store.MAX_QDRANT_ATTEMPTS


def test_is_reachable_true_for_working_client():
    assert vector_store.is_reachable() is True


def test_is_reachable_false_when_client_raises():
    mock_client = MagicMock()
    mock_client.collection_exists.side_effect = ConnectionError("simulated outage")
    vector_store.set_client(mock_client)
    assert vector_store.is_reachable() is False


def test_is_reachable_does_not_retry(monkeypatch):
    # A liveness check must stay fast even during a real outage - it must
    # not go through _with_retry's multi-second backoff loop.
    sleep_calls = {"n": 0}
    monkeypatch.setattr(vector_store.time, "sleep", lambda _s: sleep_calls.__setitem__("n", 1))
    mock_client = MagicMock()
    mock_client.collection_exists.side_effect = ConnectionError("simulated outage")
    vector_store.set_client(mock_client)

    vector_store.is_reachable()

    assert mock_client.collection_exists.call_count == 1
    assert sleep_calls["n"] == 0


def test_with_retry_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr(vector_store.time, "sleep", lambda _seconds: None)
    call_count = {"n": 0}

    def always_fails():
        call_count["n"] += 1
        raise ConnectionError("persistent failure")

    with pytest.raises(ConnectionError):
        vector_store._with_retry(always_fails)
    assert call_count["n"] == vector_store.MAX_QDRANT_ATTEMPTS
