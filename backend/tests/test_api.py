import json
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
from retrieval import generation, retriever, vector_store
from store import DEMO_DOCUMENT_FILES

client = TestClient(app)


def _ndjson_events(resp) -> list[dict]:
    """Parse a POST /chat NDJSON stream response (ADR-18) into its list of
    stage events, in order."""
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def _final_event(resp) -> dict:
    """The last event of a /chat NDJSON stream - COMPLETED or ERROR."""
    return _ndjson_events(resp)[-1]

DEMO_CONTENT = Path(__file__).parent.parent / "demo_content"
DEMO_FILES = DEMO_DOCUMENT_FILES


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


def test_health_degraded_when_vector_store_unreachable():
    mock_client = MagicMock()
    mock_client.collection_exists.side_effect = ConnectionError("simulated outage")
    vector_store.set_client(mock_client)

    resp = client.get("/health")

    assert resp.status_code == 200  # docs/API.md: degraded is signaled in the body, not via status
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["vector_store"] == "unreachable"
    assert body["session_token"]


def test_list_knowledge_bases_includes_demo():
    resp = client.get("/knowledge-bases")
    assert resp.status_code == 200
    ids = [kb["knowledge_base_id"] for kb in resp.json()["knowledge_bases"]]
    assert "kb_demo" in ids


def test_demo_kb_suggested_questions_match_source_file():
    import json
    from pathlib import Path

    expected = json.loads(
        (Path(__file__).parent.parent / "demo_content" / "suggested_questions.json").read_text()
    )
    resp = client.get("/knowledge-bases")
    demo = next(kb for kb in resp.json()["knowledge_bases"] if kb["knowledge_base_id"] == "kb_demo")
    assert demo["suggested_questions"] == [q["question"] for q in expected]


