"""In-process store (ADR-12). Document/session metadata lives here; later
phases (13-15) extend this module — it is not throwaway scaffolding.
No relational database exists; Qdrant is the persistence layer for chunks
once ingestion (Phase 5+) lands.
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEMO_KB_ID = "kb_demo"

# POC idle-session cleanup (product decision, Phase 24-ish): a "Your
# Documents" session with no activity for this long is considered
# abandoned. The reaper (backend/main.py's lifespan task) sweeps every
# SESSION_SWEEP_INTERVAL_SECONDS and purges any session idle past this TTL -
# both its _sessions/_documents metadata here and its Qdrant vectors
# (retrieval/vector_store.py's delete_knowledge_base_vectors). This is a
# server-side safety net for a genuinely abandoned tab/crashed client, not
# the primary UX mechanism (the frontend no longer persists the session
# token across a refresh/close, so most browsers won't hold one that long
# anyway). Deliberately simple, round numbers - this is a POC, not a
# production deployment (explicit user decision: no real persistence layer,
# no per-session TTL tuning).
SESSION_IDLE_TTL_SECONDS = 30 * 60  # 30 minutes
SESSION_SWEEP_INTERVAL_SECONDS = 5 * 60  # 5 minutes

# Single source of truth for which files make up the demo KB - shared by
# backend/scripts/seed_demo_kb.py (what actually gets ingested) and
# backend/api/knowledge_bases.py (what the API reports as ingested), so the
# two can never drift apart. document_id for each is Path(filename).stem
# (e.g. "01_employee_handbook"), matching seed_demo_kb.py's convention.
DEMO_DOCUMENT_FILES = [
    "01_employee_handbook.md",
    "02_product_faq.md",
    "03_onboarding_guide.md",
    "04_security_policy.md",
]

_DEMO_DOCUMENT_IDS = {Path(f).stem for f in DEMO_DOCUMENT_FILES}


def is_demo_document_id(document_id: str) -> bool:
    """True for one of the 4 real demo document ids. These are seeded
    offline (backend/scripts/seed_demo_kb.py) and never pass through
    create_document(), so the mock store below has no record of them at
    all - callers that need to distinguish "unknown document" from "this
    is a real demo document you're not allowed to write to" must check
    this BEFORE falling back to get_document()'s None-means-404 behavior,
    or a demo document_id incorrectly looks indistinguishable from a
    nonexistent one."""
    return document_id in _DEMO_DOCUMENT_IDS


# Coarse module-level lock guarding every read-modify-write sequence below.
# Both normal request handling (FastAPI runs sync endpoints via
# run_in_threadpool - a real thread pool, not just async concurrency) and
# the idle-session reaper (an asyncio background task, itself run off the
# event loop via asyncio.to_thread) mutate _sessions/_documents, so without
# this lock a sweep and a concurrent request could corrupt either dict
# (e.g. "dictionary changed size during iteration", or a lost update). A
# single coarse lock is deliberately simple - this is a POC, fine-grained
# per-session locking is not warranted.
_lock = threading.Lock()

# session_token -> {"kb_id": str | None, "last_active_at": datetime}
# kb_id is None until the session's first upload (ensure_session_kb).
_sessions: dict[str, dict] = {}

# document_id -> {filename, file_type, size_bytes, status, failure_reason,
#                  uploaded_at, chunk_count, knowledge_base_id}
_documents: dict[str, dict] = {}


def issue_session_token() -> str:
    return uuid.uuid4().hex


def get_or_create_session(token: str | None) -> str:
    """Resolve a session token, refreshing its activity timestamp if it's
    already known. A provided-but-unknown token (never seen, or previously
    reaped by the idle-session sweep) is registered as a brand-new, empty
    session under that same token string - so a stale/reaped token is
    handled gracefully rather than erroring, exactly like a genuinely new
    token."""
    now = datetime.now(UTC)
    with _lock:
        if token and token in _sessions:
            _sessions[token]["last_active_at"] = now
            return token
        new_token = token if token else issue_session_token()
        _sessions[new_token] = {"kb_id": None, "last_active_at": now}
        return new_token


def touch_session_activity(token: str | None) -> None:
    """Refresh last_active_at for an already-known session. No-op for an
    absent or unknown token (e.g. an anonymous demo-KB-only request, or a
    token the reaper already swept) - there's no session to keep alive in
    that case, and get_or_create_session/ensure_session_kb re-register a
    stale token as a fresh session on its next write path anyway. Call
    this from every route that accepts X-Session-Token, so idle time is
    measured from real activity, not just session creation."""
    if not token:
        return
    with _lock:
        session = _sessions.get(token)
        if session is not None:
            session["last_active_at"] = datetime.now(UTC)


def derive_user_kb_id(session_token: str) -> str:
    return f"kb_user_{session_token}"


def session_owns_kb(session_token: str, kb_id: str) -> bool:
    """True if the session may READ kb_id. Never use this to authorize a
    write to DEMO_KB_ID — routes must hard-block demo-KB writes separately.
    """
    if kb_id == DEMO_KB_ID:
        return True
    with _lock:
        return kb_id == derive_user_kb_id(session_token) and session_token in _sessions


def known_kb_id(kb_id: str) -> bool:
    if kb_id == DEMO_KB_ID:
        return True
    with _lock:
        return any(derive_user_kb_id(token) == kb_id for token in _sessions)


def list_documents_for_kb(kb_id: str) -> list[dict]:
    with _lock:
        return [
            {"document_id": doc_id, **doc}
            for doc_id, doc in _documents.items()
            if doc["knowledge_base_id"] == kb_id
        ]


def get_document(document_id: str) -> dict | None:
    with _lock:
        doc = _documents.get(document_id)
        if doc is None:
            return None
        return {"document_id": document_id, **doc}


def create_document(
    knowledge_base_id: str,
    filename: str,
    file_type: str,
    size_bytes: int,
    status: str = "UPLOADED",
) -> dict:
    document_id = uuid.uuid4().hex
    record = {
        "filename": filename,
        "file_type": file_type,
        "size_bytes": size_bytes,
        "status": status,
        "failure_reason": None,
        "uploaded_at": datetime.now(UTC),
        "chunk_count": 0,
        "knowledge_base_id": knowledge_base_id,
    }
    with _lock:
        _documents[document_id] = record
    return {"document_id": document_id, **record}


def delete_document(document_id: str) -> bool:
    with _lock:
        if document_id in _documents:
            del _documents[document_id]
            return True
        return False


def update_document_status(
    document_id: str,
    *,
    status: str,
    failure_reason: str | None = None,
    chunk_count: int | None = None,
) -> None:
    """No-op if document_id isn't found - a document could theoretically be
    deleted concurrently with its own background processing finishing."""
    with _lock:
        doc = _documents.get(document_id)
        if doc is None:
            return
        doc["status"] = status
        if failure_reason is not None:
            doc["failure_reason"] = failure_reason
        if chunk_count is not None:
            doc["chunk_count"] = chunk_count


def ensure_session_kb(session_token: str) -> str:
    """Derive the session's user KB id and record ownership (first upload)."""
    kb_id = derive_user_kb_id(session_token)
    now = datetime.now(UTC)
    with _lock:
        existing = _sessions.get(session_token)
        _sessions[session_token] = {
            "kb_id": kb_id,
            "last_active_at": now if existing is None else existing["last_active_at"],
        }
        # First upload for this session is activity too - always refresh.
        _sessions[session_token]["last_active_at"] = now
    return kb_id


