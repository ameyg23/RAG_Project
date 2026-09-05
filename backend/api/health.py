from fastapi import APIRouter, Header

from models.schemas import HealthResponse
from retrieval import vector_store
from store import get_or_create_session

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(x_session_token: str | None = Header(default=None)):
    session_token = get_or_create_session(x_session_token)
    if vector_store.is_reachable():
        return HealthResponse(status="ok", session_token=session_token, vector_store="connected")
    return HealthResponse(
        status="degraded", session_token=session_token, vector_store="unreachable"
    )
