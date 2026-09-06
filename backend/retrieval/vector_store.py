"""Stage 6/8 of docs/RAG_PIPELINE.md: vector storage + similarity search.

Single Qdrant choke point (ADR-07, ADR-14) — every read/write requires a
non-empty knowledge_base_id with no default, since this is the entire
knowledge-base isolation guarantee (NFR-004).
"""

import time
import uuid
from typing import TypeVar

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
VECTOR_SIZE = 384  # ADR-06: BAAI/bge-small-en-v1.5 output dim

# Transient network/DNS blips connecting to Qdrant Cloud have been observed
# repeatedly during this project's development (always resolving on a quick
# retry) - this smooths over that class of failure across every
# Qdrant-touching function in this module, not just document ingestion
# (ingestion/pipeline.py has its own narrower retry specifically around the
# upsert step, predating this more general one; the two aren't redundant -
# this one also covers query/delete/count/collection-setup).
MAX_QDRANT_ATTEMPTS = 4
QDRANT_RETRY_DELAY_SECONDS = 1.5

_T = TypeVar("_T")

_client: QdrantClient | None = None


def _with_retry(operation) -> "_T":
    last_exc: Exception | None = None
    for attempt in range(1, MAX_QDRANT_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - broad by design, see comment above
            last_exc = exc
            if attempt < MAX_QDRANT_ATTEMPTS:
                time.sleep(QDRANT_RETRY_DELAY_SECONDS)
    raise last_exc


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


def is_reachable() -> bool:
    """Single, non-retrying connectivity check for GET /health (docs/API.md).

    Intentionally skips _with_retry: a liveness endpoint must stay fast and
    report the true current state even during a real outage, not spend up
    to MAX_QDRANT_ATTEMPTS * QDRANT_RETRY_DELAY_SECONDS blocking on retries.
    """
    try:
        get_client().collection_exists(COLLECTION_NAME)
        return True
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False


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
    if not _with_retry(lambda: client.collection_exists(COLLECTION_NAME)):
        _with_retry(
            lambda: client.create_collection(
                COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
        )
        _with_retry(
            lambda: client.create_payload_index(
                COLLECTION_NAME, field_name="knowledge_base_id", field_schema="keyword"
            )
        )
        _with_retry(
            lambda: client.create_payload_index(
                COLLECTION_NAME, field_name="document_id", field_schema="keyword"
            )
        )


def drop_collection() -> None:
    """Explicitly delete the collection so a subsequent ensure_collection()
    recreates it from scratch.

    One-time migration helper: needed whenever the embedding *model*
    changes even if VECTOR_SIZE doesn't (e.g. an unchanged 384 dims across
    two different models). ensure_collection()'s idempotent create-if-
    missing check only ever looks at whether the collection exists, not
    what embedding space its vectors were written in - it cannot detect a
    model swap by dimension alone, and would otherwise silently leave old
    vectors mixed with new ones in the same collection, corrupting
    retrieval rather than erroring. Callers must re-ingest everything
    (e.g. scripts/seed_demo_kb.py) after calling this.
    """
    client = get_client()
    _with_retry(lambda: client.delete_collection(COLLECTION_NAME))


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
    _with_retry(lambda: get_client().upsert(COLLECTION_NAME, points=points))


def query(query_vector: list[float], *, knowledge_base_id: str, top_k: int = 5) -> list[dict]:
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    ensure_collection()
    response = _with_retry(
        lambda: get_client().query_points(
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
    )
    return [{"score": p.score, **p.payload} for p in response.points]


def delete_document(document_id: str, *, knowledge_base_id: str) -> None:
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    ensure_collection()
    _with_retry(
        lambda: get_client().delete(
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
    )


def delete_knowledge_base_vectors(knowledge_base_id: str) -> None:
    """Delete every chunk vector for an entire knowledge base, across all of
    its documents, keyed only by knowledge_base_id - used exclusively by the
    idle-session reaper (backend/main.py) to purge an abandoned user KB's
    vectors in one call, without needing each document_id individually.
    This is a narrower per-KB delete, not drop_collection()'s "wipe the
    whole shared collection" (that one's a migration helper for an
    embedding-model swap; the two aren't related).

    Must NEVER be called with DEMO_KB_ID - that KB is permanent and shared
    by every visitor. The assertion below is a defense-in-depth guard: a
    bug here wiping the demo KB would be catastrophic and not easily
    recoverable (would require re-running scripts/seed_demo_kb.py).
    """
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    from store import DEMO_KB_ID  # local import: avoids a store<->vector_store cycle

    assert knowledge_base_id != DEMO_KB_ID, (
        "delete_knowledge_base_vectors must never target the permanent demo KB"
    )

    ensure_collection()
    _with_retry(
        lambda: get_client().delete(
            COLLECTION_NAME,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="knowledge_base_id", match=MatchValue(value=knowledge_base_id)
                        )
                    ]
                )
            ),
        )
    )


def count_chunks_for_document(document_id: str, *, knowledge_base_id: str) -> int:
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    ensure_collection()
    result = _with_retry(
        lambda: get_client().count(
            COLLECTION_NAME,
            count_filter=Filter(
                must=[
                    FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                    FieldCondition(
                        key="knowledge_base_id", match=MatchValue(value=knowledge_base_id)
                    ),
                ]
            ),
        )
    )
    return result.count


def count_chunks_for_knowledge_base(knowledge_base_id: str) -> int:
    """Whether this KB has any ready content at all (no document_id filter) —
    the real source of truth for chat.py's 503 EMPTY_KNOWLEDGE_BASE check,
    since a document's READY-ness is represented entirely by its chunks
    existing here, not by any mock-store flag (docs/DATA_MODEL.md)."""
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    ensure_collection()
    result = _with_retry(
        lambda: get_client().count(
            COLLECTION_NAME,
            count_filter=Filter(
                must=[
                    FieldCondition(
                        key="knowledge_base_id", match=MatchValue(value=knowledge_base_id)
                    )
                ]
            ),
        )
    )
    return result.count
