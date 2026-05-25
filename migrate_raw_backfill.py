#!/usr/bin/env python3
"""
Migration script: Backfill raw_memories from existing buckets.
迁移脚本：从现有桶内容回填到原话保留层。

Usage:
  python migrate_raw_backfill.py
  python migrate_raw_backfill.py --dry-run   # Preview without writing

This scans all existing bucket .md files, extracts their content,
and inserts them into raw_memories.db preserving original timestamps.
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import frontmatter
from utils import load_config, setup_logging
from raw_memory_store import RawMemoryStore

setup_logging("INFO")


def main():
    parser = argparse.ArgumentParser(description="Backfill raw_memories from existing buckets")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    config = load_config()
    raw_store = RawMemoryStore(config)
    base_dir = config["buckets_dir"]

    total = 0
    skipped = 0
    backfilled = 0

    for type_dir in ["permanent", "dynamic", "archive", "feel"]:
        dir_path = os.path.join(base_dir, type_dir)
        if not os.path.exists(dir_path):
            continue
        for root, _, files in os.walk(dir_path):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                total += 1
                file_path = os.path.join(root, fname)
                try:
                    post = frontmatter.load(file_path)
                    content = post.content
                    if not content or not content.strip():
                        skipped += 1
                        continue

                    bucket_id = post.get("id", "")
                    timestamp = post.get("created", "")
                    importance = post.get("importance", 5)
                    tags = post.get("tags", [])
                    valence = post.get("valence", 0.5)
                    arousal = post.get("arousal", 0.3)
                    actor = post.get("actor", "")
                    target = post.get("target", "")
                    action = post.get("action", "")

                    # Determine source based on type
                    bucket_type = post.get("type", "dynamic")
                    if bucket_type == "feel":
                        source = "model_feel"
                    else:
                        source = "user"

                    if args.dry_run:
                        print(f"  [DRY] Would backfill: {bucket_id} ({post.get('name', '?')[:30]})")
                    else:
                        raw_id = raw_store.store(
                            content=content,
                            source=source,
                            importance=importance,
                            tags=tags,
                            valence=valence,
                            arousal=arousal,
                            actor=actor,
                            target=target,
                            action=action,
                        )
                        raw_store.link_bucket(raw_id, bucket_id)
                    backfilled += 1

                except Exception as e:
                    print(f"  [ERROR] {fname}: {e}")
                    skipped += 1

    print(f"\n=== Migration {'(DRY RUN) ' if args.dry_run else ''}Complete ===")
    print(f"Total buckets scanned: {total}")
    print(f"Backfilled: {backfilled}")
    print(f"Skipped (empty/error): {skipped}")
    if not args.dry_run:
        print(f"Raw memories count: {raw_store.count()}")


if __name__ == "__main__":
    main()
