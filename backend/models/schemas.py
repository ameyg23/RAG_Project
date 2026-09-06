"""Pydantic request/response models matching docs/API.md exactly."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, field_validator


class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    session_token: str
    vector_store: Literal["connected", "unreachable"]


class KnowledgeBaseSummary(BaseModel):
    knowledge_base_id: str
    kind: Literal["demo", "user"]
    name: str
    document_count: int
    # Populated only for the demo KB, from backend/demo_content/suggested_questions.json
    # (FR-003) - empty for user KBs, since their content is arbitrary. Single
    # source of truth: the frontend never hardcodes a duplicate copy of these.
    suggested_questions: list[str] = []


class KnowledgeBasesResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseSummary]


class DocumentSummary(BaseModel):
    document_id: str
    filename: str
    file_type: Literal["pdf", "docx", "txt", "md"]
    size_bytes: int
    status: DocumentStatus
    failure_reason: str | None
    uploaded_at: datetime
    chunk_count: int


class DocumentsListResponse(BaseModel):
    knowledge_base_id: str
    documents: list[DocumentSummary]


class UploadedDocumentSummary(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus


class UploadResponse(BaseModel):
    session_token: str
    knowledge_base_id: str
    documents: list[UploadedDocumentSummary]


class DocumentStatusResponse(BaseModel):
    document_id: str
    status: DocumentStatus
    failure_reason: str | None


class DeleteResponse(BaseModel):
    document_id: str
    deleted: bool


class ConversationTurn(BaseModel):
    """One prior turn of `conversation_history` (ADR-16, docs/API.md).

    Deliberately narrower than the frontend's own ChatMessage shape
    (docs/DATA_MODEL.md §6) — only `role`/`content` are ever transmitted,
    never `sources`/`timestamp`.
    """

    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def content_must_be_within_limit(cls, v: str) -> str:
        # Mirrors ChatRequest.message's own cap below — defense-in-depth
        # (NFR-006): enforced regardless of what the frontend's own 3-exchange
        # convention already does, since a misbehaving/future client could
        # send arbitrarily long entries otherwise.
        if len(v) > 2000:
            raise ValueError("conversation_history entry content must be at most 2000 characters")
        return v


class ChatRequest(BaseModel):
    knowledge_base_id: str
    message: str
    # Optional, defaults to []: an empty/omitted list means "thread's first
    # message" and skips Stage 6.5 (query rewriting) entirely (ADR-16). Not
    # persisted anywhere server-side (docs/DATA_MODEL.md §6 amendment) — read
    # once per request by retrieval/query_rewrite.py and discarded.
    conversation_history: list[ConversationTurn] = []

    @field_validator("message")
    @classmethod
    def message_must_be_valid(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("message must not be empty")
        if len(stripped) > 2000:
            raise ValueError("message must be at most 2000 characters")
        return stripped

    @field_validator("conversation_history")
    @classmethod
    def conversation_history_must_be_within_limit(
        cls, v: list["ConversationTurn"]
    ) -> list["ConversationTurn"]:
        # Hard server-side cap (ADR-16), independent of the frontend's own
        # 3-exchange/6-entry convention — a client sending more must not blow
        # the rewrite-prompt's token budget (NFR-006).
        if len(v) > 8:
            raise ValueError("conversation_history must contain at most 8 entries")
        return v


class SourceReference(BaseModel):
    document_id: str
    document_name: str
    locator: str
    snippet: str
    is_removed: bool


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceReference]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
