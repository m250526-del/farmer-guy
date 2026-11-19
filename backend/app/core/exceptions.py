"""
backend/app/core/exceptions.py

Custom exception hierarchy for KisaanDost / FarmAI.
All exceptions here are secret-safe: they never store or expose API key values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Key-manager exceptions
# ---------------------------------------------------------------------------


@dataclass
class KeyAttempt:
    """Record of a single key attempt — slot number, error class, exception type, and scrubbed message."""
    slot: int
    error_class: str
    exception_type: str = ""
    message: str = ""


class NoKeysConfiguredError(RuntimeError):
    """
    Raised when a key pool is completely empty (no domain-specific keys and
    no fallback GEMINI_API_KEY).  The message names the domain and the env
    vars the developer should set.
    """
    def __init__(self, domain: str) -> None:
        env_vars = ", ".join(
            f"GEMINI_{domain}_KEY_1 / _2 / _3"
        )
        super().__init__(
            f"No API keys configured for domain '{domain}'. "
            f"Set {env_vars} (or GEMINI_API_KEY as a fallback) in your .env file."
        )
        self.domain = domain


class AllKeysExhaustedError(RuntimeError):
    """
    Raised when every key in a pool has been tried and all failed.
    Carries a list of KeyAttempt records (slot + error class, never the key).
    """
    def __init__(self, domain: str, attempts: list[KeyAttempt]) -> None:
        attempt_summary = ", ".join(
            f"slot {a.slot} → {a.error_class}" for a in attempts
        )
        super().__init__(
            f"All keys exhausted for domain '{domain}'. "
            f"Attempts: [{attempt_summary}]"
        )
        self.domain = domain
        self.attempts: list[KeyAttempt] = attempts


# ---------------------------------------------------------------------------
# Gemini client exceptions
# ---------------------------------------------------------------------------


class GeminiUnavailableError(RuntimeError):
    """
    Raised by gemini_client when every model in the list has failed.
    Contains a per-model attempt summary (model name + error class, no secrets).
    """
    def __init__(self, model_attempts: list[dict[str, Any]]) -> None:
        summary = "; ".join(
            f"{a['model']} → {a['error_class']}" for a in model_attempts
        )
        super().__init__(f"All Gemini models failed: {summary}")
        self.model_attempts = model_attempts


class EmptyGeminiResponseError(RuntimeError):
    """
    Raised when Gemini returns a response with no usable text content
    (e.g. blocked by safety filters or empty candidates).
    """
    def __init__(self, model: str, reason: str = "empty or blocked response") -> None:
        super().__init__(f"Empty Gemini response from model '{model}': {reason}")
        self.model = model
        self.reason = reason

