"""
backend/scripts/ingest_knowledge.py

Stand-alone CLI script to ingest crop knowledge markdown documents into ChromaDB.
Usage:
    cd backend
    python scripts/ingest_knowledge.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.core.key_manager import init_pools
from app.knowledge.ingest import ingest_all
from app.knowledge.store import stats


async def main():
    print("🌾 KisaanDost (FarmAI) — Knowledge Ingestion")
    print("=" * 50)

    # Step 1: Initialise key pools
    print("1. Initialising API key pools...")
    await init_pools()

    # Step 2: Run ingestion
    print("2. Ingesting markdown documents from app/knowledge/docs/...")
    summary = await ingest_all()

    # Step 3: Print summary
    print("\n" + "=" * 50)
    print("📊 Ingestion Summary:")
    print(f"  Files processed: {summary['files_processed']}")
    print(f"  Files skipped:   {summary['files_skipped']}")
    print(f"  Chunks ingested: {summary['chunks_ingested']}")

    if summary["errors"]:
        print("\n⚠️ Errors encountered:")
        for err in summary["errors"]:
            print(f"  - {err}")
    else:
        print("  Status: All documents ingested successfully!")

    # Step 4: Collection stats
    print("\n📦 Collection Statistics:")
    current_stats = stats()
    print(f"  Total chunks in ChromaDB: {current_stats['total_chunks']}")
    print(f"  Embedding model:          {current_stats['embedding_model']}")
    print(f"  Dimensions:               {current_stats['embedding_dimensions']}")
    print(f"  Per-crop breakdown:")
    for crop, count in sorted(current_stats["crop_counts"].items()):
        print(f"    - {crop}: {count} chunk(s)")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())

