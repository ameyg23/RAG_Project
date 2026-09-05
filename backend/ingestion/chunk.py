"""Stage 3-4 of docs/RAG_PIPELINE.md: chunking + metadata.

Only LangChain's text splitter is used here (ADR-05) — no chains/agents.
"""

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ingestion.extract import TextUnit

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


@dataclass
class DocumentChunk:
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    document_name: str
    chunk_index: int
    page: int | None
    text: str


def chunk_document(
    units: list[TextUnit],
    *,
    document_id: str,
    knowledge_base_id: str,
    document_name: str,
) -> list[DocumentChunk]:
    """Split each extracted unit independently (chunks never span two units,
    so PDF page attribution is never lost across a chunk boundary), assign a
    single chunk_index counter across the whole document, and attach the
    metadata required by docs/DATA_MODEL.md's DocumentChunk.
    """
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14)")
    if not document_id:
        raise ValueError("document_id must not be empty")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
    )

    chunks: list[DocumentChunk] = []
    chunk_index = 0
    for unit in units:
        pieces = splitter.split_text(unit.text)
        for piece in pieces:
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document_id}_{chunk_index}",
                    document_id=document_id,
                    knowledge_base_id=knowledge_base_id,
                    document_name=document_name,
                    chunk_index=chunk_index,
                    page=unit.page,
                    text=piece,
                )
            )
            chunk_index += 1

    return chunks
