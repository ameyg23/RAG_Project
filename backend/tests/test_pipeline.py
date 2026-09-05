from pathlib import Path
from unittest.mock import patch

import pytest

import store
from ingestion.pipeline import SAVE_FAILURE_MESSAGE, process_document


@pytest.fixture(autouse=True)
def _clean_store():
    store._documents.clear()
    yield
    store._documents.clear()


def _make_temp_txt_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "doc.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_upsert_retries_and_succeeds_on_transient_failure(tmp_path):
    # Reproduces the exact real-world failure observed live: a transient
    # connection blip to Qdrant on the first attempt(s), succeeding on a
    # later one - the document should still end up READY, not FAILED.
    doc = store.create_document(
        knowledge_base_id="kb_demo", filename="doc.txt", file_type="txt", size_bytes=10
    )
    temp_path = _make_temp_txt_file(tmp_path, "The launch code is ALPHA-NINE-NINE.")

    call_count = {"n": 0}

    def flaky_upsert(chunks, vectors):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise ConnectionError("simulated transient DNS/connection blip")

    with (
        patch("ingestion.pipeline.upsert_chunks", side_effect=flaky_upsert),
        patch("ingestion.pipeline.time.sleep"),  # don't actually wait in tests
    ):
        process_document(
            doc["document_id"],
            temp_path,
            knowledge_base_id="kb_demo",
            document_name="doc.txt",
            file_type="txt",
        )

    result = store.get_document(doc["document_id"])
    assert result["status"] == "READY"
    assert call_count["n"] == 2


def test_upsert_fails_permanently_after_max_attempts(tmp_path):
    doc = store.create_document(
        knowledge_base_id="kb_demo", filename="doc.txt", file_type="txt", size_bytes=10
    )
    temp_path = _make_temp_txt_file(tmp_path, "The launch code is ALPHA-NINE-NINE.")

    with (
        patch(
            "ingestion.pipeline.upsert_chunks",
            side_effect=ConnectionError("persistent failure"),
        ) as mock_upsert,
        patch("ingestion.pipeline.time.sleep"),
    ):
        process_document(
            doc["document_id"],
            temp_path,
            knowledge_base_id="kb_demo",
            document_name="doc.txt",
            file_type="txt",
        )

    result = store.get_document(doc["document_id"])
    assert result["status"] == "FAILED"
    assert result["failure_reason"] == SAVE_FAILURE_MESSAGE
    assert mock_upsert.call_count == 3
