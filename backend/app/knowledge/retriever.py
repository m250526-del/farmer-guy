"""
backend/app/knowledge/retriever.py

Async knowledge retriever with in-memory LRU caching of query embeddings.
Converts cosine distances to similarity scores, applies relevance filtering,
and works independently of FastAPI for Stage 5 agent tool integration.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Optional

from app.core.config import get_settings
from app.knowledge import store
from app.services.gemini_client import embed_texts

logger = logging.getLogger(__name__)

# Query vector LRU cache: normalized query string -> unit embedding vector
_query_cache: OrderedDict[str, list[float]] = OrderedDict()


def _normalize_query(query: str) -> str:
    """Normalize query text for cache key lookup."""
    return " ".join(query.strip().lower().split())


def _get_cached_vector(norm_query: str) -> Optional[list[float]]:
    global _query_cache
    if norm_query in _query_cache:
        _query_cache.move_to_end(norm_query)
        return _query_cache[norm_query]
    return None


def _cache_vector(norm_query: str, vector: list[float], max_size: int) -> None:
    global _query_cache
    _query_cache[norm_query] = vector
    _query_cache.move_to_end(norm_query)
    while len(_query_cache) > max_size:
        _query_cache.popitem(last=False)


async def retrieve(
    query: str,
    *,
    crop: Optional[str] = None,
    top_k: Optional[int] = None,
) -> list[dict]:
    """
    Retrieve relevant knowledge chunks for a farmer query.

    Args:
        query: Farmer query in any supported language.
        crop: Optional crop name filter (e.g. 'cotton').
        top_k: Number of chunks to return (defaults to settings.RAG_TOP_K).

    Returns:
        List of dicts: text, crop, source_file, heading_path, score.
        Empty store returns [] and logs warning (never crashes).
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    settings = get_settings()
    k = top_k or settings.RAG_TOP_K
    norm_query = _normalize_query(clean_query)

    # Step 1: Check in-memory query embedding cache
    query_vector = _get_cached_vector(norm_query)
    cached = query_vector is not None

    if not cached:
        # Step 2: Generate embedding via Gemini
        embed_result = await embed_texts([clean_query], task_type="RETRIEVAL_QUERY")
        if not embed_result.vectors:
            logger.warning("[Retriever] Empty embedding returned for query.")
            return []
        query_vector = embed_result.vectors[0]
        _cache_vector(norm_query, query_vector, settings.RAG_QUERY_CACHE_SIZE)
        logger.debug(
            "[Retriever] Query embedded via %s (slot=%d)",
            embed_result.model_used, embed_result.key_slot
        )
    else:
        logger.debug("[Retriever] Query embedding served from LRU cache.")

    # Step 3: Query ChromaDB store
    raw_results = store.query(
        vector=query_vector,
        top_k=k,
        crop=crop,
    )

    if not raw_results:
        return []

    # Step 4: Apply minimum relevance filter
    min_rel = settings.RAG_MIN_RELEVANCE
    filtered_results: list[dict] = []

    for r in raw_results:
        score = r.get("score", 0.0)
        if score >= min_rel:
            filtered_results.append(r)

    logger.info(
        "[Retriever] Query='%s' crop=%s returned %d chunk(s) (cached=%s)",
        clean_query[:50], crop or "all", len(filtered_results), cached
    )
    return filtered_results

