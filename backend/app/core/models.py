"""
backend/app/core/models.py

Fixed Gemini model lists and voice settings for KisaanDost / FarmAI.
DO NOT change these strings without an explicit instruction from the project owner.
See AGENTS.md §4 for the canonical list.
"""

from __future__ import annotations

from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Fixed model lists (never alter these strings)
# ---------------------------------------------------------------------------

TEXT_MODELS: list[str] = [
    "gemini-3.5-flash-lite",
]

STT_MODELS: list[str] = [
    "gemini-3.5-flash-lite",
]

TTS_MODELS: list[str] = [
    "gemini-3.8-flash-lite-tts",
]

TTS_VOICE: str = "Aoede"


# ---------------------------------------------------------------------------
# Helpers that honour per-environment model overrides
# ---------------------------------------------------------------------------


def get_text_models() -> list[str]:
    """
    Return the text model list to try in priority order.

    If GEMINI_MODEL is set in settings, that model is inserted FIRST
    (deduplicating if it already appears in TEXT_MODELS) so it acts as the
    primary choice while the fixed list serves as fallbacks.
    """
    settings = get_settings()
    override = settings.GEMINI_MODEL
    if not override:
        return list(TEXT_MODELS)
    # Put the override first, then the rest without duplicates.
    rest = [m for m in TEXT_MODELS if m != override]
    return [override] + rest


def get_tts_models() -> list[str]:
    """
    Return the TTS model list to try in priority order.

    If GEMINI_TTS_MODEL is set in settings, it is inserted FIRST with the
    same deduplication logic as get_text_models().
    """
    settings = get_settings()
    override = settings.GEMINI_TTS_MODEL
    if not override:
        return list(TTS_MODELS)
    rest = [m for m in TTS_MODELS if m != override]
    return [override] + rest


def get_stt_models() -> list[str]:
    """Return the STT model list (no override field for STT yet)."""
    return list(STT_MODELS)
