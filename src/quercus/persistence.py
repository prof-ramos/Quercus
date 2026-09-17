"""Camada de persistência mínima.

Esta é a única fonte de verdade estrutural do Quercus no ciclo mínimo.
SQLite local; sem ORM. Eventos são append-only por design.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_user_time
    ON events (user_id, timestamp DESC);
"""


@dataclass(frozen=True)
class Event:
    id: int
    user_id: str
    event_type: str
    timestamp: str
    source_type: str
    source_id: str | None
    payload: dict
    created_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: str) -> sqlite3.Connection:
    """Abre conexão e garante o schema."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
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
    """Registra um evento. Retorna o id.

    `events` é append-only: nunca atualizamos nem deletamos por aqui.
    """
    ts = timestamp or _now()
    cur = conn.execute(
        """
        INSERT INTO events
            (user_id, event_type, timestamp, source_type, source_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            event_type,
            ts,
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
) -> list[Event]:
    """Lê eventos do usuário mais recentes primeiro."""
    rows = conn.execute(
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
    return [
        Event(
            id=row[0],
            user_id=row[1],
            event_type=row[2],
            timestamp=row[3],
            source_type=row[4],
            source_id=row[5],
            payload=json.loads(row[6]),
            created_at=row[7],
        )
        for row in rows
    ]
