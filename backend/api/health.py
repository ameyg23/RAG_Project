from fastapi import APIRouter, Header

from models.schemas import HealthResponse
from store import get_or_create_session

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(x_session_token: str | None = Header(default=None)):
    session_token = get_or_create_session(x_session_token)
    # Mock store only in Phase 3 — real Qdrant connectivity check lands in
    # Phase 8 when retrieval/vector_store.py exists.
    return HealthResponse(status="ok", session_token=session_token, vector_store="connected")
