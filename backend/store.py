"""In-process store (ADR-12). Document/session metadata lives here; later
phases (13-15) extend this module — it is not throwaway scaffolding.
No relational database exists; Qdrant is the persistence layer for chunks
once ingestion (Phase 5+) lands.
"""

import uuid
from datetime import UTC, datetime

DEMO_KB_ID = "kb_demo"

# session_token -> owned user knowledge_base_id (None until first upload)
_sessions: dict[str, str | None] = {}

# document_id -> {filename, file_type, size_bytes, status, failure_reason,
#                  uploaded_at, chunk_count, knowledge_base_id}
_documents: dict[str, dict] = {}


def issue_session_token() -> str:
    return uuid.uuid4().hex


def get_or_create_session(token: str | None) -> str:
    if token and token in _sessions:
        return token
    new_token = token if token else issue_session_token()
    _sessions[new_token] = _sessions.get(new_token)
    return new_token


def derive_user_kb_id(session_token: str) -> str:
    return f"kb_user_{session_token}"


def session_owns_kb(session_token: str, kb_id: str) -> bool:
    """True if the session may READ kb_id. Never use this to authorize a
    write to DEMO_KB_ID — routes must hard-block demo-KB writes separately.
    """
    if kb_id == DEMO_KB_ID:
        return True
    return kb_id == derive_user_kb_id(session_token) and session_token in _sessions


def known_kb_id(kb_id: str) -> bool:
    if kb_id == DEMO_KB_ID:
        return True
    return any(derive_user_kb_id(token) == kb_id for token in _sessions)


def list_documents_for_kb(kb_id: str) -> list[dict]:
    return [
        {"document_id": doc_id, **doc}
        for doc_id, doc in _documents.items()
        if doc["knowledge_base_id"] == kb_id
    ]


def get_document(document_id: str) -> dict | None:
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
    _documents[document_id] = record
    return {"document_id": document_id, **record}


def delete_document(document_id: str) -> bool:
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
    _sessions[session_token] = kb_id
    return kb_id
