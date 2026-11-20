"""
backend/app/knowledge/ingest.py

Asynchronously ingests markdown crop manuals from docs/ into ChromaDB.
Skips unchanged files based on content hash, embeds in batches, and applies
rate-limit friendly pacing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.knowledge.chunker import chunk_markdown
from app.knowledge.store import get_or_create_collection, upsert_chunks
from app.services.gemini_client import embed_texts

logger = logging.getLogger(__name__)

HASH_STORE_FILENAME = "ingest_hashes.json"


def _get_hash_file_path() -> Path:
    settings = get_settings()
    return settings.resolved_chroma_path / HASH_STORE_FILENAME


def _load_hashes() -> dict[str, str]:
    path = _get_hash_file_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_hashes(hashes: dict[str, str]) -> None:
    path = _get_hash_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("[Ingest] Could not save content hashes: %s", exc)


def _compute_file_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def ingest_all(docs_dir: Optional[Path] = None) -> dict:
    """
    Ingest all markdown files in docs/ into ChromaDB.

    Rules:
      - Reads every .md in docs/ (excluding README.md).
      - Skips files whose SHA-256 hash has not changed.
      - Chunks each modified file.
      - Embeds in batches (with 0.5s pause between batches for free-tier quotas).
      - Upserts chunks to ChromaDB.
      - One failing file does not abort remaining files.
      - Logs counts and filenames only, never document text.

    Returns:
        Summary dict: files_processed, files_skipped, chunks_ingested, errors.
    """
    target_dir = docs_dir or (Path(__file__).parent / "docs")
    if not target_dir.exists():
        logger.warning("[Ingest] Docs directory does not exist: %s", target_dir)
        return {
            "files_processed": 0,
            "files_skipped": 0,
            "chunks_ingested": 0,
            "errors": [f"Directory not found: {target_dir}"],
        }

    # Ensure collection exists and is compatible
    try:
        get_or_create_collection()
    except Exception as exc:
        logger.error("[Ingest] Collection initialization failed: %s", exc)
        return {
            "files_processed": 0,
            "files_skipped": 0,
            "chunks_ingested": 0,
            "errors": [str(exc)],
        }

    cached_hashes = _load_hashes()
    updated_hashes = dict(cached_hashes)

    md_files = [f for f in target_dir.glob("*.md") if f.name.lower() != "readme.md"]

    files_processed = 0
    files_skipped = 0
    total_chunks = 0
    errors: list[str] = []

    logger.info("[Ingest] Found %d crop markdown manual(s) in %s", len(md_files), target_dir.name)

    for md_file in sorted(md_files):
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as read_err:
            msg = f"Failed to read {md_file.name}: {read_err}"
            logger.error("[Ingest] %s", msg)
            errors.append(msg)
            continue

        file_hash = _compute_file_hash(content)
        if cached_hashes.get(md_file.name) == file_hash:
            logger.info("[Ingest] Skipping unchanged file: %s", md_file.name)
            files_skipped += 1
            continue

        logger.info("[Ingest] Processing file: %s", md_file.name)
        chunks = chunk_markdown(content, md_file.name)
        if not chunks:
            logger.warning("[Ingest] No chunks produced for %s", md_file.name)
            updated_hashes[md_file.name] = file_hash
            files_processed += 1
            continue

        texts_to_embed = [c.text for c in chunks]

        # Embed texts in batches
        try:
            # Short pause before calling Gemini for free-tier rate limits
            await asyncio.sleep(0.5)
            embed_res = await embed_texts(texts_to_embed, task_type="RETRIEVAL_DOCUMENT")
            upsert_chunks(chunks, embed_res.vectors)

            updated_hashes[md_file.name] = file_hash
            files_processed += 1
            total_chunks += len(chunks)
            logger.info(
                "[Ingest] Successfully ingested %s (%d chunks, key_slot=%d)",
                md_file.name, len(chunks), embed_res.key_slot
            )
        except Exception as ingest_err:
            msg = f"Error embedding/upserting {md_file.name}: {type(ingest_err).__name__}"
            logger.error("[Ingest] %s", msg)
            errors.append(f"{md_file.name}: {msg}")
            continue

    _save_hashes(updated_hashes)

    summary = {
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "chunks_ingested": total_chunks,
        "errors": errors,
    }
    logger.info(
        "[Ingest] Ingestion complete. Processed=%d, Skipped=%d, Chunks=%d, Errors=%d",
        files_processed, files_skipped, total_chunks, len(errors)
    )
    return summary

