from pathlib import Path

import pytest

from ingestion.chunk import CHUNK_OVERLAP, CHUNK_SIZE, chunk_document
from ingestion.extract import extract_and_clean

FIXTURES = Path(__file__).parent / "fixtures"
DEMO_CONTENT = Path(__file__).parent.parent / "demo_content"

CHUNK_SIZE_TOLERANCE = 850


def _chunk(units, **overrides):
    kwargs = {
        "document_id": "doc-1",
        "knowledge_base_id": "kb_demo",
        "document_name": "test-document",
    }
    kwargs.update(overrides)
    return chunk_document(units, **kwargs)


def test_chunk_size_bound_on_real_demo_content():
    units = extract_and_clean(str(DEMO_CONTENT / "04_security_policy.md"), "md")
    chunks = _chunk(units)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= CHUNK_SIZE_TOLERANCE


def _overlap_len(a_text, b_text):
    max_check = min(CHUNK_OVERLAP, len(a_text), len(b_text))
    for n in range(max_check, 0, -1):
        if a_text[-n:] == b_text[:n]:
            return n
    return 0


def test_overlap_correctness():
    # RecursiveCharacterTextSplitter's overlap is best-effort: when a split
    # lands cleanly on a separator (e.g. a "\n\n" paragraph break) right at
    # the chunk-size boundary, it can produce zero overlap for that one pair
    # (the separator itself isn't kept in either chunk) — this is expected
    # library behavior, not a chunk_document defect. So we assert overlap
    # exists for *most* consecutive same-unit pairs, not necessarily every one.
    units = extract_and_clean(str(DEMO_CONTENT / "01_employee_handbook.md"), "md")
    chunks = _chunk(units)
    assert len(chunks) >= 3
    same_unit_pairs = [
        (a, b) for a, b in zip(chunks, chunks[1:], strict=False) if a.page == b.page
    ]
    overlap_lengths = [_overlap_len(a.text, b.text) for a, b in same_unit_pairs]
    pairs_with_overlap = sum(1 for n in overlap_lengths if n >= 10)
    assert pairs_with_overlap >= len(same_unit_pairs) - 1, (
        f"Expected overlap on all but at most one boundary, got lengths {overlap_lengths}"
    )
    assert max(overlap_lengths) >= 10


def _merge_overlapping(chunks):
    """De-overlap merge helper: reconstruct original text from ordered,
    overlapping chunks belonging to a single unit."""
    if not chunks:
        return ""
    result = chunks[0].text
    for prev, cur in zip(chunks, chunks[1:], strict=False):
        overlap_len = _overlap_len(prev.text, cur.text)
        if overlap_len == 0:
            # A zero-overlap cut means the splitter dropped a whitespace-ish
            # separator (e.g. "\n\n") entirely rather than keeping it in
            # either chunk — reinsert a single space so words don't merge.
            result += " " + cur.text
        else:
            result += cur.text[overlap_len:]
    return result


def _normalize_whitespace(text):
    return " ".join(text.split())


def test_reconstruction_via_deoverlap_merge():
    # Compared with whitespace normalized: at a zero-overlap boundary (see
    # test_overlap_correctness), the splitter drops the separator itself
    # (e.g. "\n\n") rather than keeping it in either neighboring chunk, so a
    # byte-exact merge isn't achievable — but no actual word is ever lost or
    # duplicated, which is what this test verifies.
    units = extract_and_clean(str(DEMO_CONTENT / "02_product_faq.md"), "md")
    assert len(units) == 1  # markdown extracts as a single unit
    chunks = _chunk(units)
    assert len(chunks) > 1
    merged = _merge_overlapping(chunks)
    assert _normalize_whitespace(merged) == _normalize_whitespace(units[0].text)


def test_short_unit_produces_single_chunk():
    units = extract_and_clean(str(FIXTURES / "sample.txt"), "txt")
    chunks = _chunk(units)
    assert len(chunks) == 1
    assert chunks[0].text == units[0].text
    assert chunks[0].page is None


def test_chunk_boundaries_respect_page_boundaries():
    units = extract_and_clean(str(FIXTURES / "sample.pdf"), "pdf")
    chunks = _chunk(units)
    pages_seen = {c.page for c in chunks}
    assert pages_seen == {1, 2}
    for c in chunks:
        assert c.page in (1, 2)
    page1_text = " ".join(c.text for c in chunks if c.page == 1)
    page2_text = " ".join(c.text for c in chunks if c.page == 2)
    assert "Quarterly revenue" in page1_text
    assert "Customer satisfaction" in page2_text
    assert "Quarterly revenue" not in page2_text
    assert "Customer satisfaction" not in page1_text


def test_metadata_completeness():
    units = extract_and_clean(str(DEMO_CONTENT / "03_onboarding_guide.md"), "md")
    chunks = _chunk(
        units, document_id="doc-42", knowledge_base_id="kb_demo", document_name="onboarding.md"
    )
    assert len(chunks) > 1
    seen_indices = []
    for c in chunks:
        assert c.chunk_id
        assert c.document_id == "doc-42"
        assert c.knowledge_base_id == "kb_demo"
        assert c.document_name == "onboarding.md"
        assert c.text
        assert c.chunk_id == f"{c.document_id}_{c.chunk_index}"
        seen_indices.append(c.chunk_index)
    assert seen_indices == list(range(len(chunks)))  # sequential, no gaps/dupes


def test_empty_knowledge_base_id_raises():
    units = extract_and_clean(str(FIXTURES / "sample.txt"), "txt")
    with pytest.raises(ValueError):
        chunk_document(units, document_id="doc-1", knowledge_base_id="", document_name="x")


def test_empty_document_id_raises():
    units = extract_and_clean(str(FIXTURES / "sample.txt"), "txt")
    with pytest.raises(ValueError):
        chunk_document(units, document_id="", knowledge_base_id="kb_demo", document_name="x")


def test_config_values_match_docs():
    assert CHUNK_SIZE == 800
    assert CHUNK_OVERLAP == 120
