"""Phase 14: BackgroundTasks orchestration (ADR-13) - wires Phases 5-8's
extract/chunk/embed/upsert into the document lifecycle state machine
(docs/DOCUMENT_PROCESSING.md).

No import dependency on api/documents.py - the caller (documents.py)
computes the temp file path itself (get_temp_upload_path) and passes it
in directly, avoiding a circular import.
"""

import logging
import time
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

# Transient network/DNS blips connecting to Qdrant Cloud have been observed
# repeatedly throughout this project's development (always resolving on an
# immediate retry) - this is a short, local retry around a single already-
# running background attempt, not the "no automatic retry of a FAILED
# document" policy from docs/DOCUMENT_PROCESSING.md, which is about not
# re-attempting a document that has already reached FAILED, later, without
# the user re-uploading. A one-off connection hiccup within the same
# attempt is a different, narrower problem worth smoothing over here.
UPSERT_MAX_ATTEMPTS = 3
UPSERT_RETRY_DELAY_SECONDS = 2


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

        last_exc = None
        for attempt in range(1, UPSERT_MAX_ATTEMPTS + 1):
            try:
                upsert_chunks(chunks, vectors)
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 - broad by design, see module docstring
                last_exc = exc
                logger.warning(
                    "Vector store write attempt %d/%d failed for document %s: %s",
                    attempt,
                    UPSERT_MAX_ATTEMPTS,
                    document_id,
                    exc,
                )
                if attempt < UPSERT_MAX_ATTEMPTS:
                    time.sleep(UPSERT_RETRY_DELAY_SECONDS)

        if last_exc is not None:
            logger.exception(
                "Vector store write failed for document %s after %d attempts",
                document_id,
                UPSERT_MAX_ATTEMPTS,
                exc_info=last_exc,
            )
            update_document_status(
                document_id, status="FAILED", failure_reason=SAVE_FAILURE_MESSAGE
            )
            return

        update_document_status(document_id, status="READY", chunk_count=len(chunks))
    finally:
        # ADR-11: raw uploaded files are transient - deleted once ingestion
        # completes OR fails, regardless of which path above was taken.
        temp_path.unlink(missing_ok=True)
