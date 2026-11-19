"""
backend/app/core/key_manager.py

Domain-separated, rotating Gemini API key pool with per-key cooldowns.

Domains: CHAT, STT, TTS.

SECURITY RULES (enforced throughout this module):
  - API key VALUES are NEVER logged, returned in responses, or included in
    exception messages.  Only slot numbers (1, 2, 3) may appear in logs/errors.
  - scrub_secrets() must be applied to any exception message before logging.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Literal

from google.genai.errors import APIError, ClientError, ServerError

from app.core.config import get_settings
from app.core.exceptions import (
    AllKeysExhaustedError,
    KeyAttempt,
    NoKeysConfiguredError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Domain = Literal["CHAT", "STT", "TTS"]
ExceptionClass = Literal[
    "quota_or_rate_limit",
    "invalid_api_key",
    "model_not_found",
    "transient",
    "invalid_request",
    "unknown",
]


# ---------------------------------------------------------------------------
# Key slot state
# ---------------------------------------------------------------------------


@dataclass
class _KeySlot:
    """Internal state for a single API key slot."""
    slot: int           # 1-based human-readable index
    key: str            # The actual key — never logged or returned
    bad: bool = False   # Permanently marked invalid (401/403 with key error)
    cooldown_until: float = 0.0  # epoch seconds; 0 means not cooling


# ---------------------------------------------------------------------------
# Result carrier
# ---------------------------------------------------------------------------


@dataclass
class KeyedResult:
    """Wraps the return value of an operation with the key slot that succeeded."""
    result: Any
    key_slot: int


# ---------------------------------------------------------------------------
# Secret scrubber
# ---------------------------------------------------------------------------


def scrub_secrets(text: str, keys: list[str]) -> str:
    """
    Replace every occurrence of a real key value in `text` with '[REDACTED]'.
    Call this before logging any exception message that might have been
    constructed by the SDK and could inadvertently contain a key fragment.
    """
    for key in keys:
        if key and key in text:
            text = text.replace(key, "[REDACTED]")
    return text


# ---------------------------------------------------------------------------
# Exception classifier
# ---------------------------------------------------------------------------


def classify_exception(exc: BaseException) -> ExceptionClass:
    """
    Classify a caught exception into one of six categories so the rotation
    logic knows how to react.

    Classification is based on the SDK's actual exception attributes:
      - APIError.code  : int HTTP status code
      - APIError.status: str canonical status (e.g. "RESOURCE_EXHAUSTED")
      - APIError.message: str human-readable detail

    Network / transport errors (not APIError) are always "transient".
    """
    if isinstance(exc, APIError):
        code: int = exc.code or 0
        status: str = (exc.status or "").upper()
        message: str = (exc.message or "").lower()

        # --- 429 or RESOURCE_EXHAUSTED → rate limit / quota ---
        if code == 429 or "RESOURCE_EXHAUSTED" in status:
            return "quota_or_rate_limit"

        # --- 401 / 403, or 400 that explicitly mentions API key validity ---
        if code in (401, 403):
            return "invalid_api_key"
        if code == 400 and (
            "api key" in message
            or "api_key" in message
            or "invalid key" in message
            or "UNAUTHENTICATED" in status
            or "PERMISSION_DENIED" in status
        ):
            return "invalid_api_key"

        # --- 404 or model-not-found / not-supported messages ---
        if code == 404 or "NOT_FOUND" in status:
            return "model_not_found"
        if code == 400 and (
            "model" in message and ("not found" in message or "not support" in message)
        ):
            return "model_not_found"

        # --- 5xx server errors → transient ---
        if code in (500, 502, 503, 504):
            return "transient"

        # --- Other 400-range errors → invalid request (not a key problem) ---
        if 400 <= code < 500:
            return "invalid_request"

        return "unknown"

    # --- Network / transport failures → transient ---
    exc_type = type(exc).__name__
    if any(
        name in exc_type
        for name in ("Timeout", "Connect", "Network", "Transport", "OSError")
    ) or isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError)):
        return "transient"

    return "unknown"


# ---------------------------------------------------------------------------
# Pool registry
# ---------------------------------------------------------------------------


class _KeyPool:
    """Thread/asyncio-safe rotating key pool for one domain."""

    def __init__(self, domain: Domain, slots: list[_KeySlot]) -> None:
        self.domain = domain
        self._slots = slots          # immutable order after init
        self._index = 0              # round-robin cursor
        self._lock = asyncio.Lock()  # protects cursor + slot state mutations

    @property
    def size(self) -> int:
        return len(self._slots)

    async def _next_slot(self) -> _KeySlot | None:
        """
        Return the next usable slot (not bad, not currently cooling down)
        in round-robin order.  Returns None only when all slots are bad
        (permanently invalid).
        """
        async with self._lock:
            n = len(self._slots)
            if n == 0:
                return None
            now = time.monotonic()
            start = self._index
            for i in range(n):
                idx = (start + i) % n
                slot = self._slots[idx]
                if slot.bad:
                    continue
                if slot.cooldown_until <= now:
                    self._index = (idx + 1) % n
                    return slot
            # All are either bad or cooling — find the one cooling soonest
            best: _KeySlot | None = None
            for slot in self._slots:
                if slot.bad:
                    continue
                if best is None or slot.cooldown_until < best.cooldown_until:
                    best = slot
            if best:
                self._index = (self._slots.index(best) + 1) % n
            return best

    async def mark_cooldown(self, slot: _KeySlot, seconds: float) -> None:
        async with self._lock:
            slot.cooldown_until = time.monotonic() + seconds
        logger.warning(
            "[KeyManager] Domain=%s slot=%d → cooldown for %.0fs (rate-limited)",
            self.domain, slot.slot, seconds
        )

    async def mark_bad(self, slot: _KeySlot) -> None:
        async with self._lock:
            slot.bad = True
        logger.error(
            "[KeyManager] Domain=%s slot=%d → permanently marked INVALID (bad key)",
            self.domain, slot.slot
        )

    def all_keys(self) -> list[str]:
        """Return raw key values — used ONLY by scrub_secrets, never logged."""
        return [s.key for s in self._slots]


# ---------------------------------------------------------------------------
# Global pool registry (populated by init_pools)
# ---------------------------------------------------------------------------

_pools: dict[Domain, _KeyPool] = {}
_pools_initialised = False
_init_lock = asyncio.Lock()


async def init_pools() -> None:
    """
    Build key pools from settings.  Safe to call multiple times (idempotent).
    Must be awaited from the FastAPI lifespan startup handler.
    """
    global _pools, _pools_initialised
    async with _init_lock:
        if _pools_initialised:
            return

        settings = get_settings()
        cooldown = settings.KEY_COOLDOWN_SECONDS

        domain_key_map: dict[Domain, list[tuple[int, str | None]]] = {
            "CHAT": [
                (1, settings.GEMINI_CHAT_KEY_1),
                (2, settings.GEMINI_CHAT_KEY_2),
                (3, settings.GEMINI_CHAT_KEY_3),
            ],
            "STT": [
                (1, settings.GEMINI_STT_KEY_1),
                (2, settings.GEMINI_STT_KEY_2),
                (3, settings.GEMINI_STT_KEY_3),
            ],
            "TTS": [
                (1, settings.GEMINI_TTS_KEY_1),
                (2, settings.GEMINI_TTS_KEY_2),
                (3, settings.GEMINI_TTS_KEY_3),
            ],
        }

        for domain, key_tuples in domain_key_map.items():
            slots = [
                _KeySlot(slot=slot_num, key=k)
                for slot_num, k in key_tuples
                if k and k.strip()
            ]

            # Fall back to GEMINI_API_KEY if domain has no specific keys
            if not slots and settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip():
                slots = [_KeySlot(slot=1, key=settings.GEMINI_API_KEY)]
                logger.warning(
                    "[KeyManager] Domain=%s has no dedicated keys — "
                    "falling back to GEMINI_API_KEY (slot 1).",
                    domain,
                )

            if not slots:
                logger.warning(
                    "[KeyManager] Domain=%s has NO keys configured. "
                    "Calls to this domain will raise NoKeysConfiguredError.",
                    domain,
                )

            _pools[domain] = _KeyPool(domain=domain, slots=slots)  # type: ignore[arg-type]
            logger.info(
                "[KeyManager] Domain=%s → %d key(s) loaded.",
                domain, len(slots)
            )

        _pools_initialised = True


def _get_pool(domain: Domain) -> _KeyPool:
    if not _pools_initialised:
        raise RuntimeError(
            "Key pools have not been initialised. "
            "Ensure init_pools() is awaited in the FastAPI lifespan startup."
        )
    return _pools[domain]


# ---------------------------------------------------------------------------
# Core rotation runner
# ---------------------------------------------------------------------------


async def run_with_key_rotation(
    domain: Domain,
    operation: Callable[[str], Coroutine[Any, Any, Any]],
) -> KeyedResult:
    """
    Execute `operation(api_key)` with automatic key rotation on failure.

    Rotation strategy per error class:
      quota_or_rate_limit → cooldown this key, try next
      invalid_api_key     → permanently mark this key bad, try next
      transient           → retry SAME key once after 0.5 s, then try next
      model_not_found     → re-raise immediately (not a key problem)
      invalid_request     → re-raise immediately (not a key problem)
      unknown             → re-raise immediately

    Raises:
      NoKeysConfiguredError  — pool is empty
      AllKeysExhaustedError  — every key tried and failed
      (original exc)         — for model_not_found / invalid_request / unknown
    """
    pool = _get_pool(domain)

    if pool.size == 0:
        raise NoKeysConfiguredError(domain)

    settings = get_settings()
    cooldown_secs = settings.KEY_COOLDOWN_SECONDS
    all_keys_for_scrub = pool.all_keys()

    attempts: list[KeyAttempt] = []
    tried_slots: set[int] = set()
    max_attempts = pool.size  # at most one attempt per slot

    for _ in range(max_attempts):
        slot = await pool._next_slot()

        # If the returned slot was already tried, we've cycled — stop.
        if slot is None or slot.slot in tried_slots:
            break
        tried_slots.add(slot.slot)

        try:
            result = await operation(slot.key)
            logger.debug(
                "[KeyManager] Domain=%s slot=%d → SUCCESS", domain, slot.slot
            )
            return KeyedResult(result=result, key_slot=slot.slot)

        except BaseException as exc:
            error_class = classify_exception(exc)
            safe_msg = scrub_secrets(str(exc), all_keys_for_scrub)
            attempts.append(KeyAttempt(slot=slot.slot, error_class=error_class))

            if error_class == "quota_or_rate_limit":
                logger.warning(
                    "[KeyManager] Domain=%s slot=%d → rate-limited (%s). "
                    "Starting %.0fs cooldown.",
                    domain, slot.slot, safe_msg[:120], cooldown_secs,
                )
                await pool.mark_cooldown(slot, cooldown_secs)
                continue

            elif error_class == "invalid_api_key":
                logger.error(
                    "[KeyManager] Domain=%s slot=%d → invalid key (%s). "
                    "Marking permanently bad.",
                    domain, slot.slot, safe_msg[:120],
                )
                await pool.mark_bad(slot)
                continue

            elif error_class == "transient":
                logger.warning(
                    "[KeyManager] Domain=%s slot=%d → transient error (%s). "
                    "Retrying once after 0.5s.",
                    domain, slot.slot, safe_msg[:120],
                )
                await asyncio.sleep(0.5)
                try:
                    result = await operation(slot.key)
                    logger.debug(
                        "[KeyManager] Domain=%s slot=%d → SUCCESS on retry",
                        domain, slot.slot,
                    )
                    return KeyedResult(result=result, key_slot=slot.slot)
                except BaseException as retry_exc:
                    retry_class = classify_exception(retry_exc)
                    retry_msg = scrub_secrets(str(retry_exc), all_keys_for_scrub)
                    logger.warning(
                        "[KeyManager] Domain=%s slot=%d → retry also failed (%s). "
                        "Moving to next key.",
                        domain, slot.slot, retry_msg[:120],
                    )
                    attempts[-1] = KeyAttempt(slot=slot.slot, error_class=retry_class)
                    continue

            elif error_class in ("model_not_found", "invalid_request"):
                # Not a key problem — propagate immediately.
                raise

            else:  # "unknown"
                raise

    raise AllKeysExhaustedError(domain=domain, attempts=attempts)

