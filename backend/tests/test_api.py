from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

import retrieval.generation as generation_module
from api.documents import get_temp_upload_path
from ingestion.chunk import chunk_document
from ingestion.embed import embed_texts
from ingestion.extract import extract_and_clean
from main import MAX_REQUEST_BODY_BYTES, app
from retrieval import generation, vector_store

client = TestClient(app)

DEMO_CONTENT = Path(__file__).parent.parent / "demo_content"
DEMO_FILES = [
    "01_employee_handbook.md",
    "02_product_faq.md",
    "03_onboarding_guide.md",
    "04_security_policy.md",
]


@pytest.fixture(autouse=True)
def fresh_in_memory_qdrant():
    """Every test gets its own isolated in-memory Qdrant instance — without
    this, vector_store.get_client() falls back to the real Qdrant Cloud
    cluster now that QDRANT_URL is configured, which is slow and
    non-hermetic for tests that don't need it."""
    vector_store.set_client(QdrantClient(":memory:"))
    yield


def _ingest_all_demo_content(knowledge_base_id="kb_demo"):
    for i, filename in enumerate(DEMO_FILES):
        units = extract_and_clean(str(DEMO_CONTENT / filename), "md")
        chunks = chunk_document(
            units,
            document_id=f"doc-{i}",
            knowledge_base_id=knowledge_base_id,
            document_name=filename,
        )
        vectors = embed_texts([c.text for c in chunks])
        vector_store.upsert_chunks(chunks, vectors)


def _upload(files, token=None):
    headers = {"X-Session-Token": token} if token else {}
    return client.post("/documents/upload", files=files, headers=headers)


def test_health_happy_path():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["session_token"]


def test_list_knowledge_bases_includes_demo():
    resp = client.get("/knowledge-bases")
    assert resp.status_code == 200
    ids = [kb["knowledge_base_id"] for kb in resp.json()["knowledge_bases"]]
    assert "kb_demo" in ids


def test_upload_happy_path():
    files = [
        ("files", ("a.txt", b"hello world", "text/plain")),
        ("files", ("b.md", b"# heading", "text/markdown")),
    ]
    resp = _upload(files, token="test-session-1")
    assert resp.status_code == 202
    body = resp.json()
    assert body["knowledge_base_id"] == "kb_user_test-session-1"
    assert len(body["documents"]) == 2
    assert all(d["status"] == "UPLOADED" for d in body["documents"])


def test_upload_no_files():
    resp = client.post("/documents/upload", files=[], headers={"X-Session-Token": "s2"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "NO_FILES_PROVIDED"


def test_upload_too_many_files():
    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(6)]
    resp = _upload(files, token="s3")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "TOO_MANY_FILES"


def test_upload_file_too_large():
    big = b"x" * (5 * 1024 * 1024 + 1)
    files = [("files", ("big.txt", big, "text/plain"))]
    resp = _upload(files, token="s4")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_upload_unsupported_type():
    files = [("files", ("virus.exe", b"x", "application/octet-stream"))]
    resp = _upload(files, token="s5")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_document_status_happy_path_and_404():
    files = [("files", ("c.txt", b"content", "text/plain"))]
    upload_resp = _upload(files, token="s6")
    document_id = upload_resp.json()["documents"][0]["document_id"]

    resp = client.get(f"/documents/{document_id}/status", headers={"X-Session-Token": "s6"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "UPLOADED"

    resp = client.get("/documents/nonexistent-id/status", headers={"X-Session-Token": "s6"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_delete_document_happy_path_and_forbidden():
    files = [("files", ("d.txt", b"content", "text/plain"))]
    upload_resp = _upload(files, token="s7")
    document_id = upload_resp.json()["documents"][0]["document_id"]

    forbidden = client.delete(f"/documents/{document_id}", headers={"X-Session-Token": "not-s7"})
    assert forbidden.status_code == 403

    resp = client.delete(f"/documents/{document_id}", headers={"X-Session-Token": "s7"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_chat_against_empty_demo_kb():
    resp = client.post("/chat", json={"knowledge_base_id": "kb_demo", "message": "hello?"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "EMPTY_KNOWLEDGE_BASE"


def test_chat_against_unknown_kb():
    resp = client.post("/chat", json={"knowledge_base_id": "kb_nope", "message": "hello?"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"


def test_chat_empty_message_validation_error():
    resp = client.post("/chat", json={"knowledge_base_id": "kb_demo", "message": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_chat_grounded_answer_real_content_real_groq():
    # Real end-to-end through the actual API: real demo content ingested,
    # a real question, a real (unmocked) Groq call — consistent with how
    # Phases 10-11 validated real behavior, not just mocks.
    generation_module._client = None  # force a fresh real Groq client
    _ingest_all_demo_content()

    resp = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": "How many vacation days do I get?"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert "15" in body["answer"]
    assert body["sources"]
    assert any(s["document_name"] == "01_employee_handbook.md" for s in body["sources"])
    assert all(s["is_removed"] is False for s in body["sources"])


def test_chat_no_context_question_real_api():
    _ingest_all_demo_content()

    resp = client.post(
        "/chat", json={"knowledge_base_id": "kb_demo", "message": "What is the capital of France?"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == generation.NO_CONTEXT_RESPONSE
    assert body["sources"] == []


def test_chat_llm_failure_maps_to_502():
    _ingest_all_demo_content()

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("simulated Groq outage")
    generation.set_client(mock_client)

    resp = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": "How many vacation days do I get?"},
    )

    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "LLM_UNAVAILABLE"
    assert "simulated Groq outage" not in body["error"]["message"]


def test_upload_writes_file_to_temp_path_with_server_generated_name():
    content = b"a real uploaded file's bytes"
    files = [("files", ("notes.txt", content, "text/plain"))]
    resp = _upload(files, token="temp-path-test")
    assert resp.status_code == 202
    document_id = resp.json()["documents"][0]["document_id"]

    temp_path = get_temp_upload_path(document_id, "txt")
    try:
        assert temp_path.exists()
        assert temp_path.read_bytes() == content
    finally:
        temp_path.unlink(missing_ok=True)


def test_upload_path_traversal_filename_is_neutralized():
    content = b"malicious-looking filename, ordinary content"
    files = [("files", ("../../../etc/evil.txt", content, "text/plain"))]
    resp = _upload(files, token="traversal-test")
    assert resp.status_code == 202
    document_id = resp.json()["documents"][0]["document_id"]

    # The only place this file could legitimately land is the deterministic
    # server-generated path - never anywhere implied by the raw filename.
    expected_path = get_temp_upload_path(document_id, "txt")
    try:
        assert expected_path.exists()
        assert expected_path.read_bytes() == content
        assert expected_path.parent == get_temp_upload_path("x", "txt").parent
        assert "evil" not in str(expected_path)
        assert ".." not in expected_path.parts
    finally:
        expected_path.unlink(missing_ok=True)


def test_upload_request_too_large_returns_413():
    resp = client.post(
        "/documents/upload",
        headers={"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)},
        content=b"x",  # body content is irrelevant - rejected on header alone
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "REQUEST_TOO_LARGE"