def test_user_kb_has_no_suggested_questions():
    files = [("files", ("s.txt", b"content", "text/plain"))]
    _upload(files, token="suggested-q-test")
    resp = client.get("/knowledge-bases", headers={"X-Session-Token": "suggested-q-test"})
    user_kb = next(kb for kb in resp.json()["knowledge_bases"] if kb["kind"] == "user")
    assert user_kb["suggested_questions"] == []


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
    # Phase 14: real background processing runs synchronously within
    # TestClient's request cycle, so by the time we poll status right
    # after upload, extraction/chunking/embedding/upsert has already
    # completed for this valid content - status is genuinely READY here,
    # not UPLOADED (which was only correct back when Phase 3 had no real
    # processing at all).
    files = [("files", ("c.txt", b"content", "text/plain"))]
    upload_resp = _upload(files, token="s6")
    document_id = upload_resp.json()["documents"][0]["document_id"]

    resp = client.get(f"/documents/{document_id}/status", headers={"X-Session-Token": "s6"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "READY"

    resp = client.get("/documents/nonexistent-id/status", headers={"X-Session-Token": "s6"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_document_status_for_real_demo_document_is_ready_not_404():
    # Phase 17 finding: a demo document is seeded offline and never passes
    # through create_document(), so the mock store has no record of it at
    # all - status previously misreported this as 404 DOCUMENT_NOT_FOUND
    # for a document that genuinely exists and is ready. No upload/token
    # needed - this is a real, publicly-known demo document_id.
    resp = client.get("/documents/01_employee_handbook/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "READY"
    assert body["failure_reason"] is None


def test_delete_document_happy_path_and_forbidden():
    files = [("files", ("d.txt", b"content", "text/plain"))]
    upload_resp = _upload(files, token="s7")
    document_id = upload_resp.json()["documents"][0]["document_id"]

    forbidden = client.delete(f"/documents/{document_id}", headers={"X-Session-Token": "not-s7"})
    assert forbidden.status_code == 403

    resp = client.delete(f"/documents/{document_id}", headers={"X-Session-Token": "s7"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_demo_document_returns_403_not_404():
    # Same Phase 17 finding as above, for DELETE - the documented behavior
    # (docs/API.md) is 403 "demo documents cannot be deleted", not a
    # misleading 404 "that document does not exist".
    resp = client.delete("/documents/02_product_faq")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_KNOWLEDGE_BASE"


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


@pytest.mark.live_groq
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
    events = _ndjson_events(resp)
    assert [e["stage"] for e in events] == [
        "SEARCHING",
        "RETRIEVING",
        "GENERATING",
        "VALIDATING",
        "COMPLETED",
    ]
    body = events[-1]
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
    body = _final_event(resp)
    assert body["stage"] == "COMPLETED"
    assert body["answer"] == generation.NO_CONTEXT_RESPONSE
    assert body["sources"] == []


def test_chat_streams_all_stages_in_order_for_successful_request():
    # ADR-18: SEARCHING -> RETRIEVING -> GENERATING -> VALIDATING ->
    # COMPLETED, in that exact order, with no stage skipped or reordered.
    _ingest_all_demo_content()

    mock_client = MagicMock()
    resp_obj = MagicMock()
    resp_obj.choices[0].message.content = "Full-time employees accrue 15 days of PTO per year [1]."
    mock_client.chat.completions.create.return_value = resp_obj
    generation.set_client(mock_client)

    resp = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": "How many vacation days do I get?"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    events = _ndjson_events(resp)
    assert [e["stage"] for e in events] == [
        "SEARCHING",
        "RETRIEVING",
        "GENERATING",
        "VALIDATING",
        "COMPLETED",
    ]
    assert events[-1]["answer"]
    assert events[-1]["sources"]


def test_chat_llm_failure_produces_llm_unavailable_error_event():
    # ADR-18: once the stream has opened (HTTP 200), a Groq failure can no
    # longer be signaled via a 502 status - it must be a terminal
    # {"stage": "ERROR", "code": "LLM_UNAVAILABLE", "retryable": true} event,
    # preceded by every stage event up to (and including) GENERATING.
    _ingest_all_demo_content()

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("simulated Groq outage")
    generation.set_client(mock_client)

    resp = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": "How many vacation days do I get?"},
    )

    assert resp.status_code == 200  # already 200 by the time Groq is called - can't change now
    events = _ndjson_events(resp)
    assert [e["stage"] for e in events[:3]] == ["SEARCHING", "RETRIEVING", "GENERATING"]
    final = events[-1]
    assert final["stage"] == "ERROR"
    assert final["code"] == "LLM_UNAVAILABLE"
    assert final["retryable"] is True
    assert "simulated Groq outage" not in final["message"]


def test_chat_vector_store_failure_produces_vector_store_unavailable_error_event(monkeypatch):
    # ADR-18/FR-055: a Qdrant failure during retrieval must be distinguished
    # from an LLM failure and marked retryable - this previously fell
    # through uncaught to a non-retryable INTERNAL_ERROR (the latent gap
    # this ADR closes).
    _ingest_all_demo_content()

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated Qdrant outage")

    monkeypatch.setattr(vector_store, "query", _boom)

    resp = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": "How many vacation days do I get?"},
    )

    assert resp.status_code == 200
    events = _ndjson_events(resp)
    assert events[0]["stage"] == "SEARCHING"
    final = events[-1]
    assert final["stage"] == "ERROR"
    assert final["code"] == "VECTOR_STORE_UNAVAILABLE"
    assert final["retryable"] is True
    assert "simulated Qdrant outage" not in final["message"]


def test_chat_marks_removed_document_but_never_a_demo_document(monkeypatch):
    # FR-042/ADR-18: simulates the real race this check exists for (a
    # document deleted concurrently with an in-flight chat request that
    # already retrieved chunks from it) by injecting a citation whose
    # document_id has zero chunks in this test's fresh vector store, without
    # needing actual thread concurrency. A real KB document is also uploaded
    # so the pre-stream EMPTY_KNOWLEDGE_BASE check still passes. A second
    # injected citation uses a real demo document_id (never ingested in this
    # fresh in-memory store, so its real chunk count is also 0) to prove the
    # store.is_demo_document_id exemption - not the count - is what keeps a
    # demo citation permanently non-removed.
    files = [("files", ("keepme.txt", b"unrelated content kept in the KB", "text/plain"))]
    token = "is-removed-test"
    upload_resp = _upload(files, token=token)
    kb_id = upload_resp.json()["knowledge_base_id"]

    ghost_chunk = retriever.RetrievedChunk(
        score=5.0,
        chunk_id="ghost_0",
        document_id="ghost-document-id",
        knowledge_base_id=kb_id,
        document_name="deleted.txt",
        chunk_index=0,
        page=None,
        text="This chunk's document has since been deleted from the vector store.",
    )
    demo_chunk = retriever.RetrievedChunk(
        score=4.0,
        chunk_id="01_employee_handbook_0",
        document_id="01_employee_handbook",
        knowledge_base_id=kb_id,
        document_name="01_employee_handbook.md",
        chunk_index=0,
        page=None,
        text="Demo content chunk - never actually ingested in this test's fresh Qdrant.",
    )
    monkeypatch.setattr(
        retriever, "apply_rerank_threshold", lambda chunks, **kw: [ghost_chunk, demo_chunk]
    )

    mock_client = MagicMock()
    resp_obj = MagicMock()
    resp_obj.choices[0].message.content = "According to the documents [1][2]."
    mock_client.chat.completions.create.return_value = resp_obj
    generation.set_client(mock_client)

    resp = client.post(
        "/chat",
        json={"knowledge_base_id": kb_id, "message": "anything"},
        headers={"X-Session-Token": token},
    )

    assert resp.status_code == 200
    final = _final_event(resp)
    assert final["stage"] == "COMPLETED"
    sources_by_document_id = {s["document_id"]: s["is_removed"] for s in final["sources"]}
    assert sources_by_document_id["ghost-document-id"] is True
    assert sources_by_document_id["01_employee_handbook"] is False


def test_upload_writes_file_to_temp_path_with_server_generated_name():
    # Phase 14 note: real background processing now reads this exact file
    # and deletes it once done (ADR-11), synchronously within TestClient's
    # request cycle - so we can no longer observe the file mid-flight.
    # Instead, successful processing (READY) is itself proof the file was
    # written to, and read from, the correct deterministic path: if the
    # path were wrong, extraction would raise FileNotFoundError and the
    # document would never reach READY.
    content = b"A real uploaded file's bytes, valid extractable text content."
    files = [("files", ("notes.txt", content, "text/plain"))]
    resp = _upload(files, token="temp-path-test")
    assert resp.status_code == 202
    document_id = resp.json()["documents"][0]["document_id"]

    status_resp = client.get(
        f"/documents/{document_id}/status", headers={"X-Session-Token": "temp-path-test"}
    )
    assert status_resp.json()["status"] == "READY"

    temp_path = get_temp_upload_path(document_id, "txt")
    assert not temp_path.exists()  # cleaned up after successful processing (ADR-11)


def test_upload_path_traversal_filename_is_neutralized():
    # The only place this file could legitimately land is the deterministic
    # server-generated path - never anywhere implied by the raw filename.
    # Reaching READY proves both the write and the read used that exact
    # path: get_temp_upload_path() takes only document_id/file_type and
    # structurally cannot see the raw filename, so if either side had
    # somehow used it instead, extraction would fail to find the file.
    content = b"Malicious-looking filename, ordinary real extractable text."
    files = [("files", ("../../../etc/evil.txt", content, "text/plain"))]
    resp = _upload(files, token="traversal-test")
    assert resp.status_code == 202
    document_id = resp.json()["documents"][0]["document_id"]

    status_resp = client.get(
        f"/documents/{document_id}/status", headers={"X-Session-Token": "traversal-test"}
    )
    assert status_resp.json()["status"] == "READY"

    expected_path = get_temp_upload_path(document_id, "txt")
    assert not expected_path.exists()  # cleaned up after successful processing (ADR-11)
    assert expected_path.parent == get_temp_upload_path("x", "txt").parent
    assert "evil" not in str(expected_path)
    assert ".." not in expected_path.parts


def test_upload_request_too_large_returns_413():
    resp = client.post(
        "/documents/upload",
        headers={"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)},
        content=b"x",  # body content is irrelevant - rejected on header alone
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "REQUEST_TOO_LARGE"


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.live_groq
def test_full_upload_process_ready_chat_delete_lifecycle():
    # Phase 14's actual Definition of Done: the complete real lifecycle,
    # not mocked at any stage. Content is real prose distinct enough that
    # a grounded answer must actually come from it.
    generation_module._client = None  # force a fresh real Groq client
    content = (
        b"The office mascot is a golden retriever named Biscuit who greets "
        b"every visitor at the front desk and has his own employee badge."
    )
    files = [("files", ("mascot.txt", content, "text/plain"))]
    token = "lifecycle-test"

    upload_resp = _upload(files, token=token)
    assert upload_resp.status_code == 202
    body = upload_resp.json()
    document_id = body["documents"][0]["document_id"]
    kb_id = body["knowledge_base_id"]
    assert body["documents"][0]["status"] == "UPLOADED"  # response predates background processing

    status_resp = client.get(
        f"/documents/{document_id}/status", headers={"X-Session-Token": token}
    )
    assert status_resp.json()["status"] == "READY"
    assert status_resp.json()["failure_reason"] is None
    assert vector_store.count_chunks_for_document(document_id, knowledge_base_id=kb_id) > 0

    chat_resp = client.post(
        "/chat",
        json={"knowledge_base_id": kb_id, "message": "What is the office mascot's name?"},
        headers={"X-Session-Token": token},
    )
    assert chat_resp.status_code == 200
    chat_body = _final_event(chat_resp)
    assert chat_body["stage"] == "COMPLETED"
    assert "Biscuit" in chat_body["answer"]
    assert chat_body["sources"]

    delete_resp = client.delete(f"/documents/{document_id}", headers={"X-Session-Token": token})
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True
    assert vector_store.count_chunks_for_document(document_id, knowledge_base_id=kb_id) == 0

    # The KB now has zero ready documents again - back to the empty-KB case.
    after_delete_resp = client.post(
        "/chat",
        json={"knowledge_base_id": kb_id, "message": "What is the office mascot's name?"},
        headers={"X-Session-Token": token},
    )
    assert after_delete_resp.status_code == 503
    assert after_delete_resp.json()["error"]["code"] == "EMPTY_KNOWLEDGE_BASE"


def test_upload_corrupted_file_ends_up_failed_with_correct_reason():
    corrupted_bytes = (FIXTURES / "corrupted.pdf").read_bytes()
    files = [("files", ("bad.pdf", corrupted_bytes, "application/pdf"))]
    token = "corrupted-test"

    upload_resp = _upload(files, token=token)
    assert upload_resp.status_code == 202
    document_id = upload_resp.json()["documents"][0]["document_id"]

    status_resp = client.get(
        f"/documents/{document_id}/status", headers={"X-Session-Token": token}
    )
    body = status_resp.json()
    assert body["status"] == "FAILED"
    assert body["failure_reason"] == (
        "This file could not be read. It may be corrupted or in an unexpected format."
    )

    temp_path = get_temp_upload_path(document_id, "pdf")
    assert not temp_path.exists()  # cleaned up even on failure (ADR-11)


def test_upload_empty_content_ends_up_failed_with_correct_reason():
    files = [("files", ("blank.md", b"   \n\n  ", "text/markdown"))]
    token = "empty-content-test"

    upload_resp = _upload(files, token=token)
    assert upload_resp.status_code == 202
    document_id = upload_resp.json()["documents"][0]["document_id"]

    status_resp = client.get(
        f"/documents/{document_id}/status", headers={"X-Session-Token": token}
    )
    body = status_resp.json()
    assert body["status"] == "FAILED"
    assert body["failure_reason"] == "No extractable text found (file may be a scanned image)."


def test_delete_removes_chunks_from_qdrant_structurally():
    content = b"This document exists only to prove delete really removes its chunks."
    files = [("files", ("deleteme.txt", content, "text/plain"))]
    token = "delete-structural-test"

    upload_resp = _upload(files, token=token)
    body = upload_resp.json()
    document_id = body["documents"][0]["document_id"]
    kb_id = body["knowledge_base_id"]

    assert vector_store.count_chunks_for_document(document_id, knowledge_base_id=kb_id) > 0

    client.delete(f"/documents/{document_id}", headers={"X-Session-Token": token})

    assert vector_store.count_chunks_for_document(document_id, knowledge_base_id=kb_id) == 0


@pytest.mark.live_groq
def test_kb_isolation_two_real_sessions_similar_content():
    # Phase 15: genuinely adversarial isolation test using the real
    # /documents/upload API (not synthetic DocumentChunk objects like the
    # existing vector_store/retriever isolation tests). Both sessions'
    # files share the same subject (vacation policy) with different
    # specific numbers - a broken filter could still "work" against
    # unrelated content, so this proves the filter itself does the work.
    content_a = (
        b"Vacation Policy: Acme employees accrue 15 days of paid time off per year, "
        b"credited monthly."
    )
    content_b = (
        b"Vacation Policy: Zenith employees accrue 22 days of paid time off per year, "
        b"credited monthly."
    )

    resp_a = _upload([("files", ("policy.txt", content_a, "text/plain"))], token="iso-session-a")
    resp_b = _upload([("files", ("policy.txt", content_b, "text/plain"))], token="iso-session-b")
    kb_a = resp_a.json()["knowledge_base_id"]
    kb_b = resp_b.json()["knowledge_base_id"]
    assert kb_a != kb_b

    question = "How many vacation days do employees accrue per year?"

    chat_a = client.post(
        "/chat",
        json={"knowledge_base_id": kb_a, "message": question},
        headers={"X-Session-Token": "iso-session-a"},
    )
    assert chat_a.status_code == 200
    answer_a = _final_event(chat_a)["answer"]
    assert "15" in answer_a
    assert "22" not in answer_a

    chat_b = client.post(
        "/chat",
        json={"knowledge_base_id": kb_b, "message": question},
        headers={"X-Session-Token": "iso-session-b"},
    )
    assert chat_b.status_code == 200
    answer_b = _final_event(chat_b)["answer"]
    assert "22" in answer_b
    assert "15" not in answer_b

    # Each session can still independently chat against the shared demo KB.
    _ingest_all_demo_content()
    demo_question = "Does Acme require two-factor authentication?"
    demo_chat_a = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": demo_question},
        headers={"X-Session-Token": "iso-session-a"},
    )
    demo_chat_b = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": demo_question},
        headers={"X-Session-Token": "iso-session-b"},
    )
    assert demo_chat_a.status_code == 200
    demo_answer_a = _final_event(demo_chat_a)["answer"]
    assert "2FA" in demo_answer_a or "two-factor" in demo_answer_a
    assert demo_chat_b.status_code == 200

    # Session A cannot see session B's documents (or vice versa).
    forbidden = client.get(
        f"/knowledge-bases/{kb_b}/documents", headers={"X-Session-Token": "iso-session-a"}
    )
    assert forbidden.status_code == 403
    forbidden_reverse = client.get(
        f"/knowledge-bases/{kb_a}/documents", headers={"X-Session-Token": "iso-session-b"}
    )
    assert forbidden_reverse.status_code == 403


def test_list_kb_documents_happy_path():
    files = [("files", ("listed.txt", b"some real content to list", "text/plain"))]
    upload_resp = _upload(files, token="list-docs-test")
    kb_id = upload_resp.json()["knowledge_base_id"]
    document_id = upload_resp.json()["documents"][0]["document_id"]

    resp = client.get(
        f"/knowledge-bases/{kb_id}/documents", headers={"X-Session-Token": "list-docs-test"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["knowledge_base_id"] == kb_id
    assert len(body["documents"]) == 1
    doc = body["documents"][0]
    assert doc["document_id"] == document_id
    assert doc["filename"] == "listed.txt"
    assert doc["status"] == "READY"
    assert doc["chunk_count"] > 0


def test_list_kb_documents_unknown_kb_404():
    resp = client.get("/knowledge-bases/kb_does_not_exist/documents")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"


def test_delete_unknown_document_404():
    resp = client.delete("/documents/nonexistent-id", headers={"X-Session-Token": "any-token"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_chat_forbidden_when_session_does_not_own_kb():
    files = [("files", ("private.txt", b"only owner-token should see this", "text/plain"))]
    upload_resp = _upload(files, token="chat-owner-token")
    kb_id = upload_resp.json()["knowledge_base_id"]

    resp = client.post(
        "/chat",
        json={"knowledge_base_id": kb_id, "message": "What does this document say?"},
        headers={"X-Session-Token": "some-other-token"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_KNOWLEDGE_BASE"


def test_chat_forbidden_when_no_session_token_provided_for_user_kb():
    files = [("files", ("private2.txt", b"content", "text/plain"))]
    upload_resp = _upload(files, token="chat-owner-token-2")
    kb_id = upload_resp.json()["knowledge_base_id"]

    resp = client.post("/chat", json={"knowledge_base_id": kb_id, "message": "anything"})

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_KNOWLEDGE_BASE"


@pytest.mark.live_groq
def test_e2e_explore_demo_ask_real_suggested_question():
    # docs/TEST_STRATEGY.md §4 scenario 1: land on the app (GET /health),
    # discover the demo KB's real suggested questions, ask one of the exact
    # published questions, and see a cited answer - the full "explore the
    # demo" journey, not synthetic pieces of it.
    generation_module._client = None
    _ingest_all_demo_content()

    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    token = health_resp.json()["session_token"]

    kb_resp = client.get("/knowledge-bases", headers={"X-Session-Token": token})
    demo_kb = next(
        kb for kb in kb_resp.json()["knowledge_bases"] if kb["knowledge_base_id"] == "kb_demo"
    )
    assert demo_kb["suggested_questions"]
    question = demo_kb["suggested_questions"][0]

    chat_resp = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": question},
        headers={"X-Session-Token": token},
    )

    assert chat_resp.status_code == 200
    body = _final_event(chat_resp)
    assert body["stage"] == "COMPLETED"
    assert body["answer"]
    assert body["answer"] != generation.NO_CONTEXT_RESPONSE
    assert body["sources"]


def test_e2e_recover_from_bad_upload_then_succeed():
    # docs/TEST_STRATEGY.md §4 scenario 4: a rejected oversized/wrong-type
    # upload, followed by a valid upload succeeding in the same session.
    token = "recover-from-bad-upload"

    oversized = _upload(
        [("files", ("big.bin", b"x" * (5 * 1024 * 1024 + 1), "application/octet-stream"))],
        token=token,
    )
    assert oversized.status_code == 400
    assert oversized.json()["error"]["code"] == "FILE_TOO_LARGE"

    wrong_type = _upload([("files", ("virus.exe", b"x", "application/octet-stream"))], token=token)
    assert wrong_type.status_code == 400
    assert wrong_type.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"

    valid = _upload(
        [("files", ("good.txt", b"perfectly valid extractable content", "text/plain"))],
        token=token,
    )
    assert valid.status_code == 202
    document_id = valid.json()["documents"][0]["document_id"]
    status_resp = client.get(
        f"/documents/{document_id}/status", headers={"X-Session-Token": token}
    )
    assert status_resp.json()["status"] == "READY"


def test_chat_empty_conversation_history_skips_rewrite_only_one_groq_call():
    # ADR-16: an omitted/empty conversation_history must skip Stage 6.5
    # entirely - a single Groq call (the generation call), not two.
    _ingest_all_demo_content()

    mock_client = MagicMock()
    resp_obj = MagicMock()
    resp_obj.choices[0].message.content = "Full-time employees accrue 15 days of PTO per year [1]."
    mock_client.chat.completions.create.return_value = resp_obj
    generation.set_client(mock_client)

    resp = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": "How many vacation days do I get?"},
    )

    assert resp.status_code == 200
    assert mock_client.chat.completions.create.call_count == 1


def test_chat_conversation_history_resolves_followup_and_flows_to_generation():
    # ADR-16 end-to-end (mocked Groq, real retrieval/rerank): a follow-up
    # question with history triggers two Groq calls (rewrite, then
    # generation), and the *rewritten* query - not the raw ambiguous
    # message - is what's fed as Stage 11's QUESTION:. Also confirms a
    # query-rewrite-triggering follow-up still streams every stage in order
    # (ADR-18) - the rewrite happens inside the SEARCHING stage's work, not
    # as a separate visible stage.
    _ingest_all_demo_content()

    mock_client = MagicMock()
    rewrite_resp = MagicMock()
    rewrite_resp.choices[0].message.content = (
        "How many days of PTO do full-time employees accrue per year?"
    )
    answer_resp = MagicMock()
    answer_resp.choices[0].message.content = (
        "Full-time employees accrue 15 days of PTO per year [1]."
    )
    mock_client.chat.completions.create.side_effect = [rewrite_resp, answer_resp]
    generation.set_client(mock_client)

    resp = client.post(
        "/chat",
        json={
            "knowledge_base_id": "kb_demo",
            "message": "What about their PTO?",
            "conversation_history": [
                {"role": "user", "content": "Tell me about the engineering team's benefits"},
                {
                    "role": "assistant",
                    "content": "Engineering employees get full health coverage [1].",
                },
            ],
        },
    )

    assert resp.status_code == 200
    events = _ndjson_events(resp)
    assert [e["stage"] for e in events] == [
        "SEARCHING",
        "RETRIEVING",
        "GENERATING",
        "VALIDATING",
        "COMPLETED",
    ]
    body = events[-1]
    assert "15" in body["answer"]
    assert body["sources"]

    assert mock_client.chat.completions.create.call_count == 2
    _, second_kwargs = mock_client.chat.completions.create.call_args_list[1]
    second_user_message = second_kwargs["messages"][-1]["content"]
    assert "How many days of PTO do full-time employees accrue per year?" in second_user_message
    assert "their PTO" not in second_user_message


def test_chat_conversation_history_over_cap_rejected():
    history = [{"role": "user", "content": f"turn {i}"} for i in range(9)]
    resp = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": "hi", "conversation_history": history},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_chat_conversation_history_entry_content_too_long_rejected():
    history = [{"role": "user", "content": "x" * 2001}]
    resp = client.post(
        "/chat",
        json={"knowledge_base_id": "kb_demo", "message": "hi", "conversation_history": history},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.live_groq
def test_chat_followup_question_real_groq_and_reranker():
    # Full real stack (no mocks): the manual-verification scenario from the
    # ADR-16/ADR-17 implementation pass, as an automated regression - an
    # ambiguous follow-up ("those days") must resolve against history and
    # come back with the correct, on-topic (rollover) answer, not a generic
    # or wrong one.
    generation_module._client = None
    _ingest_all_demo_content()

    initial_question = "How many days of PTO do full-time employees accrue per year?"
    initial = client.post(
        "/chat", json={"knowledge_base_id": "kb_demo", "message": initial_question}
    )
    assert initial.status_code == 200
    initial_answer = _final_event(initial)["answer"]
    assert "15" in initial_answer

    followup = client.post(
        "/chat",
        json={
            "knowledge_base_id": "kb_demo",
            "message": "How many of those days can roll over to the next year?",
            "conversation_history": [
                {"role": "user", "content": initial_question},
                {"role": "assistant", "content": initial_answer},
            ],
        },
    )

    assert followup.status_code == 200
    followup_body = _final_event(followup)
    assert "5" in followup_body["answer"]
    assert followup_body["sources"]


def test_no_server_side_chat_message_store_exists():
    # FR-023 architectural guarantee: there is no persistent chat-message
    # store anywhere in this codebase (ADR-12 - store.py is the single
    # source of truth for all mock persistence). A future accidental
    # addition of message/history persistence would break this test.
    import inspect

    import store
    from api import chat as chat_module

    store_function_names = [name for name in dir(store) if not name.startswith("_")]
    assert not any("message" in name.lower() for name in store_function_names)
    assert not any("history" in name.lower() for name in store_function_names)

    chat_source = inspect.getsource(chat_module)
    assert "save_message" not in chat_source
    assert "chat_history" not in chat_source
    assert "message_store" not in chat_source
