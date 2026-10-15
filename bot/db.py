"""SQLite storage for scheduled posts."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,              -- text | photo | video
    text        TEXT,                       -- message text or caption
    entities    TEXT,                       -- JSON list of Telegram message entities
    file_id     TEXT,                       -- photo/video file_id
    send_at     TEXT NOT NULL,              -- ISO-8601 UTC
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | failed | cancelled
    created_by  INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_due ON posts(status, send_at);
"""


@dataclass
class Post:
    id: int
    kind: str
    text: str | None
    entities: list[dict]
    file_id: str | None
    send_at: datetime
    status: str
    created_by: int


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def add_post(self, kind: str, text: str | None, entities: list[dict], file_id: str | None,
                 send_at: datetime, created_by: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO posts (kind, text, entities, file_id, send_at, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, text, json.dumps(entities, ensure_ascii=False), file_id,
             _to_utc_iso(send_at), created_by, _to_utc_iso(datetime.now(timezone.utc))),
        )
        self.conn.commit()
        return cur.lastrowid

    def pending(self) -> list[Post]:
        rows = self.conn.execute(
            "SELECT * FROM posts WHERE status = 'pending' ORDER BY send_at, id"
        ).fetchall()
        return [_row_to_post(r) for r in rows]

    def due(self, now: datetime) -> list[Post]:
        rows = self.conn.execute(
            "SELECT * FROM posts WHERE status = 'pending' AND send_at <= ? ORDER BY send_at, id",
            (_to_utc_iso(now),),
        ).fetchall()
        return [_row_to_post(r) for r in rows]

    def cancel(self, post_id: int) -> bool:
        cur = self.conn.execute(
            "UPDATE posts SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (post_id,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_sent(self, post_id: int) -> None:
        self.conn.execute("UPDATE posts SET status = 'sent' WHERE id = ?", (post_id,))
        self.conn.commit()

    def mark_failed(self, post_id: int, error: str) -> None:
        self.conn.execute("UPDATE posts SET status = 'failed', error = ? WHERE id = ?", (error, post_id))
        self.conn.commit()


def _to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _row_to_post(row: sqlite3.Row) -> Post:
    return Post(
        id=row["id"],
        kind=row["kind"],
        text=row["text"],
        entities=json.loads(row["entities"] or "[]"),
        file_id=row["file_id"],
        send_at=datetime.strptime(row["send_at"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc),
        status=row["status"],
        created_by=row["created_by"],
    )
