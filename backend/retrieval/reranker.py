"""Stage 8.5 of docs/RAG_PIPELINE.md: reranking (ADR-17).

A bi-encoder (BAAI/bge-small-en-v1.5, ingestion/embed.py) embeds the query
and each chunk independently, so its cosine similarity (retriever.py's
Stage 8) is a coarse topical/lexical proximity signal — this is exactly why
some clearly-off-topic control questions still clear MIN_SIMILARITY_SCORE
(see retriever.py's docstring for the measured cases). A cross-encoder
jointly attends over the full (query, chunk) pair in one forward pass,
which is a strictly more discriminating "does this chunk actually answer
this question" signal — see ADR-17 for the full architectural reasoning.

Model loaded once per process (module-level singleton), mirroring
ingestion/embed.py's get_model() and generation.py's get_client() pattern —
never per-request, for the same cold-start-cost reason ADR-06 established.
"""

from dataclasses import replace

from sentence_transformers import CrossEncoder

from retrieval.retriever import RetrievedChunk

# ADR-17: cross-encoder/ms-marco-MiniLM-L-6-v2 — the standard default for
# reranking bi-encoder retrieval output, already available via the
# sentence-transformers dependency embed.py already uses (zero new package).
CROSS_ENCODER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_model: CrossEncoder | None = None


def get_model() -> CrossEncoder:
    """Load the cross-encoder once per process (not once per request)."""
    global _model
    if _model is None:
        _model = CrossEncoder(CROSS_ENCODER_MODEL_NAME)
    return _model


def set_model(model: CrossEncoder) -> None:
    """Test-only override."""
    global _model
    _model = model


def rerank(query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Score each (query, chunk.text) pair and re-sort descending by that
    score, discarding Stage 8's cosine ordering (it was always provisional —
    docs/RAG_PIPELINE.md Stage 8's Output note).

    `query` must be the Stage 6.5 rewritten query, not the raw original
    message — the referent-resolution problem ADR-16 exists to fix applies
    to the reranker's judgment exactly as it does to embedding and
    generation (ADR-17, Stage 8.5's Input note).

    Returns the same chunks as new RetrievedChunk instances with `.score`
    replaced by the cross-encoder's score — NOT numerically comparable to
    the cosine score it replaces (retriever.MIN_RERANK_SCORE, not
    retriever.MIN_SIMILARITY_SCORE, is the threshold meant to be applied to
    this output). Callers must not read `.score` as cosine similarity on
    anything returned from here.
    """
    if not candidates:
        return []

    pairs = [(query, chunk.text) for chunk in candidates]
    scores = get_model().predict(pairs)

    rescored = [
        replace(chunk, score=float(score)) for chunk, score in zip(candidates, scores, strict=True)
    ]
    rescored.sort(key=lambda chunk: chunk.score, reverse=True)
    return rescored
