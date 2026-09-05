"""Stage 8-10 of docs/RAG_PIPELINE.md: similarity search, top-K threshold,
context construction.

Threshold calibration note: empirically re-verified against all 4 real
demo_content files and all 5 real suggested_questions.json entries — every
answerable question's correct-document top hit scored between 0.48 and 0.84,
while an unrelated control question ("What is the capital of France?")
topped out at 0.034. 0.35 sits comfortably in that gap; kept unchanged.
"""

from dataclasses import dataclass

from retrieval import vector_store

TOP_K = 5
MIN_SIMILARITY_SCORE = 0.35


@dataclass
class RetrievedChunk:
    score: float
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    document_name: str
    chunk_index: int
    page: int | None
    text: str


@dataclass
class ChunkContext:
    context_text: str
    citation_map: dict[int, RetrievedChunk]


def retrieve(
    query_vector: list[float],
    *,
    knowledge_base_id: str,
    top_k: int = TOP_K,
    min_score: float = MIN_SIMILARITY_SCORE,
) -> list[RetrievedChunk]:
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    results = vector_store.query(query_vector, knowledge_base_id=knowledge_base_id, top_k=top_k)

    # Qdrant already returns results sorted descending by score, but don't
    # assume it silently forever — verify defensively rather than trust blindly.
    results = sorted(results, key=lambda r: r["score"], reverse=True)

    chunks = [RetrievedChunk(**r) for r in results if r["score"] >= min_score]
    return chunks


def build_context(chunks: list[RetrievedChunk]) -> ChunkContext:
    if not chunks:
        return ChunkContext(context_text="", citation_map={})

    parts = []
    citation_map: dict[int, RetrievedChunk] = {}
    for i, chunk in enumerate(chunks, start=1):
        parts.append(f"[{i}] {chunk.text}")
        citation_map[i] = chunk

    context_text = "\n\n".join(parts)
    return ChunkContext(context_text=context_text, citation_map=citation_map)
