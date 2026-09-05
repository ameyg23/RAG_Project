from fastapi import APIRouter, Header

from errors import ApiError
from ingestion.embed import embed_texts
from models.schemas import ChatRequest, ChatResponse, SourceReference
from retrieval import generation, vector_store
from store import DEMO_KB_ID, known_kb_id, session_owns_kb

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, x_session_token: str | None = Header(default=None)):
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
    # UPLOADED/PROCESSING/FAILED states.
    if vector_store.count_chunks_for_knowledge_base(kb_id) == 0:
        raise ApiError(
            503, "EMPTY_KNOWLEDGE_BASE", "This knowledge base has no ready documents yet."
        )

    (query_vector,) = embed_texts([request.message])

    try:
        answer, chunk_context = generation.answer_question(
            query_vector, request.message, knowledge_base_id=kb_id
        )
    except generation.LLMUnavailableError:
        raise ApiError(
            502,
            "LLM_UNAVAILABLE",
            "The answer service is temporarily unavailable. Please try again shortly.",
        ) from None

    sources = generation.build_sources(answer, chunk_context)
    return ChatResponse(answer=answer, sources=[SourceReference(**s) for s in sources])
