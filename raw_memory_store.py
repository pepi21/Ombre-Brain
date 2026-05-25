# ============================================================
# Module: Raw Memory Store (raw_memory_store.py)
# 模块：原话保留层
#
# Append-only storage for raw conversation content.
# 只追加不修改的原始对话内容存储。
#
# Design:
#   - SQLite table: raw_memories
#   - Never dehydrated, never merged, never decayed, never archived
#   - Provides full-text search for recall
#   - Linked to bucket IDs for cross-reference
#
# Depended on by: server.py
# ============================================================

import os
import json
import sqlite3
import logging
from datetime import datetime

from utils import now_iso

logger = logging.getLogger("ombre_brain.raw_store")


class RawMemoryStore:
    """
    Append-only raw memory store.
    原话保留层 — 只追加，不修改，不删除，不参与任何压缩/合并/衰减。
    """

    def __init__(self, config: dict):
        db_path = os.path.join(config["buckets_dir"], "raw_memories.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create raw_memories table and FTS virtual table if not exists."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'user',
                timestamp TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 5,
                tags TEXT DEFAULT '[]',
                valence REAL DEFAULT 0.5,
                arousal REAL DEFAULT 0.3,
                actor TEXT DEFAULT '',
                target TEXT DEFAULT '',
                action TEXT DEFAULT '',
                related_bucket_ids TEXT DEFAULT '[]'
            )
        """)
        # FTS5 virtual table for full-text search
        # Check if FTS table exists first
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_memories_fts'"
        ).fetchone()
        if not row:
            conn.execute("""
                CREATE VIRTUAL TABLE raw_memories_fts USING fts5(
                    content,
                    actor,
                    target,
                    content='raw_memories',
                    content_rowid='id'
                )
            """)
            # Triggers to keep FTS in sync
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS raw_memories_ai AFTER INSERT ON raw_memories BEGIN
                    INSERT INTO raw_memories_fts(rowid, content, actor, target)
                    VALUES (new.id, new.content, new.actor, new.target);
                END
            """)
        conn.commit()
        conn.close()

    def store(
        self,
        content: str,
        source: str = "user",
        importance: int = 5,
        tags: list[str] = None,
        valence: float = 0.5,
        arousal: float = 0.3,
        actor: str = "",
        target: str = "",
        action: str = "",
    ) -> int:
        """
        Append a raw memory entry. Returns the row ID.
        追加一条原话记录，返回行 ID。
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """INSERT INTO raw_memories
               (content, source, timestamp, importance, tags, valence, arousal, actor, target, action, related_bucket_ids)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                content,
                source,
                now_iso(),
                max(1, min(10, importance)),
                json.dumps(tags or [], ensure_ascii=False),
                max(0.0, min(1.0, valence)),
                max(0.0, min(1.0, arousal)),
                actor or "",
                target or "",
                action or "",
                "[]",
            ),
        )
        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"Raw memory stored: id={row_id}, source={source}, actor={actor}, target={target}")
        return row_id

    def link_bucket(self, raw_id: int, bucket_id: str):
        """
        Link a raw memory to a bucket (after merge/create).
        将原话记录关联到桶 ID（合并/新建后调用）。
        """
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT related_bucket_ids FROM raw_memories WHERE id = ?", (raw_id,)
        ).fetchone()
        if row:
            try:
                ids = json.loads(row[0]) if row[0] else []
            except json.JSONDecodeError:
                ids = []
            if bucket_id not in ids:
                ids.append(bucket_id)
            conn.execute(
                "UPDATE raw_memories SET related_bucket_ids = ? WHERE id = ?",
                (json.dumps(ids, ensure_ascii=False), raw_id),
            )
            conn.commit()
        conn.close()

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """
        Full-text search raw memories. Returns list of dicts.
        全文搜索原话层，返回字典列表。
        """
        if not query or not query.strip():
            return []

        conn = sqlite3.connect(self.db_path)
        # Use FTS5 MATCH for search; fall back to LIKE if FTS fails
        results = []
        try:
            # FTS5 query: escape special chars
            safe_query = query.replace('"', '""')
            rows = conn.execute(
                """SELECT r.id, r.content, r.source, r.timestamp, r.importance,
                          r.tags, r.valence, r.arousal, r.actor, r.target, r.action,
                          r.related_bucket_ids
                   FROM raw_memories r
                   JOIN raw_memories_fts f ON r.id = f.rowid
                   WHERE raw_memories_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (f'"{safe_query}"', limit),
            ).fetchall()
        except Exception:
            # Fallback to LIKE search
            rows = conn.execute(
                """SELECT id, content, source, timestamp, importance,
                          tags, valence, arousal, actor, target, action,
                          related_bucket_ids
                   FROM raw_memories
                   WHERE content LIKE ?
                   ORDER BY importance DESC, timestamp DESC
                   LIMIT ?""",
                (f"%{query}%", limit),
            ).fetchall()

        for row in rows:
            results.append({
                "id": row[0],
                "content": row[1],
                "source": row[2],
                "timestamp": row[3],
                "importance": row[4],
                "tags": json.loads(row[5]) if row[5] else [],
                "valence": row[6],
                "arousal": row[7],
                "actor": row[8],
                "target": row[9],
                "action": row[10],
                "related_bucket_ids": json.loads(row[11]) if row[11] else [],
            })
        conn.close()
        return results

    def get_recent(self, limit: int = 10) -> list[dict]:
        """
        Get most recent raw memories.
        获取最近的原话记录。
        """
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT id, content, source, timestamp, importance,
                      tags, valence, arousal, actor, target, action,
                      related_bucket_ids
               FROM raw_memories
               ORDER BY id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "content": row[1],
                "source": row[2],
                "timestamp": row[3],
                "importance": row[4],
                "tags": json.loads(row[5]) if row[5] else [],
                "valence": row[6],
                "arousal": row[7],
                "actor": row[8],
                "target": row[9],
                "action": row[10],
                "related_bucket_ids": json.loads(row[11]) if row[11] else [],
            })
        return results

    def get_by_importance(self, min_importance: int = 8, limit: int = 20) -> list[dict]:
        """
        Get raw memories with importance >= threshold.
        获取重要度达标的原话记录。
        """
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT id, content, source, timestamp, importance,
                      tags, valence, arousal, actor, target, action,
                      related_bucket_ids
               FROM raw_memories
               WHERE importance >= ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (min_importance, limit),
        ).fetchall()
        conn.close()
        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "content": row[1],
                "source": row[2],
                "timestamp": row[3],
                "importance": row[4],
                "tags": json.loads(row[5]) if row[5] else [],
                "valence": row[6],
                "arousal": row[7],
                "actor": row[8],
                "target": row[9],
                "action": row[10],
                "related_bucket_ids": json.loads(row[11]) if row[11] else [],
            })
        return results

    def count(self) -> int:
        """Total number of raw memories."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT COUNT(*) FROM raw_memories").fetchone()
        conn.close()
        return row[0] if row else 0
