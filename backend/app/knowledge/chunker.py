"""
backend/app/knowledge/chunker.py

Splits markdown crop manuals by headings and natural sentence/paragraph
boundaries with overlap. Preserves heading context and is fully Unicode/Urdu safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import get_settings


@dataclass
class KnowledgeChunk:
    """A single chunk of agricultural knowledge ready for embedding and storage."""
    text: str
    crop: str
    source_file: str
    heading_path: str
    chunk_index: int


# Urdu and English sentence end markers (۔ = U+06D4, ؟ = U+061F, ., !, ?)
_SENTENCE_BOUNDARY_RE = re.compile(r"([.!?۔؟]+(?:\s+|$))")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences preserving punctuation and handling Unicode/Urdu."""
    tokens = _SENTENCE_BOUNDARY_RE.split(text)
    sentences: list[str] = []
    current = ""
    for tok in tokens:
        if not tok:
            continue
        current += tok
        if _SENTENCE_BOUNDARY_RE.search(tok):
            s = current.strip()
            if s:
                sentences.append(s)
            current = ""
    if current.strip():
        sentences.append(current.strip())
    return sentences


def _subdivide_oversized_text(
    text: str,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    """
    Subdivide text longer than max_chars into overlapping pieces, breaking on
    paragraph or sentence boundaries without cutting mid-word.
    """
    if len(text) <= max_chars:
        return [text] if text.strip() else []

    # First attempt: break into paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pieces: list[str] = []

    for para in paragraphs:
        if len(para) <= max_chars:
            pieces.append(para)
        else:
            # Paragraph itself is too big -> break into sentences
            sentences = _split_into_sentences(para)
            buffer = ""
            for s in sentences:
                if not buffer:
                    buffer = s
                elif len(buffer) + 1 + len(s) <= max_chars:
                    buffer += " " + s
                else:
                    if buffer.strip():
                        pieces.append(buffer.strip())
                    # If single sentence exceeds max_chars, split on words
                    if len(s) > max_chars:
                        words = s.split()
                        w_buf = ""
                        for w in words:
                            if not w_buf:
                                w_buf = w
                            elif len(w_buf) + 1 + len(w) <= max_chars:
                                w_buf += " " + w
                            else:
                                if w_buf.strip():
                                    pieces.append(w_buf.strip())
                                w_buf = w
                        buffer = w_buf
                    else:
                        buffer = s
            if buffer.strip():
                pieces.append(buffer.strip())

    # Now group pieces into overlapping chunks of at most max_chars
    chunks: list[str] = []
    current_chunk = ""

    for piece in pieces:
        if not current_chunk:
            current_chunk = piece
        elif len(current_chunk) + 2 + len(piece) <= max_chars:
            current_chunk += "\n\n" + piece
        else:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            # Overlap: keep tail of current_chunk
            overlap_prefix = ""
            if overlap_chars > 0 and len(current_chunk) > overlap_chars:
                overlap_text = current_chunk[-overlap_chars:]
                # Try to snap to space/boundary
                first_space = overlap_text.find(" ")
                if first_space != -1:
                    overlap_prefix = overlap_text[first_space + 1:].strip()
                else:
                    overlap_prefix = overlap_text.strip()
            if overlap_prefix:
                current_chunk = overlap_prefix + "\n\n" + piece
            else:
                current_chunk = piece

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def chunk_markdown(
    content: str,
    source_filename: str,
    max_chars: Optional[int] = None,
    overlap_chars: Optional[int] = None,
) -> list[KnowledgeChunk]:
    """
    Parse a Markdown document into heading-scoped, size-bounded KnowledgeChunks.

    Args:
        content: Raw markdown text.
        source_filename: Name of the file, e.g. "cotton.md".
        max_chars: Maximum chunk character length (defaults to settings.RAG_CHUNK_MAX_CHARS).
        overlap_chars: Overlap character length (defaults to settings.RAG_CHUNK_OVERLAP_CHARS).

    Returns:
        List of KnowledgeChunk objects with deterministic chunk_index.
    """
    settings = get_settings()
    max_len = max_chars or settings.RAG_CHUNK_MAX_CHARS
    overlap_len = overlap_chars or settings.RAG_CHUNK_OVERLAP_CHARS

    crop_name = Path(source_filename).stem.lower().strip()

    # Step 1: Split content by Markdown headings
    lines = content.splitlines()
    sections: list[tuple[str, str]] = []  # (heading_path, text)
    current_heading_stack: list[tuple[int, str]] = []  # [(level, title)]
    current_section_lines: list[str] = []

    def get_heading_path() -> str:
        if not current_heading_stack:
            return crop_name.capitalize()
        return " > ".join(title for _, title in current_heading_stack)

    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            # Flush existing section
            body = "\n".join(current_section_lines).strip()
            if body:
                sections.append((get_heading_path(), body))
            current_section_lines = []

            level = len(match.group(1))
            title = match.group(2).strip()

            # Update heading stack
            while current_heading_stack and current_heading_stack[-1][0] >= level:
                current_heading_stack.pop()
            current_heading_stack.append((level, title))
        else:
            current_section_lines.append(line)

    # Flush final section
    final_body = "\n".join(current_section_lines).strip()
    if final_body:
        sections.append((get_heading_path(), final_body))

    # If document has no headings at all, treat entire text as single section
    if not sections and content.strip():
        sections.append((crop_name.capitalize(), content.strip()))

    # Step 2: Split each section if it exceeds max_chars
    chunks: list[KnowledgeChunk] = []
    chunk_index = 0

    for heading_path, body in sections:
        sub_texts = _subdivide_oversized_text(body, max_chars=max_len, overlap_chars=overlap_len)
        for text in sub_texts:
            t = text.strip()
            if not t:
                continue
            chunks.append(
                KnowledgeChunk(
                    text=t,
                    crop=crop_name,
                    source_file=source_filename,
                    heading_path=heading_path,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

    return chunks

