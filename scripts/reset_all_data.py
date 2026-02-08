"""Reset all GraphRecall data stores for a clean slate.

Clears:
1. PostgreSQL — all user-generated rows (notes, chunks, flashcards, quizzes, etc.)
2. Neo4j — all Concept nodes, NoteSource nodes, and relationships
3. S3/Supabase Storage — all uploaded files in the bucket

Usage:
  python scripts/reset_all_data.py                    # Interactive confirmation
  python scripts/reset_all_data.py --yes               # Skip confirmation
  python scripts/reset_all_data.py --keep-users         # Keep user accounts, clear everything else
  python scripts/reset_all_data.py --postgres-only      # Only clear PostgreSQL
  python scripts/reset_all_data.py --neo4j-only         # Only clear Neo4j
  python scripts/reset_all_data.py --storage-only       # Only clear S3 storage
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

logger = structlog.get_logger()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset all GraphRecall data stores")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--keep-users", action="store_true", help="Keep user accounts, clear everything else")
    parser.add_argument("--postgres-only", action="store_true", help="Only clear PostgreSQL")
    parser.add_argument("--neo4j-only", action="store_true", help="Only clear Neo4j")
    parser.add_argument("--storage-only", action="store_true", help="Only clear S3 storage")
    return parser.parse_args()


async def reset_postgres(keep_users: bool = False):
    """Clear all PostgreSQL tables in dependency order."""
    from backend.db.postgres_client import get_postgres_client

    pg = await get_postgres_client()

    # Order matters: delete child tables before parent tables (FK constraints)
    tables_to_clear = [
        # Chat & saved data
        "saved_responses",
        "chat_messages",
        "chat_conversations",
        # Learning analytics
        "study_sessions",
        "daily_stats",
        # Generated content
        "generated_content",
        "rag_citations",
        # Study content
        "flashcards",
        "quizzes",
        # Concept tracking
        "proficiency_scores",
        "concept_review_sessions",
        "community_nodes",
        "communities",
        # Content hierarchy
        "propositions",
        "chunks",
        "notes",
        # Uploads
        "user_uploads",
    ]

    if not keep_users:
        tables_to_clear.append("users")

    cleared = 0
    for table in tables_to_clear:
        try:
            result = await pg.execute_query(f"SELECT COUNT(*) as cnt FROM {table}")
            count = result[0]["cnt"] if result else 0

            if count > 0:
                await pg.execute_update(f"TRUNCATE TABLE {table} CASCADE")
                logger.info(f"  Cleared {table}", rows_deleted=count)
                cleared += count
            else:
                logger.info(f"  {table} already empty")
        except Exception as e:
            # Table might not exist yet
            logger.warning(f"  Skipped {table}", error=str(e))

    logger.info("PostgreSQL reset complete", total_rows_cleared=cleared)
    return cleared


async def reset_neo4j():
    """Delete all nodes and relationships in Neo4j."""
    from backend.db.neo4j_client import get_neo4j_client

    neo4j = await get_neo4j_client()

    # Count before
    try:
        count_result = await neo4j.execute_query("MATCH (n) RETURN count(n) AS cnt")
        node_count = count_result[0]["cnt"] if count_result else 0

        rel_result = await neo4j.execute_query("MATCH ()-[r]->() RETURN count(r) AS cnt")
        rel_count = rel_result[0]["cnt"] if rel_result else 0

        logger.info(f"  Neo4j before: {node_count} nodes, {rel_count} relationships")
    except Exception:
        node_count = 0
        rel_count = 0

    # Delete in batches to avoid memory issues with large graphs
    try:
        # Delete all relationships first, then nodes (in batches)
        batch_size = 1000
        deleted_total = 0

        while True:
            result = await neo4j.execute_write(
                f"MATCH (n) WITH n LIMIT {batch_size} DETACH DELETE n RETURN count(*) AS deleted"
            )
            deleted = result[0]["deleted"] if result else 0
            if deleted == 0:
                break
            deleted_total += deleted
            logger.info(f"  Deleted batch of {deleted} nodes...")

        logger.info("Neo4j reset complete", nodes_deleted=node_count, relationships_deleted=rel_count)
    except Exception as e:
        logger.error("Neo4j reset failed", error=str(e))
        raise

    return node_count


async def reset_storage():
    """Clear all files from S3/Supabase storage bucket."""
    from backend.services.storage_service import get_storage_service

    storage = get_storage_service()

    try:
        # List all objects in the bucket
        bucket = storage.bucket_name
        s3 = storage.s3_client

        deleted = 0
        continuation_token = None

        while True:
            list_kwargs = {"Bucket": bucket, "MaxKeys": 1000}
            if continuation_token:
                list_kwargs["ContinuationToken"] = continuation_token

            response = s3.list_objects_v2(**list_kwargs)
            contents = response.get("Contents", [])

            if not contents:
                break

            # Batch delete
            objects = [{"Key": obj["Key"]} for obj in contents]
            delete_response = s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": objects, "Quiet": True},
            )
            errors = delete_response.get("Errors", [])
            if errors:
                for err in errors:
                    logger.warning("  Failed to delete", key=err["Key"], error=err["Message"])

            deleted += len(objects) - len(errors)
            logger.info(f"  Deleted {len(objects)} files from storage...")

            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")

        logger.info("Storage reset complete", files_deleted=deleted)
        return deleted

    except Exception as e:
        logger.error("Storage reset failed", error=str(e))
        # Storage might not be configured — don't fail the whole script
        logger.warning("  (This is non-fatal — storage may not be configured)")
        return 0


async def main():
    args = _parse_args()

    # Determine which stores to clear
    clear_all = not (args.postgres_only or args.neo4j_only or args.storage_only)
    clear_pg = clear_all or args.postgres_only
    clear_neo = clear_all or args.neo4j_only
    clear_s3 = clear_all or args.storage_only

    # Build summary of what will be cleared
    targets = []
    if clear_pg:
        targets.append("PostgreSQL (notes, chunks, flashcards, quizzes, chat, analytics)")
    if clear_neo:
        targets.append("Neo4j (all Concept nodes, NoteSource nodes, relationships)")
    if clear_s3:
        targets.append("S3 Storage (all uploaded files)")
    if args.keep_users:
        targets.append("(keeping user accounts)")

    print("\n" + "=" * 60)
    print("GraphRecall Data Reset")
    print("=" * 60)
    print("\nThis will PERMANENTLY DELETE:")
    for t in targets:
        print(f"  - {t}")
    print()

    if not args.yes:
        confirm = input("Type 'RESET' to confirm: ").strip()
        if confirm != "RESET":
            print("Aborted.")
            sys.exit(0)

    print()

    # Execute resets
    if clear_pg:
        print("=" * 40)
        print("Resetting PostgreSQL...")
        print("=" * 40)
        await reset_postgres(keep_users=args.keep_users)
        print()

    if clear_neo:
        print("=" * 40)
        print("Resetting Neo4j...")
        print("=" * 40)
        await reset_neo4j()
        print()

    if clear_s3:
        print("=" * 40)
        print("Resetting S3 Storage...")
        print("=" * 40)
        await reset_storage()
        print()

    print("=" * 60)
    print("RESET COMPLETE — All data stores cleared.")
    print("You can now run the book ingestion pipeline:")
    print('  python scripts/ingest_book.py --md-path "..." --images-dir "..."')
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
