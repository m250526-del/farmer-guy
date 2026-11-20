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
import math
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

    # Compute timeout in milliseconds for google-genai HttpOptions
    base_timeout = settings.GEMINI_REQUEST_TIMEOUT_SECONDS
    timeout_secs = base_timeout + 15 if image else base_timeout
    timeout_ms = int(timeout_secs * 1000)

    model_attempts: list[dict] = []

    for model in model_list:
        t_model_start = time.monotonic()

        async def _call(api_key: str, _model: str = model) -> object:
            """Inner coroutine that the key-manager will call with a key."""
            client = genai.Client(
                api_key=api_key,
                http_options=genai_types.HttpOptions(timeout=timeout_ms),
            )

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

            # Async call with SDK HttpOptions timeout
            response = await client.aio.models.generate_content(
                model=_model,
                contents=contents,
                config=generation_config,
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
            from app.core.key_manager import classify_exception, scrub_secrets, _get_pool
            pool = _get_pool(domain)
            safe_msg = scrub_secrets(str(exc), pool.all_keys())
            err_class = classify_exception(exc)
            if err_class == "model_not_found":
                latency_ms = (time.monotonic() - t_model_start) * 1000
                logger.warning(
                    "[GeminiClient] model=%s not found/supported (%.0fms). "
                    "Trying next model.",
                    model, latency_ms,
                )
                model_attempts.append({
                    "model": model,
                    "error_class": err_class,
                    "exception_type": type(exc).__name__,
                    "message": safe_msg[:300],
                })
                continue
            # invalid_request or unknown → propagate
            raise

        except (EmptyGeminiResponseError, GeminiUnavailableError):
            raise

        except Exception as exc:
            from app.core.key_manager import classify_exception, scrub_secrets, _get_pool
            pool = _get_pool(domain)
            safe_msg = scrub_secrets(str(exc), pool.all_keys())
            err_class = classify_exception(exc)
            logger.warning(
                "[GeminiClient] model=%s unexpected error class=%s: %s",
                model, err_class, safe_msg[:200],
            )
            model_attempts.append({
                "model": model,
                "error_class": err_class,
                "exception_type": type(exc).__name__,
                "message": safe_msg[:300],
            })
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


# ---------------------------------------------------------------------------
# Embeddings (Stage 3)
# ---------------------------------------------------------------------------


@dataclass
class GeminiEmbedResult:
    """Return value of embed_texts()."""
    vectors: list[list[float]]
    model_used: str
    key_slot: int
    latency_ms: float


def _l2_normalize(vector: list[float]) -> list[float]:
    """Compute unit L2 norm vector (required when dimensions are truncated)."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return vector
    return [x / norm for x in vector]


_TASK_TYPE_REJECTED_LOGGED = False


async def embed_texts(
    texts: list[str],
    *,
    task_type: str,  # "RETRIEVAL_DOCUMENT" or "RETRIEVAL_QUERY"
    domain: Domain = "CHAT",
    model: Optional[str] = None,
) -> GeminiEmbedResult:
    """
    Generate vector embeddings for input texts using Gemini embedding models.
    Supports batching (max 50 texts per API call), L2 normalization,
    graceful task_type fallback, and key rotation.
    """
    global _TASK_TYPE_REJECTED_LOGGED
    settings = get_settings()
    model_to_use = model or settings.GEMINI_EMBEDDING_MODEL

    if not texts:
        return GeminiEmbedResult(
            vectors=[],
            model_used=model_to_use,
            key_slot=1,
            latency_ms=0.0,
        )

    base_timeout = settings.GEMINI_REQUEST_TIMEOUT_SECONDS
    timeout_ms = int(base_timeout * 1000)

    # Process in batches of at most 50
    batch_size = 50
    batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]

    all_vectors: list[list[float]] = []
    last_key_slot = 1
    t_start = time.monotonic()

    for batch in batches:
        async def _call(api_key: str) -> list[list[float]]:
            global _TASK_TYPE_REJECTED_LOGGED
            client = genai.Client(
                api_key=api_key,
                http_options=genai_types.HttpOptions(timeout=timeout_ms),
            )

            # Attempt 1: with task_type if not previously rejected
            use_task_type = task_type if not _TASK_TYPE_REJECTED_LOGGED else None
            config_kwargs: dict = {}
            if settings.EMBEDDING_DIMENSIONS:
                config_kwargs["output_dimensionality"] = settings.EMBEDDING_DIMENSIONS
            if use_task_type:
                config_kwargs["task_type"] = use_task_type

            config = genai_types.EmbedContentConfig(**config_kwargs) if config_kwargs else None

            try:
                response = await client.aio.models.embed_content(
                    model=model_to_use,
                    contents=batch,
                    config=config,
                )
            except APIError as api_err:
                from app.core.key_manager import classify_exception
                err_class = classify_exception(api_err)
                if err_class == "model_not_found":
                    raise

                msg = str(api_err).lower()
                # If rejected due to task_type, retry without it
                if use_task_type and ("task_type" in msg or "task type" in msg or "invalid_argument" in msg):
                    if not _TASK_TYPE_REJECTED_LOGGED:
                        logger.warning(
                            "[GeminiClient] Embedding model '%s' rejected task_type '%s'; retrying without task_type.",
                            model_to_use, task_type
                        )
                        _TASK_TYPE_REJECTED_LOGGED = True
                    fallback_kwargs = {}
                    if settings.EMBEDDING_DIMENSIONS:
                        fallback_kwargs["output_dimensionality"] = settings.EMBEDDING_DIMENSIONS
                    fallback_config = genai_types.EmbedContentConfig(**fallback_kwargs) if fallback_kwargs else None
                    response = await client.aio.models.embed_content(
                        model=model_to_use,
                        contents=batch,
                        config=fallback_config,
                    )
                else:
                    raise

            # Extract vectors
            batch_vectors: list[list[float]] = []
            raw_embeddings = getattr(response, "embeddings", None)
            if raw_embeddings:
                for emb in raw_embeddings:
                    vals = getattr(emb, "values", None)
                    if vals is not None:
                        batch_vectors.append(_l2_normalize(list(vals)))

            if not batch_vectors or len(batch_vectors) != len(batch):
                raise EmptyGeminiResponseError(
                    model=model_to_use,
                    reason=f"Expected {len(batch)} embeddings, received {len(batch_vectors)}",
                )

            return batch_vectors

        keyed = await run_with_key_rotation(domain=domain, operation=_call)
        last_key_slot = keyed.key_slot
        all_vectors.extend(keyed.result)

    latency_ms = (time.monotonic() - t_start) * 1000
    logger.info(
        "[GeminiClient] Embedded %d texts via model=%s key_slot=%d latency=%.0fms",
        len(texts), model_to_use, last_key_slot, latency_ms
    )

    return GeminiEmbedResult(
        vectors=all_vectors,
        model_used=model_to_use,
        key_slot=last_key_slot,
        latency_ms=round(latency_ms, 1),
    )

