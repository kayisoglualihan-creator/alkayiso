"""SQLite-Datenbank mit einfachem, vorwärtsgerichtetem Migrationssystem."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # 1 – Grundschema
    """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

    CREATE TABLE devices (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT 'unknown',
        created_at REAL NOT NULL,
        last_seen REAL,
        revoked_at REAL,
        refresh_hash TEXT,
        refresh_expires REAL,
        token_version INTEGER NOT NULL DEFAULT 1,
        tailscale_login TEXT
    );

    CREATE TABLE pairings (
        id TEXT PRIMARY KEY,
        code_hash TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        status TEXT NOT NULL,
        device_name TEXT,
        platform TEXT,
        claim_hash TEXT,
        verify_code TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        device_id TEXT,
        tailscale_login TEXT
    );

    CREATE TABLE conversations (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );

    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        meta TEXT,
        created_at REAL NOT NULL
    );
    CREATE INDEX idx_messages_conv ON messages(conversation_id, id);

    CREATE TABLE memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'allgemein',
        importance REAL NOT NULL DEFAULT 0.5,
        source TEXT NOT NULL DEFAULT 'user',
        vector TEXT NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        last_used REAL
    );

    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        priority INTEGER NOT NULL DEFAULT 2,
        project TEXT NOT NULL DEFAULT '',
        due_at REAL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        completed_at REAL
    );

    CREATE TABLE reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        due_at REAL NOT NULL,
        repeat TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at REAL NOT NULL,
        fired_at REAL
    );

    CREATE TABLE automations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        schedule TEXT NOT NULL,
        action_type TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_run REAL,
        next_run REAL,
        last_result TEXT,
        created_at REAL NOT NULL
    );

    CREATE TABLE jobs (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        device_id TEXT,
        text TEXT NOT NULL,
        status TEXT NOT NULL,
        result TEXT,
        error TEXT,
        conversation_id TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );

    CREATE TABLE approvals (
        id TEXT PRIMARY KEY,
        job_id TEXT,
        tool TEXT NOT NULL,
        args TEXT NOT NULL,
        risk INTEGER NOT NULL,
        summary TEXT NOT NULL,
        status TEXT NOT NULL,
        requested_by TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        decided_at REAL,
        decided_by TEXT
    );

    CREATE TABLE audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        risk INTEGER NOT NULL DEFAULT 0,
        outcome TEXT NOT NULL DEFAULT 'ok',
        detail TEXT
    );

    CREATE TABLE notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        read INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cost REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE undo_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        description TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0
    );
    """,
    # 2 – Listen (Einkauf etc.), Gewohnheiten, Budget
    """
    CREATE TABLE list_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        list_name TEXT NOT NULL,
        text TEXT NOT NULL,
        checked INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    );
    CREATE TABLE habits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at REAL NOT NULL
    );
    CREATE TABLE habit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
        day TEXT NOT NULL,
        UNIQUE(habit_id, day)
    );
    CREATE TABLE budget_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL,
        amount REAL NOT NULL,
        category TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL
    );
    """,
]


class Database:
    """Thread-sichere SQLite-Hülle. Für die Datenmengen eines persönlichen Assistenten
    ist eine einzige Verbindung mit Lock völlig ausreichend und robust."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    # -- Migrationen -------------------------------------------------------
    def schema_version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        with self._lock:
            current = self.schema_version()
            for idx, script in enumerate(MIGRATIONS[current:], start=current + 1):
                self.conn.execute("BEGIN")
                try:
                    for stmt in [s for s in script.split(";") if s.strip()]:
                        self.conn.execute(stmt)
                    self.conn.execute(f"PRAGMA user_version = {idx}")
                    self.conn.execute("COMMIT")
                except Exception:
                    self.conn.execute("ROLLBACK")
                    raise

    # -- Hilfsfunktionen ----------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, tuple(params))

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self._lock:
            row = self.conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def insert(self, table: str, values: dict) -> int:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self._lock:
            cur = self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
            return cur.lastrowid

    def update(self, table: str, key: str, key_value: Any, values: dict) -> int:
        sets = ", ".join(f"{k} = ?" for k in values)
        with self._lock:
            cur = self.conn.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", (*values.values(), key_value))
            return cur.rowcount

    # -- Einstellungen ------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # -- Audit --------------------------------------------------------------
    def audit(self, actor: str, action: str, detail: Any = None, risk: int = 0, outcome: str = "ok") -> None:
        self.insert("audit", {
            "ts": time.time(), "actor": actor, "action": action, "risk": risk, "outcome": outcome,
            "detail": json.dumps(detail, ensure_ascii=False, default=str) if detail is not None else None,
        })

    def close(self) -> None:
        with self._lock:
            self.conn.close()
