"""FastAPI app entry point. Full route implementations land in Phase 3 (docs/API.md)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings

app = FastAPI(title="RAG Chatbot Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ALLOWED_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    # Placeholder for Phase 1 validation only. Phase 3 replaces this with the
    # full docs/API.md contract (session_token issuance, vector_store status).
    return {"status": "ok"}
