"""Seeds the demo knowledge base (kb_demo) directly against Qdrant, bypassing
the public /documents/upload endpoint entirely (docs/DOCUMENT_PROCESSING.md
"Demo Knowledge-Base Seeding"). Run manually at deploy time, or after a
Qdrant Cloud free-cluster suspension to repopulate the demo KB (ADR-07's
recovery procedure).

Known gap (Phase 15): GET /knowledge-bases and GET /knowledge-bases/{id}/documents
derive kb_demo's document list/count from the in-process mock store
(store.list_documents_for_kb), which this script does not and should not
touch - the mock store is per-process memory (ADR-12), and this script is a
separate, offline process whose writes go straight to Qdrant. This means
those two endpoints will keep reporting document_count: 0 for kb_demo even
after real seeding, even though chat against kb_demo works correctly (its
readiness check already queries Qdrant directly, not the mock store -
fixed in Phase 12). Not fixed here: doing so is a real design decision
(denormalize file_type/size_bytes/uploaded_at onto every chunk payload, or
read backend/demo_content/ from disk at request time, or something else)
that deserves its own deliberate choice - most likely Phase 16, once the
actual Demo Knowledge-Base View UI's real requirements (docs/UI_UX.md only
needs document *names*, not full status/size) are concretely in front of
whoever builds it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.chunk import chunk_document
from ingestion.embed import embed_texts
from ingestion.extract import extract_and_clean
from retrieval import vector_store
from store import DEMO_KB_ID

DEMO_CONTENT_DIR = Path(__file__).parent.parent / "demo_content"
DEMO_FILES = [
    "01_employee_handbook.md",
    "02_product_faq.md",
    "03_onboarding_guide.md",
    "04_security_policy.md",
]


def seed_demo_kb() -> int:
    """Ingests every file in DEMO_FILES into kb_demo. Returns total chunk count.

    document_id is derived deterministically from the filename stem (not a
    random UUID) so that chunk_id - and therefore each Qdrant point's ID
    (vector_store._point_id, a uuid5 of chunk_id) - is stable across runs.
    Re-running this script overwrites the same points rather than creating
    duplicates alongside old ones.
    """
    total_chunks = 0
    for filename in DEMO_FILES:
        path = DEMO_CONTENT_DIR / filename
        document_id = Path(filename).stem  # e.g. "01_employee_handbook"
        file_type = Path(filename).suffix.lstrip(".")

        units = extract_and_clean(str(path), file_type)
        chunks = chunk_document(
            units,
            document_id=document_id,
            knowledge_base_id=DEMO_KB_ID,
            document_name=filename,
        )
        vectors = embed_texts([c.text for c in chunks])
        vector_store.upsert_chunks(chunks, vectors)

        print(f"  {filename}: {len(chunks)} chunks")
        total_chunks += len(chunks)

    return total_chunks


if __name__ == "__main__":
    print(f"Seeding demo knowledge base ({DEMO_KB_ID}) from {DEMO_CONTENT_DIR}...")
    total = seed_demo_kb()
    print(f"Done. {len(DEMO_FILES)} files, {total} chunks total.")
