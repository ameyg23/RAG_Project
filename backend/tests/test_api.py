from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


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
