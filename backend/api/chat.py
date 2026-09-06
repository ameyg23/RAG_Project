"""POST /chat (docs/API.md, ADR-18): streams real-time pipeline progress as
newline-delimited JSON (NDJSON). Everything checkable BEFORE the RAG
pipeline starts (unknown/forbidden knowledge_base_id, empty KB, invalid
message) stays a plain, non-streamed JSON error response via ApiError -
identical to before ADR-18, since none of that needs progress reporting.
Once those checks pass, the response is a StreamingResponse
(media_type=application/x-ndjson): one JSON object per line, ending in
exactly one terminal event (COMPLETED or ERROR). See
docs/ARCHITECTURE_DECISIONS.md ADR-18 for the full wire format, the
stage-to-pipeline-code mapping, and the error taxonomy.
"""

import json
import logging
from collections.abc import Generator

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from errors import ApiError
from ingestion.embed import embed_query
from models.schemas import ChatRequest
from retrieval import generation, query_rewrite, retriever, vector_store
from store import (
    DEMO_KB_ID,
    is_demo_document_id,
    known_kb_id,
    session_owns_kb,
    touch_session_activity,
)

logger = logging.getLogger("backend")

router = APIRouter()


def _event(data: dict) -> bytes:
    return (json.dumps(data) + "\n").encode("utf-8")


def _error_event(code: str, message: str, *, retryable: bool) -> bytes:
    return _event({"stage": "ERROR", "code": code, "message": message, "retryable": retryable})


def _apply_removed_flags(sources: list[dict], *, knowledge_base_id: str) -> list[dict]:
    """Stage 14's new existence check (ADR-18, FR-042 - closes a real,
    previously-hardcoded `is_removed: False` gap in generation.build_sources).

    For each *distinct* cited document_id, checks whether it still has any
    chunks in the vector store right now - a document can be deleted
    (DELETE /documents/{id}) concurrently with an in-flight chat request
    that already retrieved chunks from it moments earlier. Demo documents
    (store.is_demo_document_id) are permanently exempt, being seeded offline
    and never deletable via the public API. If the check itself fails (a
    transient Qdrant hiccup), it is caught and logged server-side, degrading
    to is_removed=False for the affected source(s) rather than failing an
    otherwise-successful answer - the same graceful-degrade philosophy
    ADR-16 already established for query-rewrite failures.
    """
    removed_by_document_id: dict[str, bool] = {}
    for document_id in {s["document_id"] for s in sources}:
        if is_demo_document_id(document_id):
            removed_by_document_id[document_id] = False
            continue
        try:
            count = vector_store.count_chunks_for_document(
                document_id, knowledge_base_id=knowledge_base_id
            )
            removed_by_document_id[document_id] = count == 0
        except Exception:
            logger.exception(
                "is_removed existence check failed for document_id=%s; degrading to "
                "is_removed=False for this source",
                document_id,
            )
            removed_by_document_id[document_id] = False

    for source in sources:
        source["is_removed"] = removed_by_document_id[source["document_id"]]
    return sources


