"""Phase 14: BackgroundTasks orchestration (ADR-13) - wires Phases 5-8's
extract/chunk/embed/upsert into the document lifecycle state machine
(docs/DOCUMENT_PROCESSING.md).

No import dependency on api/documents.py - the caller (documents.py)
computes the temp file path itself (get_temp_upload_path) and passes it
in directly, avoiding a circular import.
"""

import logging
from pathlib import Path

from ingestion.chunk import chunk_document
from ingestion.embed import embed_texts
from ingestion.extract import CorruptedDocumentError, EmptyDocumentError, extract_and_clean
from retrieval.vector_store import upsert_chunks
from store import update_document_status

logger = logging.getLogger("backend")

CORRUPTED_DOCUMENT_MESSAGE = (
    "This file could not be read. It may be corrupted or in an unexpected format."
)
SAVE_FAILURE_MESSAGE = (
    "The document was processed but could not be saved. Please try uploading again."
)


def process_document(
    document_id: str,
    temp_path: Path,
    *,
    knowledge_base_id: str,
    document_name: str,
    file_type: str,
) -> None:
    update_document_status(document_id, status="PROCESSING")

    try:
        try:
            units = extract_and_clean(str(temp_path), file_type)
        except EmptyDocumentError as exc:
            # The exception's own message already carries the exact
            # docs/DOCUMENT_PROCESSING.md string - reuse it, don't duplicate.
            update_document_status(document_id, status="FAILED", failure_reason=str(exc))
            return
        except CorruptedDocumentError:
            logger.exception("Extraction failed for document %s", document_id)
            update_document_status(
                document_id, status="FAILED", failure_reason=CORRUPTED_DOCUMENT_MESSAGE
            )
            return

        chunks = chunk_document(
            units,
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            document_name=document_name,
        )
        vectors = embed_texts([c.text for c in chunks])

        try:
            upsert_chunks(chunks, vectors)
        except Exception:
            logger.exception("Vector store write failed for document %s", document_id)
            update_document_status(
                document_id, status="FAILED", failure_reason=SAVE_FAILURE_MESSAGE
            )
            return

        update_document_status(document_id, status="READY", chunk_count=len(chunks))
    finally:
        # ADR-11: raw uploaded files are transient - deleted once ingestion
        # completes OR fails, regardless of which path above was taken.
        temp_path.unlink(missing_ok=True)
