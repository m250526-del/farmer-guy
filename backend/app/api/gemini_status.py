"""
backend/app/api/gemini_status.py

Diagnostic endpoints for inspecting and testing the Gemini key pools.

Endpoints:
  GET /gemini-status          — pool sizes and model lists (always available)
  GET /gemini-test            — live key test for one domain (dev only)
  GET /gemini-models-check    — test each model individually (dev only)

SECURITY:
  - No key values, no partial key values, no key hashes are ever returned.
  - All exception texts are scrubbed before returning.
  - /gemini-test and /gemini-models-check return 404 in production.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.core.exceptions import (
    AllKeysExhaustedError,
    EmptyGeminiResponseError,
    GeminiUnavailableError,
    NoKeysConfiguredError,
)
from app.core.key_manager import (
    Domain,
    _get_all_configured_keys,
    _get_pool,
    classify_exception,
    scrub_secrets,
)
from app.core.models import get_text_models, get_tts_models, get_stt_models
from app.services.gemini_client import generate_text

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Gemini Status"])

_TEST_PROMPT = "Reply with exactly: OK"
_VALID_DOMAINS: list[Domain] = ["CHAT", "STT", "TTS"]


def _require_dev() -> None:
    """Raise 404 if running in production (endpoint disabled)."""
    if get_settings().ENVIRONMENT == "production":
        raise HTTPException(status_code=404, detail="Not found")


def _pool_info(domain: Domain) -> dict:
    """Return safe info about a pool (count + fallback flag only)."""
    try:
        pool = _get_pool(domain)
        settings = get_settings()
        domain_keys = [
            getattr(settings, f"GEMINI_{domain}_KEY_{i}", None)
            for i in (1, 2, 3)
        ]
        has_dedicated = any(k and k.strip() for k in domain_keys)
        fallback_in_use = (not has_dedicated) and bool(
            settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip()
        )
        return {
            "keys_configured": pool.size,
            "fallback_key_in_use": fallback_in_use,
        }
    except RuntimeError:
        return {"keys_configured": 0, "fallback_key_in_use": False, "error": "pools_not_initialised"}


@router.get("/gemini-status")
async def gemini_status() -> dict:
    """
    Returns the number of keys configured per domain and the effective
    model lists (after GEMINI_MODEL / GEMINI_TTS_MODEL overrides).
    Never returns key values.
    """
    return {
        "pools": {
            "CHAT": _pool_info("CHAT"),
            "STT":  _pool_info("STT"),
            "TTS":  _pool_info("TTS"),
        },
        "models": {
            "text": get_text_models(),
            "tts":  get_tts_models(),
            "stt":  get_stt_models(),
        },
    }


@router.get("/gemini-test")
async def gemini_test(
    domain: Literal["CHAT", "STT", "TTS"] = Query(default="CHAT"),
) -> dict:
    """
    Send a tiny test prompt using the specified domain's key pool.
    Verifies pool keys are live; does NOT test voice features.
    Disabled in production (returns 404).
    """
    _require_dev()

    if domain not in _VALID_DOMAINS:
        raise HTTPException(status_code=400, detail=f"domain must be one of {_VALID_DOMAINS}")

    all_keys = _get_all_configured_keys()

    try:
        result = await generate_text(
            prompt=_TEST_PROMPT,
            domain=domain,  # type: ignore[arg-type]
        )
        return {
            "status": "ok",
            "domain": domain,
            "model_used": result.model_used,
            "key_slot_used": result.key_slot,
            "latency_ms": result.latency_ms,
            "reply_preview": result.text[:40],
        }

    except NoKeysConfiguredError as exc:
        safe_msg = scrub_secrets(str(exc), all_keys)[:300]
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "error_type": "no_keys_configured", "detail": safe_msg, "attempts": []},
        )

    except AllKeysExhaustedError as exc:
        attempts = [
            {
                "slot": a.slot,
                "error_class": a.error_class,
                "exception_type": a.exception_type,
                "message": a.message,
            }
            for a in exc.attempts
        ]
        safe_msg = scrub_secrets(str(exc), all_keys)[:300]
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "error_type": "all_keys_exhausted", "detail": safe_msg, "attempts": attempts},
        )

    except GeminiUnavailableError as exc:
        safe_msg = scrub_secrets(str(exc), all_keys)[:300]
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "error_type": "gemini_unavailable",
                "detail": safe_msg,
                "attempts": exc.model_attempts,
            },
        )

    except EmptyGeminiResponseError as exc:
        safe_msg = scrub_secrets(str(exc), all_keys)[:300]
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "error_type": "empty_response", "detail": safe_msg, "attempts": []},
        )

    except Exception as exc:
        err_class = classify_exception(exc)
        safe_msg = scrub_secrets(str(exc), all_keys)[:300]
        logger.exception("[GeminiStatus] /gemini-test unexpected error (class=%s)", err_class)
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "error_type": err_class,
                "detail": safe_msg,
                "attempts": [{
                    "error_class": err_class,
                    "exception_type": type(exc).__name__,
                    "message": safe_msg,
                }],
            },
        )


@router.get("/gemini-models-check")
async def gemini_models_check(
    domain: Literal["CHAT", "STT", "TTS"] = Query(default="CHAT"),
) -> dict:
    """
    Test EACH text model individually (no cross-model fallback).
    Returns a list showing which models are alive.
    Limited to text models for Stage 2.
    Disabled in production (returns 404).
    """
    _require_dev()

    if domain not in _VALID_DOMAINS:
        raise HTTPException(status_code=400, detail=f"domain must be one of {_VALID_DOMAINS}")

    all_keys = _get_all_configured_keys()
    model_list = get_text_models()
    results = []

    for model in model_list:
        try:
            await generate_text(
                prompt=_TEST_PROMPT,
                domain=domain,  # type: ignore[arg-type]
                models=[model],  # one model only — no fallback
            )
            results.append({
                "model": model,
                "working": True,
                "error_type": None,
                "exception_type": None,
                "message": None,
            })

        except (NoKeysConfiguredError, AllKeysExhaustedError) as exc:
            # Key problem — fail fast
            safe_msg = scrub_secrets(str(exc), all_keys)[:300]
            raise HTTPException(
                status_code=400 if isinstance(exc, NoKeysConfiguredError) else 503,
                detail=safe_msg,
            )

        except GeminiUnavailableError as exc:
            attempt = exc.model_attempts[0] if exc.model_attempts else {}
            results.append({
                "model": model,
                "working": False,
                "error_type": attempt.get("error_class", "unknown"),
                "exception_type": attempt.get("exception_type", type(exc).__name__),
                "message": attempt.get("message", scrub_secrets(str(exc), all_keys)[:300]),
            })

        except EmptyGeminiResponseError as exc:
            safe_msg = scrub_secrets(str(exc), all_keys)[:300]
            results.append({
                "model": model,
                "working": False,
                "error_type": "empty_response",
                "exception_type": type(exc).__name__,
                "message": safe_msg,
            })

        except Exception as exc:
            err_class = classify_exception(exc)
            safe_msg = scrub_secrets(str(exc), all_keys)[:300]
            results.append({
                "model": model,
                "working": False,
                "error_type": err_class,
                "exception_type": type(exc).__name__,
                "message": safe_msg,
            })

    return {"domain": domain, "models": results}
