import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Header

from errors import ApiError
from models.schemas import (
    DocumentsListResponse,
    DocumentStatus,
    DocumentSummary,
    KnowledgeBasesResponse,
    KnowledgeBaseSummary,
)
from retrieval import vector_store
from store import (
    DEMO_DOCUMENT_FILES,
    DEMO_KB_ID,
    derive_user_kb_id,
    known_kb_id,
    list_documents_for_kb,
    session_owns_kb,
)

router = APIRouter()

DEMO_CONTENT_DIR = Path(__file__).parent.parent / "demo_content"
SUGGESTED_QUESTIONS_PATH = DEMO_CONTENT_DIR / "suggested_questions.json"


@lru_cache(maxsize=1)
def _demo_suggested_questions() -> list[str]:
    """FR-003: 3-5 curated questions, single source of truth in
    backend/demo_content/suggested_questions.json - only the question text
    is exposed via the API, not the internal source_document/
    expected_answer_summary/verified_answerable fields used at authoring
    time (docs/PLANNING_REVIEW.md / Phase 4)."""
    data = json.loads(SUGGESTED_QUESTIONS_PATH.read_text(encoding="utf-8"))
    return [item["question"] for item in data]


def _demo_document_summaries() -> list[dict]:
    """Real ingested demo documents, derived from store.DEMO_DOCUMENT_FILES
    (the exact same list backend/scripts/seed_demo_kb.py ingests) plus real
    file stats and a real Qdrant chunk count per document. Fixes the Phase
    15 gap where this endpoint reported document_count: 0 for kb_demo
    forever, even after real seeding, because it read the in-process mock
    store instead - the mock store is per-process memory (ADR-12) and the
    seed script is a separate offline process, so it was structurally
    never going to be populated that way.

    Every demo document is reported READY: it's only in this list because
    it's a file this project committed and seeds - if seeding somehow left
    one with zero chunks, chunk_count reports that honestly rather than
    silently claiming a nonzero-content status.
    """
    summaries = []
    for filename in DEMO_DOCUMENT_FILES:
        path = DEMO_CONTENT_DIR / filename
        if not path.exists():
            continue
        document_id = path.stem
        stat = path.stat()
        chunk_count = vector_store.count_chunks_for_document(
            document_id, knowledge_base_id=DEMO_KB_ID
        )
        summaries.append(
            {
                "document_id": document_id,
                "filename": filename,
                "file_type": path.suffix.lstrip("."),
                "size_bytes": stat.st_size,
                "status": "READY",
                "failure_reason": None,
                "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                "chunk_count": chunk_count,
            }
        )
    return summaries


@router.get("/knowledge-bases", response_model=KnowledgeBasesResponse)
def list_knowledge_bases(x_session_token: str | None = Header(default=None)):
    demo = KnowledgeBaseSummary(
        knowledge_base_id=DEMO_KB_ID,
        kind="demo",
        name="Demo: Sample Knowledge Base",
        document_count=len(_demo_document_summaries()),
        suggested_questions=_demo_suggested_questions(),
    )
    kbs = [demo]

    if x_session_token:
        user_kb_id = derive_user_kb_id(x_session_token)
        user_docs = list_documents_for_kb(user_kb_id)
        if user_docs:
            kbs.append(
                KnowledgeBaseSummary(
                    knowledge_base_id=user_kb_id,
                    kind="user",
                    name="Your documents",
                    document_count=len(user_docs),
                )
            )

    return KnowledgeBasesResponse(knowledge_bases=kbs)


@router.get("/knowledge-bases/{knowledge_base_id}/documents", response_model=DocumentsListResponse)
def list_kb_documents(knowledge_base_id: str, x_session_token: str | None = Header(default=None)):
    if not known_kb_id(knowledge_base_id):
        raise ApiError(404, "KNOWLEDGE_BASE_NOT_FOUND", "That knowledge base does not exist.")

    if knowledge_base_id != DEMO_KB_ID:
        if not x_session_token or not session_owns_kb(x_session_token, knowledge_base_id):
            raise ApiError(
                403, "FORBIDDEN_KNOWLEDGE_BASE", "You do not have access to this knowledge base."
            )

    raw_docs = (
        _demo_document_summaries()
        if knowledge_base_id == DEMO_KB_ID
        else list_documents_for_kb(knowledge_base_id)
    )
    docs = [
        DocumentSummary(
            document_id=d["document_id"],
            filename=d["filename"],
            file_type=d["file_type"],
            size_bytes=d["size_bytes"],
            status=DocumentStatus(d["status"]),
            failure_reason=d["failure_reason"],
            uploaded_at=d["uploaded_at"],
            chunk_count=d["chunk_count"],
        )
        for d in raw_docs
    ]
    return DocumentsListResponse(knowledge_base_id=knowledge_base_id, documents=docs)
