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


class ChatRequest(BaseModel):
    knowledge_base_id: str
    message: str

    @field_validator("message")
    @classmethod
    def message_must_be_valid(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("message must not be empty")
        if len(stripped) > 2000:
            raise ValueError("message must be at most 2000 characters")
        return stripped


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
