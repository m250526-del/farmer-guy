"""
backend/app/api/knowledge.py

Diagnostic endpoints for inspecting and searching the RAG knowledge store.

Endpoints:
  GET /knowledge-status  — chunk counts, model info, ready status
  GET /knowledge-search  — test vector retrieval and context formatting

SECURITY:
  - Both endpoints return 404 when settings.ENVIRONMENT == "production".
  - /knowledge-status returns metadata only (no document text).
  - All errors pass through scrub_secrets().
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.core.exceptions import (
    AllKeysExhaustedError,
    EmptyGeminiResponseError,
    GeminiUnavailableError,
    NoKeysConfiguredError,
)
from app.core.key_manager import _get_all_configured_keys, classify_exception, scrub_secrets
from app.knowledge import retriever, store
from app.knowledge.context import format_context

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Knowledge & RAG"])


def _require_dev() -> None:
    """Raise 404 if running in production."""
    if get_settings().ENVIRONMENT == "production":
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/knowledge-status")
async def knowledge_status() -> dict:
    """
    Returns statistics of the vector knowledge store:
    total chunks, per-crop counts, embedding model, and ready flag.
    Disabled in production (returns 404). Never exposes document text.
    """
    _require_dev()
    return store.stats()


@router.get("/knowledge-search")
async def knowledge_search(
    q: str = Query(..., min_length=1, max_length=500, description="Farmer query text"),
    crop: Optional[str] = Query(None, description="Optional crop filter, e.g. cotton"),
    top_k: int = Query(default=3, ge=1, le=10, description="Number of chunks (1-10)"),
) -> dict:
    """
    Search the RAG store for knowledge chunks relevant to `q`.
    Returns retrieved chunks and length of the formatted prompt context.
    Disabled in production (returns 404).
    """
    _require_dev()

    all_keys = _get_all_configured_keys()

    # Validate crop if provided
    clean_crop = crop.strip().lower() if crop else None
    if clean_crop:
        current_stats = store.stats()
        known_crops = set(c.lower() for c in current_stats.get("crop_counts", {}).keys())
        if known_crops and clean_crop not in known_crops:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown crop '{crop}'. Available crops: {sorted(list(known_crops))}",
            )

    # Check for empty store
    current_stats = store.stats()
    if current_stats["total_chunks"] == 0:
        return {
            "status": "ok",
            "query": q,
            "crop": clean_crop,
            "results": [],
            "context_chars": 0,
            "hint": "The knowledge base is empty. Run 'python scripts/ingest_knowledge.py' from backend/ to ingest crop manuals.",
        }

    try:
        results = await retriever.retrieve(
            query=q,
            crop=clean_crop,
            top_k=top_k,
        )
        context_str = format_context(results)
        return {
            "status": "ok",
            "query": q,
            "crop": clean_crop,
            "top_k": top_k,
            "results_count": len(results),
            "results": results,
            "context_chars": len(context_str),
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
        logger.exception("[KnowledgeAPI] /knowledge-search error (class=%s)", err_class)
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

