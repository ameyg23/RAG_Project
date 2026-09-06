"""Stage 5/7 of docs/RAG_PIPELINE.md: embedding + query embedding.

Local embeddings (ADR-06), run via fastembed/ONNX Runtime instead of
sentence-transformers/torch as of ADR-20 — no external API, no rate limit,
and no PyTorch dependency (the memory cost that made the free-tier Render
deploy OOM under real request load, per ADR-19).

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

The prefix is applied manually here rather than via fastembed's own
model-specific query_embed() convenience method, so this exact,
already-evaluated prefix behavior carries over unchanged across the
ADR-20 runtime swap instead of depending on fastembed's own (undocumented,
per-model) prefix logic for this model.
"""

from fastembed import TextEmbedding

from config import settings

_model: TextEmbedding | None = None

# BGE's documented query-side instruction prefix (bge-small-en-v1.5 model
# card). Applied only to the single query embedding at retrieval time —
# never to passage/chunk text at ingestion time.
QUERY_INSTRUCTION_PREFIX = "Represent this sentence for searching relevant passages: "


def get_model() -> TextEmbedding:
    """Load the embedding model once per process (not once per request).

    threads=1 matches the BLAS-thread-pool cap this project already applies
    around this model in render.yaml/backend/Dockerfile (OMP_NUM_THREADS=1
    etc.) — one more thread pool would add its own memory overhead for
    negligible speed gain on a single shared free-tier vCPU.
    """
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=settings.EMBEDDING_MODEL_NAME, threads=1)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Passage-side embedding: document chunks, embedded as-is (no prefix)."""
    if not texts:
        return []
    vectors = get_model().embed(texts, batch_size=32)
    return [vector.tolist() for vector in vectors]


def embed_query(text: str) -> list[float]:
    """Query-side embedding: a single user question, with the BGE
    query-instruction prefix applied so it lands in the same retrieval
    space as the unprefixed passage embeddings it's compared against."""
    (vector,) = embed_texts([QUERY_INSTRUCTION_PREFIX + text])
    return vector
