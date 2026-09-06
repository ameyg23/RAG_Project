"""FastAPI app entry point. Route implementations: docs/API.md; error
shape: docs/API.md / docs/SECURITY.md (Error Leakage)."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import chat, documents, health, knowledge_bases
from config import settings
from errors import ApiError
from retrieval import vector_store
from store import (
    DEMO_KB_ID,
    SESSION_IDLE_TTL_SECONDS,
    SESSION_SWEEP_INTERVAL_SECONDS,
    get_idle_session_tokens,
    reap_session,
)

logger = logging.getLogger("backend")


def _sweep_idle_sessions() -> None:
    """One idle-session reaper pass (product decision: abandoned "Your
    Documents" data must not accumulate forever - POC scope, see
    store.py's SESSION_IDLE_TTL_SECONDS comment). Synchronous by design -
    every call here (store.py's dict ops, Qdrant) is blocking - so this
    must always be invoked via asyncio.to_thread from the async reaper
    loop, the same way FastAPI's own run_in_threadpool keeps sync route
    handlers off the event loop.
    """
    for token in get_idle_session_tokens(SESSION_IDLE_TTL_SECONDS):
        kb_id = reap_session(token)
        if kb_id is None:
            continue  # session never uploaded anything - nothing else to clean up
        if kb_id == DEMO_KB_ID:
            # Structurally impossible - reap_session asserts this itself -
            # but never risk the permanent demo KB on a bug here.
            logger.error("Idle-session reaper refused to delete vectors for the demo KB.")
            continue
        try:
            vector_store.delete_knowledge_base_vectors(kb_id)
        except Exception:
            logger.exception("Failed to delete Qdrant vectors for reaped KB %s", kb_id)


async def _idle_session_reaper_loop() -> None:
    while True:
        await asyncio.sleep(SESSION_SWEEP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(_sweep_idle_sessions)
        except Exception:
            logger.exception("Idle-session reaper sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    reaper_task = asyncio.create_task(_idle_session_reaper_loop())
    try:
        yield
    finally:
        reaper_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reaper_task


app = FastAPI(title="RAG Chatbot Backend", lifespan=lifespan)

# Defense-in-depth beyond the per-file 5MB check (docs/API.md, docs/SECURITY.md
# Excessive File Size): rejects an oversized request based on the
# Content-Length header alone, before the body is ever read into memory.
# 30MB covers 5 files x 5MB plus multipart boundary/header overhead.
MAX_REQUEST_BODY_BYTES = 30 * 1024 * 1024


class MaxBodySizeMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            content_length = headers.get(b"content-length")
            if content_length is not None:
                try:
                    length = int(content_length)
                except ValueError:
                    length = 0
                if length > self.max_bytes:
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "REQUEST_TOO_LARGE",
                                "message": "The request body is too large.",
                            }
                        },
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


app.add_middleware(MaxBodySizeMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ALLOWED_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(knowledge_bases.router)
app.include_router(documents.router)
app.include_router(chat.router)


@app.exception_handler(ApiError)
def handle_api_error(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, exc: RequestValidationError):
    logger.info("Validation error on %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "The request was invalid. Please check the submitted data.",
            }
        },
    )


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred. Please try again shortly.",
            }
        },
    )
