"""
backend/app/knowledge/store.py

ChromaDB persistent vector store for KisaanDost (FarmAI).
Maintains collection 'farm_knowledge' with cosine distance, metadata safeguards,
and idempotent upsert/query operations.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import get_settings
from app.knowledge.chunker import KnowledgeChunk

logger = logging.getLogger(__name__)

COLLECTION_NAME = "farm_knowledge"
_client: Optional[chromadb.PersistentClient] = None


def get_client() -> chromadb.PersistentClient:
    """Return a singleton ChromaDB PersistentClient pointing to resolved_chroma_path."""
    global _client
    if _client is None:
        settings = get_settings()
        persist_dir = settings.resolved_chroma_path
        persist_dir.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
        )
    return _client


def get_or_create_collection():
    """
    Get or create 'farm_knowledge' collection with cosine space.
    Verifies embedding model and dimension compatibility.
    """
    client = get_client()
    settings = get_settings()

    target_metadata = {
        "hnsw:space": "cosine",
        "embedding_model": settings.GEMINI_EMBEDDING_MODEL,
        "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
    }

    try:
        collection = client.get_collection(name=COLLECTION_NAME)
        # Check metadata compatibility
        meta = collection.metadata or {}
        coll_model = meta.get("embedding_model")
        coll_dim = meta.get("embedding_dimensions")
        if coll_model and coll_model != settings.GEMINI_EMBEDDING_MODEL:
            raise ValueError(
                f"ChromaDB collection '{COLLECTION_NAME}' was created with embedding model "
                f"'{coll_model}', but settings specify '{settings.GEMINI_EMBEDDING_MODEL}'. "
                f"Cannot mix different embedding models."
            )
        if coll_dim and coll_dim != settings.EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"ChromaDB collection '{COLLECTION_NAME}' was created with dimension "
                f"{coll_dim}, but settings specify {settings.EMBEDDING_DIMENSIONS}. "
                f"Cannot mix different vector dimensions."
            )
        return collection
    except ValueError as ve:
        # Re-raise compatibility errors
        if "Cannot mix" in str(ve):
            raise
        # Collection does not exist -> create it
        return client.create_collection(name=COLLECTION_NAME, metadata=target_metadata)
    except Exception:
        # Collection does not exist -> create it
        return client.create_collection(name=COLLECTION_NAME, metadata=target_metadata)


def upsert_chunks(chunks: list[KnowledgeChunk], vectors: list[list[float]]) -> int:
    """
    Idempotently upsert knowledge chunks with their vector embeddings into ChromaDB.
    Deletes old chunks for any source_file being updated.

    Args:
        chunks: List of KnowledgeChunk objects.
        vectors: Corresponding list of embedding vectors.

    Returns:
        Number of chunks upserted.
    """
    if not chunks:
        return 0

    if len(chunks) != len(vectors):
        raise ValueError(
            f"Chunk count ({len(chunks)}) does not match vector count ({len(vectors)})"
        )

    collection = get_or_create_collection()

    # Determine unique source files being updated
    source_files = list(set(c.source_file for c in chunks))

    # Delete existing records for these source files to ensure clean update
    for src in source_files:
        try:
            collection.delete(where={"source_file": src})
        except Exception as exc:
            logger.debug("[Store] Delete prior chunks for %s notice: %s", src, exc)

    # Prepare deterministic IDs, documents, embeddings, and metadatas
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for c in chunks:
        # Deterministic ID: sha256 of source_file + chunk_index + text
        raw_id = f"{c.source_file}:{c.chunk_index}:{c.text}"
        chunk_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]
        ids.append(chunk_id)
        documents.append(c.text)
        metadatas.append({
            "crop": c.crop,
            "source_file": c.source_file,
            "heading_path": c.heading_path,
            "chunk_index": c.chunk_index,
        })

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=vectors,
        metadatas=metadatas,
    )

    logger.info("[Store] Upserted %d chunk(s) across %d file(s)", len(chunks), len(source_files))
    return len(chunks)


def query(
    vector: list[float],
    top_k: int = 3,
    crop: Optional[str] = None,
) -> list[dict]:
    """
    Query the vector store for most similar chunks.

    Args:
        vector: Query embedding vector.
        top_k: Maximum chunks to retrieve.
        crop: Optional crop name filter (e.g. 'cotton').

    Returns:
        List of result dicts: text, crop, source_file, heading_path, score.
    """
    try:
        collection = get_or_create_collection()
    except Exception as exc:
        logger.warning("[Store] Could not access collection: %s", exc)
        return []

    total_count = collection.count()
    if total_count == 0:
        logger.warning("[Store] Collection '%s' is empty.", COLLECTION_NAME)
        return []

    where = {"crop": crop.lower().strip()} if crop else None
    n_results = min(top_k, total_count)

    try:
        query_args = {
            "query_embeddings": [vector],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_args["where"] = where

        res = collection.query(**query_args)
    except Exception as exc:
        logger.error("[Store] Query execution failed: %s", exc)
        return []

    results: list[dict] = []
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    distances = res.get("distances", [[]])[0]

    for doc, meta, dist in zip(docs, metas, distances):
        # In cosine distance: d in [0, 2], where 0 is identical and 2 is opposite.
        # Similarity score s = max(0.0, 1.0 - d)
        similarity = max(0.0, round(1.0 - float(dist), 4))
        results.append({
            "text": doc,
            "crop": meta.get("crop", ""),
            "source_file": meta.get("source_file", ""),
            "heading_path": meta.get("heading_path", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "score": similarity,
        })

    return results


def stats() -> dict:
    """
    Return collection statistics including total chunks, per-crop counts,
    embedding model, and ready status.
    """
    try:
        collection = get_or_create_collection()
        total = collection.count()
        meta = collection.metadata or {}

        crop_counts: dict[str, int] = {}
        if total > 0:
            all_records = collection.get(include=["metadatas"])
            for m in all_records.get("metadatas", []):
                if m:
                    c = m.get("crop", "unknown")
                    crop_counts[c] = crop_counts.get(c, 0) + 1

        settings = get_settings()
        return {
            "total_chunks": total,
            "crop_counts": crop_counts,
            "embedding_model": meta.get("embedding_model", settings.GEMINI_EMBEDDING_MODEL),
            "embedding_dimensions": meta.get("embedding_dimensions", settings.EMBEDDING_DIMENSIONS),
            "ready": total > 0,
        }
    except Exception as exc:
        logger.warning("[Store] Stats lookup failed: %s", exc)
        settings = get_settings()
        return {
            "total_chunks": 0,
            "crop_counts": {},
            "embedding_model": settings.GEMINI_EMBEDDING_MODEL,
            "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
            "ready": False,
        }