def get_idle_session_tokens(
    ttl_seconds: float = SESSION_IDLE_TTL_SECONDS, *, now: datetime | None = None
) -> list[str]:
    """Tokens whose last_active_at is older than ttl_seconds ago. Read-only:
    callers (the reaper in backend/main.py, or a test/manual script) must
    then call reap_session() for each token to actually remove it. `now`
    and `ttl_seconds` are overridable so a test can simulate expiry without
    waiting for real wall-clock time."""
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=ttl_seconds)
    with _lock:
        return [
            token for token, session in _sessions.items() if session["last_active_at"] < cutoff
        ]


def reap_session(token: str) -> str | None:
    """Remove one idle session's bookkeeping: its _sessions entry and every
    _documents record under its user KB. Returns the session's user
    knowledge_base_id if it had one (so the caller can also purge its
    Qdrant vectors via retrieval.vector_store.delete_knowledge_base_vectors),
    or None if the token was unknown or never uploaded anything (nothing
    else to clean up).

    NEVER removes DEMO_KB_ID's documents and can never be made to - the
    session's own recorded kb_id is always a kb_user_<token> string or
    None, structurally never DEMO_KB_ID (derive_user_kb_id always prefixes
    "kb_user_"), but the assertion below is kept as a defense-in-depth
    guard against this function ever being repurposed or miscalled: a bug
    here deleting the permanent demo content would be catastrophic and not
    easily recoverable (would require re-running scripts/seed_demo_kb.py).
    """
    with _lock:
        session = _sessions.pop(token, None)
        if session is None:
            return None
        kb_id = session["kb_id"]
        if kb_id is None:
            return None
        assert kb_id != DEMO_KB_ID, "reap_session must never target the permanent demo KB"
        stale_doc_ids = [
            doc_id for doc_id, doc in _documents.items() if doc["knowledge_base_id"] == kb_id
        ]
        for doc_id in stale_doc_ids:
            del _documents[doc_id]
        return kb_id
