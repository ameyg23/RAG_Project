"""Idle-session cleanup for "Your Documents" data (POC product decision):
a session with no activity for SESSION_IDLE_TTL_SECONDS is considered
abandoned and its per-session metadata (store.py) and Qdrant vectors
(retrieval/vector_store.py) must be purged - but the permanent Demo KB
must never be touched by any of this, no matter what.

Every test in this file monkeypatches store._sessions/_documents to a
fresh dict, since those are shared module-level state with every other
test file in this suite (no reset fixture exists project-wide) - without
this isolation, a TTL=0 sweep here would also reap sessions created by
test_api.py et al.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from qdrant_client import QdrantClient

import store
from ingestion.chunk import DocumentChunk
from retrieval import vector_store


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch):
    monkeypatch.setattr(store, "_sessions", {})
    monkeypatch.setattr(store, "_documents", {})
    yield


@pytest.fixture(autouse=True)
def fresh_in_memory_qdrant():
    vector_store.set_client(QdrantClient(":memory:"))
    yield


def _upsert_one_chunk(kb_id: str, document_id: str = "doc-1") -> None:
    chunk = DocumentChunk(
        chunk_id=f"{document_id}_0",
        document_id=document_id,
        knowledge_base_id=kb_id,
        document_name="f.txt",
        chunk_index=0,
        page=None,
        text="some real content",
    )
    vector_store.upsert_chunks([chunk], [[0.01] * 384])


def test_get_or_create_session_sets_last_active_at():
    token = store.get_or_create_session("token-a")
    session = store._sessions[token]
    assert isinstance(session["last_active_at"], datetime)
    assert session["kb_id"] is None


def test_touch_session_activity_refreshes_timestamp():
    token = store.get_or_create_session("token-b")
    old_time = datetime.now(UTC) - timedelta(hours=1)
    store._sessions[token]["last_active_at"] = old_time

    store.touch_session_activity(token)

    assert store._sessions[token]["last_active_at"] > old_time


def test_touch_session_activity_noop_for_unknown_or_missing_token():
    # Must not raise and must not fabricate a session entry.
    store.touch_session_activity(None)
    store.touch_session_activity("never-seen-token")
    assert "never-seen-token" not in store._sessions


def test_ensure_session_kb_also_counts_as_activity():
    token = "token-c"
    store.get_or_create_session(token)
    old_time = datetime.now(UTC) - timedelta(hours=1)
    store._sessions[token]["last_active_at"] = old_time

    store.ensure_session_kb(token)

    assert store._sessions[token]["last_active_at"] > old_time
    assert store._sessions[token]["kb_id"] == "kb_user_token-c"


def test_get_idle_session_tokens_finds_only_sessions_past_ttl():
    fresh_token = store.get_or_create_session("fresh-token")
    idle_token = store.get_or_create_session("idle-token")
    store._sessions[idle_token]["last_active_at"] = datetime.now(UTC) - timedelta(hours=1)

    idle = store.get_idle_session_tokens(ttl_seconds=60)

    assert idle_token in idle
    assert fresh_token not in idle


def test_reap_session_removes_metadata_and_vectors():
    token = "reap-me"
    kb_id = store.ensure_session_kb(token)
    doc = store.create_document(
        knowledge_base_id=kb_id, filename="a.txt", file_type="txt", size_bytes=10
    )
    _upsert_one_chunk(kb_id, doc["document_id"])
    assert vector_store.count_chunks_for_knowledge_base(kb_id) == 1

    returned_kb_id = store.reap_session(token)

    assert returned_kb_id == kb_id
    assert token not in store._sessions
    assert store.get_document(doc["document_id"]) is None
    # reap_session only removes the mock-store metadata; the caller (the
    # reaper loop in main.py) is responsible for the Qdrant side, mirroring
    # main.py's own division of labor between store.reap_session and
    # vector_store.delete_knowledge_base_vectors.
    vector_store.delete_knowledge_base_vectors(returned_kb_id)
    assert vector_store.count_chunks_for_knowledge_base(kb_id) == 0


def test_reap_session_unknown_token_is_noop():
    assert store.reap_session("never-existed") is None


def test_reap_session_session_that_never_uploaded_is_noop_but_removed():
    token = store.get_or_create_session("never-uploaded")
    assert store.reap_session(token) is None
    assert token not in store._sessions


def test_reap_session_never_touches_demo_kb():
    # A session's kb_id is always derived via derive_user_kb_id (always
    # "kb_user_<token>"), so it can never legitimately equal DEMO_KB_ID -
    # but simulate a corrupted/malicious record to prove the guard actually
    # fires rather than trusting that invariant blindly.
    token = "malicious-token"
    store._sessions[token] = {"kb_id": store.DEMO_KB_ID, "last_active_at": datetime.now(UTC)}

    with pytest.raises(AssertionError):
        store.reap_session(token)


def test_delete_knowledge_base_vectors_refuses_demo_kb():
    with pytest.raises(AssertionError):
        vector_store.delete_knowledge_base_vectors(store.DEMO_KB_ID)


def test_delete_knowledge_base_vectors_only_removes_that_kb():
    _upsert_one_chunk("kb_user_x", "doc-x")
    _upsert_one_chunk("kb_user_y", "doc-y")

    vector_store.delete_knowledge_base_vectors("kb_user_x")

    assert vector_store.count_chunks_for_knowledge_base("kb_user_x") == 0
    assert vector_store.count_chunks_for_knowledge_base("kb_user_y") == 1


def test_full_sweep_never_touches_demo_kb_documents():
    # Seed a demo-kb-shaped document under the real DEMO_KB_ID directly in
    # the mock store (demo documents don't normally pass through
    # create_document(), but this proves even a document that DID end up
    # tagged with DEMO_KB_ID survives a sweep) alongside a genuinely idle
    # user session, then run a real sweep exactly the way main.py's
    # reaper does it.
    demo_doc = store.create_document(
        knowledge_base_id=store.DEMO_KB_ID, filename="demo.md", file_type="md", size_bytes=1
    )
    idle_token = store.get_or_create_session("idle-demo-adjacent")
    idle_kb_id = store.ensure_session_kb(idle_token)
    user_doc = store.create_document(
        knowledge_base_id=idle_kb_id, filename="u.txt", file_type="txt", size_bytes=1
    )
    _upsert_one_chunk(idle_kb_id, user_doc["document_id"])
    store._sessions[idle_token]["last_active_at"] = datetime.now(UTC) - timedelta(hours=1)

    for token in store.get_idle_session_tokens(ttl_seconds=60):
        kb_id = store.reap_session(token)
        if kb_id is not None:
            vector_store.delete_knowledge_base_vectors(kb_id)

    assert store.get_document(demo_doc["document_id"]) is not None
    assert store.get_document(user_doc["document_id"]) is None
    assert idle_token not in store._sessions


def test_stale_token_after_reap_is_treated_as_fresh_empty_session():
    token = "will-be-reaped"
    kb_id = store.ensure_session_kb(token)
    store.create_document(knowledge_base_id=kb_id, filename="a.txt", file_type="txt", size_bytes=1)
    store._sessions[token]["last_active_at"] = datetime.now(UTC) - timedelta(hours=1)

    for stale_token in store.get_idle_session_tokens(ttl_seconds=60):
        reaped_kb_id = store.reap_session(stale_token)
        if reaped_kb_id is not None:
            vector_store.delete_knowledge_base_vectors(reaped_kb_id)

    assert token not in store._sessions

    # The same browser tab reuses the same (now-reaped) token on its next
    # request - must behave as a brand-new, empty session, not error.
    resolved = store.get_or_create_session(token)
    assert resolved == token
    assert store._sessions[token]["kb_id"] is None
    assert store.list_documents_for_kb(kb_id) == []
    assert store.session_owns_kb(token, store.derive_user_kb_id(token)) is True


def test_concurrent_create_document_and_list_does_not_corrupt_or_raise():
    kb_id = "kb_user_concurrent-test"
    errors: list[Exception] = []

    def writer():
        for _ in range(200):
            store.create_document(
                knowledge_base_id=kb_id, filename="c.txt", file_type="txt", size_bytes=1
            )

    def reader():
        for _ in range(200):
            try:
                store.list_documents_for_kb(kb_id)
            except Exception as exc:  # noqa: BLE001 - test wants to see any failure
                errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(3)] + [
        threading.Thread(target=reader) for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(store.list_documents_for_kb(kb_id)) == 600


def test_concurrent_reap_and_touch_does_not_raise():
    # Simulates the reaper sweeping a session at the same moment a request
    # for that same (about-to-be-reaped) token is touching its activity -
    # the exact race this module's lock exists to prevent.
    token = "race-token"
    kb_id = store.ensure_session_kb(token)
    for _ in range(20):
        store.create_document(
            knowledge_base_id=kb_id, filename="r.txt", file_type="txt", size_bytes=1
        )
    errors: list[Exception] = []

    def reaper():
        try:
            store.reap_session(token)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def toucher():
        for _ in range(50):
            try:
                store.touch_session_activity(token)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=reaper), threading.Thread(target=toucher)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
