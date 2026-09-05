"""Stage 1-2 of docs/RAG_PIPELINE.md: extraction + cleaning.

Only LangChain document loaders are used here (ADR-05) — no chains/agents.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_FILE_TYPES = {"pdf", "docx", "txt", "md"}

EMPTY_DOCUMENT_MESSAGE = "No extractable text found (file may be a scanned image)."


class CorruptedDocumentError(Exception):
    """Raised when the underlying loader/decoder cannot read the file at all."""


class EmptyDocumentError(Exception):
    """Raised when extraction succeeds but yields no usable text."""


@dataclass
class TextUnit:
    text: str
    page: int | None


def _clean_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    # Strip Unicode control characters (category Cc/Cf/...) except \n and \t.
    stripped = "".join(
        ch
        for ch in normalized
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )
    collapsed_spaces = re.sub(r"[ \t]+", " ", stripped)
    collapsed_newlines = re.sub(r"\n{3,}", "\n\n", collapsed_spaces)
    return collapsed_newlines.strip()


def _extract_raw_units(file_path: str, file_type: str) -> list[TextUnit]:
    if file_type == "pdf":
        from langchain_community.document_loaders import PyPDFLoader

        try:
            docs = PyPDFLoader(file_path).load()
        except Exception as exc:
            raise CorruptedDocumentError(
                f"Failed to read PDF '{file_path}': {exc}"
            ) from exc
        return [TextUnit(text=doc.page_content, page=i + 1) for i, doc in enumerate(docs)]

    if file_type == "docx":
        from langchain_community.document_loaders import Docx2txtLoader

        try:
            docs = Docx2txtLoader(file_path).load()
        except Exception as exc:
            raise CorruptedDocumentError(
                f"Failed to read DOCX '{file_path}': {exc}"
            ) from exc
        text = "\n".join(doc.page_content for doc in docs)
        return [TextUnit(text=text, page=None)]

    if file_type in ("txt", "md"):
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise CorruptedDocumentError(
                f"Failed to decode '{file_path}' as UTF-8: {exc}"
            ) from exc
        return [TextUnit(text=text, page=None)]

    raise ValueError(f"Unsupported file_type: {file_type!r}")


def extract_and_clean(file_path: str, file_type: str) -> list[TextUnit]:
    if file_type not in SUPPORTED_FILE_TYPES:
        raise ValueError(f"Unsupported file_type: {file_type!r}")

    raw_units = _extract_raw_units(file_path, file_type)

    cleaned_units = []
    for unit in raw_units:
        cleaned_text = _clean_text(unit.text)
        if cleaned_text:
            cleaned_units.append(TextUnit(text=cleaned_text, page=unit.page))

    if not cleaned_units:
        raise EmptyDocumentError(EMPTY_DOCUMENT_MESSAGE)

    return cleaned_units
