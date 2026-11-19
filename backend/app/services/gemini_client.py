"""
backend/app/services/gemini_client.py

Generic Gemini text-generation client for KisaanDost / FarmAI.

All calls go through core/key_manager.run_with_key_rotation() so that:
  - API keys are never handled directly here.
  - Rate-limit and key rotation happen automatically.
  - No key value ever appears in logs or error messages.

Rule: ALL Gemini SDK calls in this project must come through this module.
Never import google.genai directly in any other file.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from google import genai
from google.genai import types as genai_types
from google.genai.errors import APIError

from app.core.config import get_settings
from app.core.exceptions import (
    AllKeysExhaustedError,
    EmptyGeminiResponseError,
    GeminiUnavailableError,
)
from app.core.key_manager import Domain, run_with_key_rotation
from app.core.models import get_text_models

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GeminiTextResult:
    """Return value of generate_text()."""
    text: str
    model_used: str
    key_slot: int
    latency_ms: float


# ---------------------------------------------------------------------------
# Image helper
# ---------------------------------------------------------------------------


@dataclass
class ImageInput:
    """Optional image to attach to a generate_text() call (Stage 4+)."""
    data: bytes
    mime_type: str  # e.g. "image/jpeg"


# ---------------------------------------------------------------------------
# Core text generation
# ---------------------------------------------------------------------------


async def generate_text(
    prompt: str,
    *,
    domain: Domain = "CHAT",
    models: Optional[list[str]] = None,
    system_instruction: Optional[str] = None,
    image: Optional[ImageInput] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    response_mime_type: Optional[str] = None,
) -> GeminiTextResult:
    """
    Generate text using the Gemini API with automatic key rotation and
    model fallback.

    Args:
        prompt: The user/farmer prompt text.
        domain: Key pool domain to use ("CHAT", "STT", "TTS"). Default "CHAT".
        models: Model list to try in order. Defaults to get_text_models().
        system_instruction: Optional system-level instruction for the model.
        image: Optional ImageInput (bytes + mime_type) to include in the request.
        temperature: Sampling temperature (None → model default).
        max_output_tokens: Max tokens in the response (None → model default).
        response_mime_type: e.g. "application/json" to request JSON output.

    Returns:
        GeminiTextResult with text, model_used, key_slot, latency_ms.

    Raises:
        NoKeysConfiguredError: No keys in the pool for this domain.
        AllKeysExhaustedError: Every key was tried and all failed.
        EmptyGeminiResponseError: Gemini returned an empty / blocked response.
        GeminiUnavailableError: Every model in the list failed.
        (APIError subclasses for invalid_request propagated directly.)
    """
    settings = get_settings()
    model_list = models or get_text_models()

    base_timeout = settings.GEMINI_REQUEST_TIMEOUT_SECONDS
    timeout_secs = base_timeout + 15 if image else base_timeout

    model_attempts: list[dict] = []
    t_overall_start = time.monotonic()

    for model in model_list:
        t_model_start = time.monotonic()

        async def _call(api_key: str, _model: str = model) -> str:
            """Inner coroutine that the key-manager will call with a key."""
            client = genai.Client(api_key=api_key)

            # Build config
            config_kwargs: dict = {}
            if system_instruction:
                config_kwargs["system_instruction"] = system_instruction
            if temperature is not None:
                config_kwargs["temperature"] = temperature
            if max_output_tokens is not None:
                config_kwargs["max_output_tokens"] = max_output_tokens
            if response_mime_type:
                config_kwargs["response_mime_type"] = response_mime_type

            generation_config = (
                genai_types.GenerateContentConfig(**config_kwargs)
                if config_kwargs
                else None
            )

            # Build contents
            if image:
                contents: list = [
                    genai_types.Part.from_bytes(
                        data=image.data, mime_type=image.mime_type
                    ),
                    prompt,
                ]
            else:
                contents = [prompt]

            # Async call with timeout
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=_model,
                    contents=contents,
                    config=generation_config,
                ),
                timeout=timeout_secs,
            )
            return response

        try:
            keyed = await run_with_key_rotation(domain=domain, operation=_call)
            response = keyed.result
            latency_ms = (time.monotonic() - t_model_start) * 1000

            # Extract text safely
            text = _extract_text(response, model)

            logger.info(
                "[GeminiClient] model=%s key_slot=%d latency=%.0fms domain=%s",
                model, keyed.key_slot, latency_ms, domain,
            )
            return GeminiTextResult(
                text=text,
                model_used=model,
                key_slot=keyed.key_slot,
                latency_ms=round(latency_ms, 1),
            )

        except AllKeysExhaustedError:
            # All keys failed for this model → pointless to try other models
            # (they would use the same exhausted/cooling pool).
            raise

        except APIError as exc:
            from app.core.key_manager import classify_exception
            err_class = classify_exception(exc)
            if err_class == "model_not_found":
                latency_ms = (time.monotonic() - t_model_start) * 1000
                logger.warning(
                    "[GeminiClient] model=%s not found/supported (%.0fms). "
                    "Trying next model.",
                    model, latency_ms,
                )
                model_attempts.append({"model": model, "error_class": err_class})
                continue
            # invalid_request or unknown → propagate
            raise

        except (EmptyGeminiResponseError, GeminiUnavailableError):
            raise

        except Exception as exc:
            from app.core.key_manager import classify_exception, scrub_secrets
            from app.core.key_manager import _get_pool
            pool = _get_pool(domain)
            safe_msg = scrub_secrets(str(exc), pool.all_keys())
            err_class = classify_exception(exc)
            logger.warning(
                "[GeminiClient] model=%s unexpected error class=%s: %s",
                model, err_class, safe_msg[:200],
            )
            model_attempts.append({"model": model, "error_class": err_class})
            continue

    # All models exhausted without success
    raise GeminiUnavailableError(model_attempts=model_attempts)


# ---------------------------------------------------------------------------
# Text extractor
# ---------------------------------------------------------------------------


def _extract_text(response: object, model: str) -> str:
    """
    Pull the text out of a Gemini GenerateContentResponse.
    Raises EmptyGeminiResponseError if no usable text is found.
    """
    # The SDK response object has a .text shortcut
    text: str | None = None

    try:
        text = response.text  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    # Fallback: walk candidates → content → parts
    if not text:
        try:
            for candidate in response.candidates or []:  # type: ignore[union-attr]
                for part in (candidate.content.parts or []):
                    if hasattr(part, "text") and part.text:
                        text = part.text
                        break
                if text:
                    break
        except (AttributeError, TypeError):
            pass

    if not text or not text.strip():
        # Try to get a reason (e.g. SAFETY)
        reason = "empty or blocked response"
        try:
            finish_reason = response.candidates[0].finish_reason  # type: ignore[index]
            reason = str(finish_reason)
        except (AttributeError, IndexError, TypeError):
            pass
        raise EmptyGeminiResponseError(model=model, reason=reason)

    return text.strip()

