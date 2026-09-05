import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from ingestion.chunk import DocumentChunk, chunk_document
from ingestion.embed import embed_texts
from ingestion.extract import extract_and_clean
from retrieval import vector_store
from retrieval.retriever import RetrievedChunk, build_context, retrieve

DEMO_CONTENT = Path(__file__).parent.parent / "demo_content"
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


def _make_chunk(i, score=0.9):
    return RetrievedChunk(
        score=score,
        chunk_id=f"doc_{i}",
        document_id="doc",
        knowledge_base_id="kb_demo",
        document_name="doc.md",
        chunk_index=i,
        page=None,
        text=f"chunk text {i}",
    )


def test_build_context_citation_markers_match_map():
    chunks = [_make_chunk(0), _make_chunk(1), _make_chunk(2)]
    ctx = build_context(chunks)

    for n in (1, 2, 3):
        assert ctx.context_text.count(f"[{n}]") == 1
    assert set(ctx.citation_map.keys()) == {1, 2, 3}
    assert ctx.citation_map[1] is chunks[0]
    assert ctx.citation_map[2] is chunks[1]
    assert ctx.citation_map[3] is chunks[2]
    # Order: [1] must appear before [2] before [3] in the text.
    assert ctx.context_text.index("[1]") < ctx.context_text.index("[2]") < ctx.context_text.index(
        "[3]"
    )


def test_build_context_empty_input():
    ctx = build_context([])
    assert ctx.context_text == ""
    assert ctx.citation_map == {}


def _ingest_all_demo_content():
    for i, filename in enumerate(DEMO_FILES):
        units = extract_and_clean(str(DEMO_CONTENT / filename), "md")
        chunks = chunk_document(
            units, document_id=f"doc-{i}", knowledge_base_id="kb_demo", document_name=filename
        )
        vectors = embed_texts([c.text for c in chunks])
        vector_store.upsert_chunks(chunks, vectors)


def test_retrieval_hit_rate_on_real_suggested_questions():
    # This is Phase 9's actual Definition of Done: every real, pre-verified
    # answerable question's expected source document survives both top-K
    # and the similarity threshold. Calibration (see retriever.py docstring)
    # confirmed real scores land 0.48-0.84, comfortably above 0.35 — this
    # test is the regression guard for that finding.
    _ingest_all_demo_content()
    questions = json.loads((DEMO_CONTENT / "suggested_questions.json").read_text())

    for q in questions:
        (query_vector,) = embed_texts([q["question"]])
        results = retrieve(query_vector, knowledge_base_id="kb_demo")
        matched_docs = {r.document_name for r in results}
        assert q["source_document"] in matched_docs, (
            f"Question {q['question']!r} expected {q['source_document']!r} "
            f"in results but got {matched_docs}"
        )


def test_threshold_excludes_unrelated_control_question():
    _ingest_all_demo_content()
    (query_vector,) = embed_texts(["What is the capital of France?"])
    results = retrieve(query_vector, knowledge_base_id="kb_demo")
    assert results == []


def test_retrieve_requires_knowledge_base_id():
    with pytest.raises(ValueError):
        retrieve([0.0] * 384, knowledge_base_id="")


def test_retrieve_respects_knowledge_base_isolation():
    # Same adversarial pattern as Phase 8's vector_store test: identical
    # text under two different KB ids, to prove the filter (not content
    # difference) is what enforces isolation at this layer too.
    shared_text = (
        "Full-time employees accrue 15 days of paid time off per year, "
        "with up to 5 unused days rolling over to the next year."
    )
    (vector,) = embed_texts([shared_text])

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

    results_a = retrieve(vector, knowledge_base_id="kb_a")
    results_b = retrieve(vector, knowledge_base_id="kb_b")

    assert results_a and all(r.knowledge_base_id == "kb_a" for r in results_a)
    assert results_b and all(r.knowledge_base_id == "kb_b" for r in results_b)
