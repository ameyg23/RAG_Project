"""Stage 5/7 of docs/RAG_PIPELINE.md: embedding + query embedding.

Local sentence-transformers model (ADR-06) — no external API, no rate
limit.

BAAI/bge-small-en-v1.5 (the current EMBEDDING_MODEL_NAME) is a
retrieval-tuned, *asymmetric* model: per its documented usage convention,
passages are embedded as-is, while queries must be prefixed with a fixed
instruction string so a query lands in the same region of the embedding
space as the passages relevant to it. That means passage-time and
query-time embedding are no longer the same operation on the same input
shape — embed_texts() (passages: document chunks, batched, no prefix) and
embed_query() (a single user question, prefixed) are two thin wrappers
around the same underlying model, used by different call sites:
  - embed_texts(): ingestion/pipeline.py, scripts/seed_demo_kb.py
  - embed_query(): api/chat.py
"""

from sentence_transformers import SentenceTransformer

from config import settings

_model: SentenceTransformer | None = None

# BGE's documented query-side instruction prefix (bge-small-en-v1.5 model
# card). Applied only to the single query embedding at retrieval time —
# never to passage/chunk text at ingestion time.
QUERY_INSTRUCTION_PREFIX = "Represent this sentence for searching relevant passages: "


def get_model() -> SentenceTransformer:
    """Load the embedding model once per process (not once per request)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Passage-side embedding: document chunks, embedded as-is (no prefix)."""
    if not texts:
        return []
    vectors = get_model().encode(texts, batch_size=32)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    """Query-side embedding: a single user question, with the BGE
    query-instruction prefix applied so it lands in the same retrieval
    space as the unprefixed passage embeddings it's compared against."""
    (vector,) = embed_texts([QUERY_INSTRUCTION_PREFIX + text])
    return vector
