"""Stage 5/7 of docs/RAG_PIPELINE.md: embedding + query embedding.

Local sentence-transformers model (ADR-06) — no external API, no rate
limit. The same embed_texts() function is used for both document chunks
(batched) and a single query, guaranteeing they land in the same
embedding space.
"""

from sentence_transformers import SentenceTransformer

from config import settings

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Load the embedding model once per process (not once per request)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = get_model().encode(texts, batch_size=32)
    return vectors.tolist()
