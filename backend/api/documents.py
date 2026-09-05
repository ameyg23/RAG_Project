import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Header, UploadFile

from errors import ApiError
from ingestion.pipeline import process_document
from models.schemas import (
    DeleteResponse,
    DocumentStatus,
    DocumentStatusResponse,
    UploadedDocumentSummary,
    UploadResponse,
)
from retrieval import vector_store
from store import (
    DEMO_KB_ID,
    create_document,
    delete_document,
    ensure_session_kb,
    get_document,
    get_or_create_session,
    session_owns_kb,
)

router = APIRouter()

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB, FR-011
MAX_FILE_COUNT = 5  # FR-010
SUPPORTED_EXTENSIONS = {"pdf", "docx", "txt", "md"}

# docs/DOCUMENT_PROCESSING.md: temp file paths are always
# {temp_dir}/{document_id}.{ext} - a pure function of the server-generated
# document_id and the already-validated extension, NEVER the raw/original
# filename (docs/SECURITY.md Path Traversal). Phase 14's background
# pipeline recomputes this same path to read the file back; nothing extra
# needs to be stored in the mock store.
UPLOAD_TEMP_DIR = Path(tempfile.gettempdir()) / "rag_chatbot_uploads"


def _extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def get_temp_upload_path(document_id: str, file_type: str) -> Path:
    UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_TEMP_DIR / f"{document_id}.{file_type}"


@router.post("/documents/upload", response_model=UploadResponse, status_code=202)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(default=[]),
    x_session_token: str | None = Header(default=None),
):
    if len(files) == 0:
        raise ApiError(400, "NO_FILES_PROVIDED", "At least one file must be provided.")
    if len(files) > MAX_FILE_COUNT:
        raise ApiError(
            400, "TOO_MANY_FILES", f"A maximum of {MAX_FILE_COUNT} files may be uploaded at once."
        )

    contents: list[bytes] = []
    for f in files:
        data = await f.read()
        contents.append(data)
        if len(data) > MAX_FILE_SIZE_BYTES:
            size_mb = len(data) / (1024 * 1024)
            raise ApiError(
                400,
                "FILE_TOO_LARGE",
                f'"{f.filename}" is {size_mb:.1f}MB; the limit is 5MB per file.',
            )

    for f in files:
        ext = _extension_of(f.filename or "")
        if ext not in SUPPORTED_EXTENSIONS:
            raise ApiError(
                400,
                "UNSUPPORTED_FILE_TYPE",
                f'"{f.filename}" has an unsupported file type. '
                f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.",
            )

    session_token = get_or_create_session(x_session_token)
    kb_id = ensure_session_kb(session_token)

    created = []
    for f, data in zip(files, contents, strict=True):
        ext = _extension_of(f.filename or "")
        doc = create_document(
            knowledge_base_id=kb_id,
            filename=f.filename or "unnamed",
            file_type=ext,
            size_bytes=len(data),
            status="UPLOADED",
        )
        # Server-generated path only - document_id and the already-validated
        # extension, never f.filename (docs/SECURITY.md Path Traversal).
        temp_path = get_temp_upload_path(doc["document_id"], ext)
        temp_path.write_bytes(data)
        background_tasks.add_task(
            process_document,
            doc["document_id"],
            temp_path,
            knowledge_base_id=kb_id,
            document_name=doc["filename"],
            file_type=ext,
        )
        created.append(
            UploadedDocumentSummary(
                document_id=doc["document_id"],
                filename=doc["filename"],
                status=DocumentStatus(doc["status"]),
            )
        )

    return UploadResponse(session_token=session_token, knowledge_base_id=kb_id, documents=created)


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
def document_status(document_id: str, x_session_token: str | None = Header(default=None)):
    doc = get_document(document_id)
    if doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "That document does not exist.")

    if doc["knowledge_base_id"] != DEMO_KB_ID:
        if not x_session_token or not session_owns_kb(x_session_token, doc["knowledge_base_id"]):
            raise ApiError(
                403, "FORBIDDEN_KNOWLEDGE_BASE", "You do not have access to this document."
            )

    return DocumentStatusResponse(
        document_id=doc["document_id"],
        status=DocumentStatus(doc["status"]),
        failure_reason=doc["failure_reason"],
    )


@router.delete("/documents/{document_id}", response_model=DeleteResponse)
def delete_document_route(document_id: str, x_session_token: str | None = Header(default=None)):
    doc = get_document(document_id)
    if doc is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "That document does not exist.")

    if doc["knowledge_base_id"] == DEMO_KB_ID:
        raise ApiError(403, "FORBIDDEN_KNOWLEDGE_BASE", "Demo documents cannot be deleted.")

    if not x_session_token or not session_owns_kb(x_session_token, doc["knowledge_base_id"]):
        raise ApiError(403, "FORBIDDEN_KNOWLEDGE_BASE", "You do not have access to this document.")

    # FR-015: deleting a document must remove its chunks from Qdrant, not
    # just the mock-store record - this was simply missing before.
    vector_store.delete_document(document_id, knowledge_base_id=doc["knowledge_base_id"])
    deleted = delete_document(document_id)
    return DeleteResponse(document_id=document_id, deleted=deleted)
