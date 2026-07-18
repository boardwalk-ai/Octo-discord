"""Async SQLite storage for settings and scheduled messages."""
from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER NOT NULL,
    key      TEXT    NOT NULL,
    value    TEXT,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    content     TEXT    NOT NULL DEFAULT '',
    card_name   TEXT,                       -- optional: post a saved card instead of/with text
    -- 'once' | 'hourly' | 'daily' | 'weekly'
    repeat      TEXT    NOT NULL DEFAULT 'once',
    next_run    TEXT    NOT NULL,          -- ISO 8601 UTC timestamp
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cards (
    guild_id     INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    title        TEXT    NOT NULL DEFAULT '',
    description  TEXT    NOT NULL DEFAULT '',
    image_url    TEXT,
    color        TEXT,
    buttons      TEXT    NOT NULL DEFAULT '[]',  -- JSON: [{"label","url"}]
    channel_id   INTEGER,                        -- where it was posted
    message_id   INTEGER,                        -- so it can be edited live
    PRIMARY KEY (guild_id, name)
);
"""


@dataclass
class Card:
    guild_id: int
    name: str
    title: str
    description: str
    image_url: str | None
    color: str | None
    buttons: str  # JSON string
    channel_id: int | None
    message_id: int | None


@dataclass
class ScheduledMessage:
    id: int
    guild_id: int
    channel_id: int
    content: str
    repeat: str
    next_run: str
    enabled: bool
    created_by: int
    card_name: str | None = None


class Database:
    def __init__(self, path: str = config.DATABASE_PATH) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        await self._migrate()

    async def _migrate(self) -> None:
        """Apply lightweight, additive schema migrations to existing databases."""
        await self._ensure_column("scheduled_messages", "card_name", "card_name TEXT")

    async def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        async with self.conn.execute(f"PRAGMA table_info({table})") as cur:
            existing = {row["name"] for row in await cur.fetchall()}
        if column not in existing:
            await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            await self.conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._conn

    # ── Settings ─────────────────────────────────────────────
    async def get_setting(self, guild_id: int, key: str) -> str | None:
        async with self.conn.execute(
            "SELECT value FROM settings WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_setting(self, guild_id: int, key: str, value: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO settings (guild_id, key, value) VALUES (?, ?, ?)
            ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value
            """,
            (guild_id, key, value),
        )
        await self.conn.commit()

    # ── Cards ────────────────────────────────────────────────
    async def upsert_card(
        self,
        guild_id: int,
        name: str,
        title: str,
        description: str,
        image_url: str | None,
        color: str | None,
        buttons_json: str,
    ) -> None:
        """Create or update a card's content, preserving where it was posted."""
        await self.conn.execute(
            """
            INSERT INTO cards (guild_id, name, title, description, image_url, color, buttons)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, name) DO UPDATE SET
                title       = excluded.title,
                description = excluded.description,
                image_url   = excluded.image_url,
                color       = excluded.color,
                buttons     = excluded.buttons
            """,
            (guild_id, name, title, description, image_url, color, buttons_json),
        )
        await self.conn.commit()

    async def get_card(self, guild_id: int, name: str) -> Card | None:
        async with self.conn.execute(
            "SELECT * FROM cards WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        ) as cur:
            row = await cur.fetchone()
        return _row_to_card(row) if row else None

    async def list_cards(self, guild_id: int) -> list[Card]:
        async with self.conn.execute(
            "SELECT * FROM cards WHERE guild_id = ? ORDER BY name",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_card(r) for r in rows]

    async def set_card_message(
        self, guild_id: int, name: str, channel_id: int, message_id: int
    ) -> None:
        await self.conn.execute(
            "UPDATE cards SET channel_id = ?, message_id = ? WHERE guild_id = ? AND name = ?",
            (channel_id, message_id, guild_id, name),
        )
        await self.conn.commit()

    async def delete_card(self, guild_id: int, name: str) -> bool:
        cur = await self.conn.execute(
            "DELETE FROM cards WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    # ── Scheduled messages ───────────────────────────────────
    async def add_schedule(
        self,
        guild_id: int,
        channel_id: int,
        content: str,
        repeat: str,
        next_run: str,
        created_by: int,
        card_name: str | None = None,
    ) -> int:
        cur = await self.conn.execute(
            """
            INSERT INTO scheduled_messages
                (guild_id, channel_id, content, card_name, repeat, next_run, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, channel_id, content, card_name, repeat, next_run, created_by),
        )
        await self.conn.commit()
        return cur.lastrowid or 0

    async def list_schedules(self, guild_id: int) -> list[ScheduledMessage]:
        async with self.conn.execute(
            "SELECT * FROM scheduled_messages WHERE guild_id = ? ORDER BY next_run",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_schedule(r) for r in rows]

    async def due_schedules(self, now_iso: str) -> list[ScheduledMessage]:
        async with self.conn.execute(
            "SELECT * FROM scheduled_messages WHERE enabled = 1 AND next_run <= ?",
            (now_iso,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_schedule(r) for r in rows]

    async def update_next_run(self, schedule_id: int, next_run: str) -> None:
        await self.conn.execute(
            "UPDATE scheduled_messages SET next_run = ? WHERE id = ?",
            (next_run, schedule_id),
        )
        await self.conn.commit()

    async def set_enabled(self, schedule_id: int, enabled: bool) -> None:
        await self.conn.execute(
            "UPDATE scheduled_messages SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, schedule_id),
        )
        await self.conn.commit()

    async def delete_schedule(self, guild_id: int, schedule_id: int) -> bool:
        cur = await self.conn.execute(
            "DELETE FROM scheduled_messages WHERE id = ? AND guild_id = ?",
            (schedule_id, guild_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0


def _row_to_card(row: aiosqlite.Row) -> Card:
    return Card(
        guild_id=row["guild_id"],
        name=row["name"],
        title=row["title"],
        description=row["description"],
        image_url=row["image_url"],
        color=row["color"],
        buttons=row["buttons"],
        channel_id=row["channel_id"],
        message_id=row["message_id"],
    )


def _row_to_schedule(row: aiosqlite.Row) -> ScheduledMessage:
    keys = row.keys()
    return ScheduledMessage(
        id=row["id"],
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        content=row["content"],
        repeat=row["repeat"],
        next_run=row["next_run"],
        enabled=bool(row["enabled"]),
        created_by=row["created_by"],
        card_name=row["card_name"] if "card_name" in keys else None,
    )
