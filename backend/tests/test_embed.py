import math
from pathlib import Path

from ingestion.chunk import chunk_document
from ingestion.embed import QUERY_INSTRUCTION_PREFIX, embed_query, embed_texts
from ingestion.extract import extract_and_clean

DEMO_CONTENT = Path(__file__).parent.parent / "demo_content"


def test_single_text_dimensionality():
    vectors = embed_texts(["hello world"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 384


def test_batch_dimensionality():
    vectors = embed_texts(["a", "b", "c"])
    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == 384


def test_determinism():
    first = embed_texts(["The quick brown fox jumps over the lazy dog."])
    second = embed_texts(["The quick brown fox jumps over the lazy dog."])
    # Observed empirically: CPU sentence-transformers inference on this
    # model is exactly reproducible for repeated calls in the same process
    # (no nondeterminism from batching/threading was seen), so exact
    # equality is asserted rather than a tolerance-based fallback.
    assert first == second


def test_empty_input_returns_empty_list():
    assert embed_texts([]) == []


def test_embed_query_returns_single_vector_of_correct_dimension():
    vector = embed_query("How many vacation days do I get?")
    assert isinstance(vector, list)
    assert len(vector) == 384
    assert isinstance(vector[0], float)


def test_embed_query_applies_prefix_embed_texts_does_not():
    # The query-side wrapper must embed the *prefixed* text, not the raw
    # question - i.e. embed_query(q) must equal embed_texts([PREFIX + q])
    # exactly, and must differ from embedding the raw (unprefixed) question,
    # proving the asymmetric passage/query convention is actually wired up
    # end-to-end rather than just present as an unused constant.
    question = "How many vacation days do I get?"
    query_vector = embed_query(question)
    (prefixed_vector,) = embed_texts([QUERY_INSTRUCTION_PREFIX + question])
    (raw_vector,) = embed_texts([question])

    assert query_vector == prefixed_vector
    assert query_vector != raw_vector


def test_embed_query_determinism():
    first = embed_query("The quick brown fox jumps over the lazy dog.")
    second = embed_query("The quick brown fox jumps over the lazy dog.")
    assert first == second


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def test_semantic_similarity_on_real_demo_content():
    handbook_units = extract_and_clean(str(DEMO_CONTENT / "01_employee_handbook.md"), "md")
    security_units = extract_and_clean(str(DEMO_CONTENT / "04_security_policy.md"), "md")

    handbook_chunks = chunk_document(
        handbook_units,
        document_id="doc-handbook",
        knowledge_base_id="kb_demo",
        document_name="01_employee_handbook.md",
    )
    security_chunks = chunk_document(
        security_units,
        document_id="doc-security",
        knowledge_base_id="kb_demo",
        document_name="04_security_policy.md",
    )

    pto_chunk = next(c for c in handbook_chunks if "Paid Time Off" in c.text or "PTO" in c.text)
    twofa_chunk = next(
        c for c in security_chunks if "Two-Factor Authentication" in c.text or "2FA" in c.text
    )

    query = "How many vacation days do I get?"
    query_vec = embed_query(query)
    pto_vec, twofa_vec = embed_texts([pto_chunk.text, twofa_chunk.text])

    sim_pto = _cosine_similarity(query_vec, pto_vec)
    sim_twofa = _cosine_similarity(query_vec, twofa_vec)

    assert sim_pto > sim_twofa, (
        f"Expected the PTO chunk to score higher for a vacation-days query, "
        f"got sim_pto={sim_pto:.4f} sim_twofa={sim_twofa:.4f}"
    )
