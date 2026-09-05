"""docs/TEST_STRATEGY.md §1: one test per request/response model in
docs/API.md, covering both valid and invalid payload shapes."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from models.schemas import (
    ChatRequest,
    ChatResponse,
    DeleteResponse,
    DocumentsListResponse,
    DocumentStatus,
    DocumentStatusResponse,
    DocumentSummary,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    KnowledgeBasesResponse,
    KnowledgeBaseSummary,
    SourceReference,
    UploadedDocumentSummary,
    UploadResponse,
)


def test_health_response_valid():
    resp = HealthResponse(status="ok", session_token="t1", vector_store="connected")
    assert resp.status == "ok"


def test_health_response_invalid_status_literal():
    with pytest.raises(ValidationError):
        HealthResponse(status="totally-fine", session_token="t1", vector_store="connected")


def test_health_response_invalid_vector_store_literal():
    with pytest.raises(ValidationError):
        HealthResponse(status="ok", session_token="t1", vector_store="probably-connected")


def test_knowledge_base_summary_valid_defaults_empty_suggested_questions():
    kb = KnowledgeBaseSummary(
        knowledge_base_id="kb_demo", kind="demo", name="Demo", document_count=4
    )
    assert kb.suggested_questions == []


def test_knowledge_base_summary_invalid_kind_literal():
    with pytest.raises(ValidationError):
        KnowledgeBaseSummary(
            knowledge_base_id="kb_x", kind="shared", name="X", document_count=0
        )


def test_knowledge_bases_response_valid():
    resp = KnowledgeBasesResponse(
        knowledge_bases=[
            KnowledgeBaseSummary(
                knowledge_base_id="kb_demo", kind="demo", name="Demo", document_count=1
            )
        ]
    )
    assert len(resp.knowledge_bases) == 1


def test_document_summary_valid():
    doc = DocumentSummary(
        document_id="d1",
        filename="a.txt",
        file_type="txt",
        size_bytes=10,
        status=DocumentStatus.READY,
        failure_reason=None,
        uploaded_at=datetime.now(UTC),
        chunk_count=3,
    )
    assert doc.status == DocumentStatus.READY


def test_document_summary_invalid_file_type_literal():
    with pytest.raises(ValidationError):
        DocumentSummary(
            document_id="d1",
            filename="a.exe",
            file_type="exe",
            size_bytes=10,
            status=DocumentStatus.READY,
            failure_reason=None,
            uploaded_at=datetime.now(UTC),
            chunk_count=0,
        )


def test_document_summary_invalid_status_enum():
    with pytest.raises(ValidationError):
        DocumentSummary(
            document_id="d1",
            filename="a.txt",
            file_type="txt",
            size_bytes=10,
            status="ARCHIVED",
            failure_reason=None,
            uploaded_at=datetime.now(UTC),
            chunk_count=0,
        )


def test_documents_list_response_valid():
    resp = DocumentsListResponse(knowledge_base_id="kb_demo", documents=[])
    assert resp.documents == []


def test_uploaded_document_summary_valid():
    doc = UploadedDocumentSummary(
        document_id="d1", filename="a.txt", status=DocumentStatus.UPLOADED
    )
    assert doc.status == DocumentStatus.UPLOADED


def test_upload_response_valid():
    resp = UploadResponse(
        session_token="t1",
        knowledge_base_id="kb_user_t1",
        documents=[
            UploadedDocumentSummary(
                document_id="d1", filename="a.txt", status=DocumentStatus.UPLOADED
            )
        ],
    )
    assert len(resp.documents) == 1


def test_document_status_response_valid():
    resp = DocumentStatusResponse(
        document_id="d1", status=DocumentStatus.FAILED, failure_reason="corrupted"
    )
    assert resp.status == DocumentStatus.FAILED


def test_document_status_response_missing_required_field():
    with pytest.raises(ValidationError):
        DocumentStatusResponse(document_id="d1", status=DocumentStatus.READY)


def test_delete_response_valid():
    resp = DeleteResponse(document_id="d1", deleted=True)
    assert resp.deleted is True


def test_chat_request_valid():
    req = ChatRequest(knowledge_base_id="kb_demo", message="How many PTO days do I get?")
    assert req.message == "How many PTO days do I get?"


def test_chat_request_strips_whitespace():
    req = ChatRequest(knowledge_base_id="kb_demo", message="  padded question?  ")
    assert req.message == "padded question?"


def test_chat_request_empty_message_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(knowledge_base_id="kb_demo", message="   ")


def test_chat_request_too_long_message_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(knowledge_base_id="kb_demo", message="x" * 2001)


def test_chat_request_at_max_length_accepted():
    req = ChatRequest(knowledge_base_id="kb_demo", message="x" * 2000)
    assert len(req.message) == 2000


def test_source_reference_valid():
    src = SourceReference(
        document_id="d1",
        document_name="a.txt",
        locator="chunk 0",
        snippet="some text",
        is_removed=False,
    )
    assert src.is_removed is False


def test_chat_response_valid_empty_sources():
    resp = ChatResponse(answer="I don't have enough information.", sources=[])
    assert resp.sources == []


def test_error_detail_valid():
    detail = ErrorDetail(code="NOT_FOUND", message="missing")
    assert detail.code == "NOT_FOUND"


def test_error_response_valid():
    resp = ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message="missing"))
    assert resp.error.code == "NOT_FOUND"


def test_error_response_missing_error_field_rejected():
    with pytest.raises(ValidationError):
        ErrorResponse()
