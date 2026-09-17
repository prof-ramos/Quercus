"""Camada de persistência mínima.

SQLite local; sem ORM. `events` é append-only: não há mutators expostos.
"""

import json
import sqlite3
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: str) -> sqlite3.Connection:
    """Abre conexão e garante o schema."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def record_event(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    event_type: str,
    payload: dict,
    source_type: str = "SYSTEM_OBSERVED",
    source_id: str | None = None,
    timestamp: str | None = None,
) -> int:
    """Registra um evento. Retorna o id."""
    cur = conn.execute(
        """
        INSERT INTO events
            (user_id, event_type, timestamp, source_type, source_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            event_type,
            timestamp or _now(),
            source_type,
            source_id,
            json.dumps(payload, ensure_ascii=False),
            _now(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_events(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """Lê eventos do usuário mais recentes primeiro."""
    return conn.execute(
        """
        SELECT id, user_id, event_type, timestamp, source_type, source_id,
               payload_json, created_at
        FROM events
        WHERE user_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
