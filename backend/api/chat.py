from fastapi import APIRouter, Header

from errors import ApiError
from models.schemas import ChatRequest, ChatResponse
from store import DEMO_KB_ID, known_kb_id, list_documents_for_kb, session_owns_kb

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

    # Real retrieval + generation is Phases 5-12 (docs/RAG_PIPELINE.md); no
    # ingestion pipeline exists yet, so no document can ever be READY —
    # this always raises 503 in Phase 3, which is honest stub behavior.
    ready_docs = [d for d in list_documents_for_kb(kb_id) if d["status"] == "READY"]
    if not ready_docs:
        raise ApiError(
            503, "EMPTY_KNOWLEDGE_BASE", "This knowledge base has no ready documents yet."
        )

    raise NotImplementedError("Unreachable in Phase 3 — no document can be READY yet.")
