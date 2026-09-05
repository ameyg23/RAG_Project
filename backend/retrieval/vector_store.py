"""Stage 6/8 of docs/RAG_PIPELINE.md: vector storage + similarity search.

Single Qdrant choke point (ADR-07, ADR-14) — every read/write requires a
non-empty knowledge_base_id with no default, since this is the entire
knowledge-base isolation guarantee (NFR-004).
"""

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from config import settings
from ingestion.chunk import DocumentChunk

COLLECTION_NAME = "rag_chunks"
VECTOR_SIZE = 384  # ADR-06: sentence-transformers/all-MiniLM-L6-v2 output dim

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    """Lazily create and cache the Qdrant client, once per process.

    Production path (ADR-07): connect to Qdrant Cloud via settings.QDRANT_URL/
    QDRANT_API_KEY. Fallback: an in-process, in-memory Qdrant instance when
    those aren't set — this is a local-dev/test convenience ONLY. It is not
    persistent (data vanishes when the process exits) and is not the
    deployed architecture; Qdrant Cloud was chosen specifically because
    Render's backend disk is ephemeral (ADR-07), which the in-memory
    fallback does not change or replace.
    """
    global _client
    if _client is None:
        if settings.QDRANT_URL:
            _client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
        else:
            _client = QdrantClient(":memory:")
    return _client


def set_client(client: QdrantClient) -> None:
    """Test-only override so each test can inject a fresh in-memory client."""
    global _client
    _client = client


def ensure_collection() -> None:
    """Idempotently create the shared collection (and its required payload
    indexes) if it doesn't exist yet.

    A real Qdrant Cloud server (unlike the in-memory local mode used in
    tests) refuses to filter on a payload field with no index at all,
    raising a 400 "Index required but not found" error — this was only
    discovered by verifying against a real live cluster. Every field this
    module filters by (knowledge_base_id, document_id) needs a keyword
    payload index, since the entire knowledge-base isolation guarantee
    (NFR-004, ADR-14) depends on the knowledge_base_id filter actually
    working, not just being present in the query.
    """
    client = get_client()
    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        client.create_payload_index(
            COLLECTION_NAME, field_name="knowledge_base_id", field_schema="keyword"
        )
        client.create_payload_index(
            COLLECTION_NAME, field_name="document_id", field_schema="keyword"
        )


def _point_id(chunk_id: str) -> str:
    """Qdrant point IDs must be an unsigned int or UUID; chunk_id is an
    arbitrary string, so map it deterministically — upserting the same
    chunk_id twice then overwrites the same point rather than duplicating
    it (Stage 6's idempotency requirement)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def upsert_chunks(chunks: list[DocumentChunk], vectors: list[list[float]]) -> None:
    if len(chunks) != len(vectors):
        raise ValueError("chunks and vectors must be the same length")
    for chunk in chunks:
        if not chunk.knowledge_base_id:
            raise ValueError("every chunk must have a non-empty knowledge_base_id (ADR-14)")

    if not chunks:
        return

    ensure_collection()
    points = [
        PointStruct(
            id=_point_id(chunk.chunk_id),
            vector=vector,
            payload={
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "knowledge_base_id": chunk.knowledge_base_id,
                "document_name": chunk.document_name,
                "chunk_index": chunk.chunk_index,
                "page": chunk.page,
                "text": chunk.text,
            },
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    get_client().upsert(COLLECTION_NAME, points=points)


def query(query_vector: list[float], *, knowledge_base_id: str, top_k: int = 5) -> list[dict]:
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    ensure_collection()
    response = get_client().query_points(
        COLLECTION_NAME,
        query=query_vector,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="knowledge_base_id", match=MatchValue(value=knowledge_base_id)
                )
            ]
        ),
        limit=top_k,
    )
    return [{"score": p.score, **p.payload} for p in response.points]


def delete_document(document_id: str, *, knowledge_base_id: str) -> None:
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    ensure_collection()
    get_client().delete(
        COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                    FieldCondition(
                        key="knowledge_base_id", match=MatchValue(value=knowledge_base_id)
                    ),
                ]
            )
        ),
    )


def count_chunks_for_document(document_id: str, *, knowledge_base_id: str) -> int:
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    ensure_collection()
    result = get_client().count(
        COLLECTION_NAME,
        count_filter=Filter(
            must=[
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                FieldCondition(key="knowledge_base_id", match=MatchValue(value=knowledge_base_id)),
            ]
        ),
    )
    return result.count
