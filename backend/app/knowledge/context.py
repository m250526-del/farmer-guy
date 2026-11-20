"""
backend/app/knowledge/context.py

Formats retrieved knowledge chunks into compact, token-efficient prompt context.
Ensures context limits are respected and sentences are never cut mid-way.
"""

from __future__ import annotations

import re
from typing import Optional

from app.core.config import get_settings

_SENTENCE_BOUNDARY_RE = re.compile(r"([.!?۔؟]+(?:\s+|\n+|$))")


def _truncate_to_sentence(text: str, budget: int) -> str:
    """Trim text to fit within budget characters on a sentence boundary."""
    if len(text) <= budget:
        return text

    truncated = text[:budget]
    matches = list(_SENTENCE_BOUNDARY_RE.finditer(truncated))
    if matches:
        last_end = matches[-1].end()
        candidate = truncated[:last_end].strip()
        if candidate:
            return candidate

    # Fallback: snap to last word boundary
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space].strip()
    return ""


def format_context(results: list[dict], max_chars: Optional[int] = None) -> str:
    """
    Format retrieved knowledge chunks into a structured string for LLM injection.

    Rules:
      - Ranks best scoring chunks first.
      - Displays context header `[Heading Path]` before text.
      - Stops when RAG_CONTEXT_MAX_CHARS is reached.
      - Never cuts a chunk mid-sentence.
      - This is the ONLY function that should prepare context for agent prompts.

    Args:
        results: List of retrieved dicts with 'heading_path', 'text', 'score', etc.
        max_chars: Hard character budget (defaults to settings.RAG_CONTEXT_MAX_CHARS).

    Returns:
        Formatted context string, or empty string if results are empty.
    """
    if not results:
        return ""

    settings = get_settings()
    char_budget = max_chars or settings.RAG_CONTEXT_MAX_CHARS

    formatted_blocks: list[str] = []
    used_chars = 0

    # Ensure results are sorted descending by score
    sorted_results = sorted(results, key=lambda r: r.get("score", 0.0), reverse=True)

    for item in sorted_results:
        heading = item.get("heading_path", "").strip()
        text = item.get("text", "").strip()
        if not text:
            continue

        header_line = f"[{heading}]\n" if heading else ""
        block_text = f"{header_line}{text}"
        block_len = len(block_text)

        remaining_budget = char_budget - used_chars

        if remaining_budget <= 0:
            break

        # Check if full block fits
        separator_len = 2 if formatted_blocks else 0  # "\n\n"
        if block_len + separator_len <= remaining_budget:
            formatted_blocks.append(block_text)
            used_chars += block_len + separator_len
        else:
            # Does not fit fully: try to fit partial block on sentence boundary
            allowed_for_text = remaining_budget - separator_len - len(header_line)
            if allowed_for_text > 80:  # Only add if meaningful sentence fits
                clean_text = _truncate_to_sentence(text, allowed_for_text)
                if clean_text:
                    truncated_block = f"{header_line}{clean_text}"
                    formatted_blocks.append(truncated_block)
                    used_chars += len(truncated_block) + separator_len
            break

    return "\n\n".join(formatted_blocks).strip()