def _stream_chat(*, kb_id: str, message: str, history: list[dict]) -> Generator[bytes]:
    """Yields one NDJSON event per real pipeline milestone (ADR-18).

    Each stage event is yielded *before* its corresponding work begins, and
    the next event is yielded only once that work's real result is
    available - a fast stage flashes by almost instantly, a slow one stays
    visible exactly as long as the real call takes. No sleep/timer of any
    kind is introduced. A failure at any stage ends the stream with exactly
    one terminal ERROR event instead of the next stage/COMPLETED event; the
    HTTP status is already 200 by the time this generator runs (it cannot
    change), so retryable-vs-not travels in the event body (docs/API.md).
    """
    try:
        yield _event({"stage": "SEARCHING"})

        # Stage 6.5 (ADR-16): already fail-safe internally - a Groq failure
        # here falls back to the raw message rather than raising, so it is
        # deliberately NOT inside the VECTOR_STORE_UNAVAILABLE zone below.
        rewritten_query = query_rewrite.rewrite_query(message, history)
        try:
            # Stage 7 (query embedding) + Stage 8 (similarity search) +
            # Stage 9 (MIN_SIMILARITY_SCORE threshold + top_k cap) - all
            # folded into retriever.retrieve() (ADR-17's reranking stage
            # was reverted, see docs/ARCHITECTURE_DECISIONS.md ADR-17's
            # "Reverted" note; there is no longer a wider candidate pool or
            # a separate rerank threshold between search and here).
            query_vector = embed_query(rewritten_query)
            usable_chunks = retriever.retrieve(query_vector, knowledge_base_id=kb_id)
        except Exception:
            logger.exception("Vector store failure during /chat SEARCHING stage")
            yield _error_event(
                "VECTOR_STORE_UNAVAILABLE",
                "The knowledge base search is temporarily unavailable. Please try again shortly.",
                retryable=True,
            )
            return

        yield _event({"stage": "RETRIEVING"})

        yield _event({"stage": "GENERATING"})
        try:
            # Stage 10 (context construction) + Stage 11 (prompt) +
            # Stage 12 (Groq call). The rewritten query is also Stage 11's
            # QUESTION: field (ADR-16) - the user's own chat thread still
            # only ever shows the original request.message.
            answer, chunk_context = generation.answer_question(usable_chunks, rewritten_query)
        except generation.LLMUnavailableError:
            logger.exception("LLM failure during /chat GENERATING stage")
            yield _error_event(
                "LLM_UNAVAILABLE",
                "The answer service is temporarily unavailable. Please try again shortly.",
                retryable=True,
            )
            return

        yield _event({"stage": "VALIDATING"})
        # Stage 13 (answer, pass-through) + Stage 14 (citation resolution,
        # then the new per-document existence check - ADR-18, FR-042).
        sources = generation.build_sources(answer, chunk_context)
        sources = _apply_removed_flags(sources, knowledge_base_id=kb_id)

        yield _event({"stage": "COMPLETED", "answer": answer, "sources": sources})
    except Exception:
        logger.exception("Unexpected error in /chat stream")
        yield _error_event(
            "INTERNAL_ERROR",
            "An unexpected error occurred. Please try again shortly.",
            retryable=False,
        )


@router.post("/chat")
def chat(request: ChatRequest, x_session_token: str | None = Header(default=None)):
    touch_session_activity(x_session_token)
    kb_id = request.knowledge_base_id

    if not known_kb_id(kb_id):
        raise ApiError(404, "KNOWLEDGE_BASE_NOT_FOUND", "That knowledge base does not exist.")

    if kb_id != DEMO_KB_ID:
        if not x_session_token or not session_owns_kb(x_session_token, kb_id):
            raise ApiError(
                403, "FORBIDDEN_KNOWLEDGE_BASE", "You do not have access to this knowledge base."
            )

    # Readiness is decided by Qdrant, not the mock store: once a document is
    # READY its existence is represented entirely by its chunks
    # (docs/DATA_MODEL.md) — the mock store only ever tracks the transient
    # UPLOADED/PROCESSING/FAILED states. This check (and everything above)
    # runs BEFORE the stream opens (ADR-18) - still a plain HTTP error
    # response, unaffected by anything below.
    if vector_store.count_chunks_for_knowledge_base(kb_id) == 0:
        raise ApiError(
            503, "EMPTY_KNOWLEDGE_BASE", "This knowledge base has no ready documents yet."
        )

    # Stage 6.5 input (ADR-16): conversation_history is never persisted -
    # read once here, handed to the generator, and discarded at the end of
    # this one request (docs/DATA_MODEL.md §6 amendment).
    history = [turn.model_dump() for turn in request.conversation_history]

    return StreamingResponse(
        _stream_chat(kb_id=kb_id, message=request.message, history=history),
        media_type="application/x-ndjson",
    )
