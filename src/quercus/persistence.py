"""Camada de persistência mínima.

SQLite local; sem ORM. `events` é append-only: não há mutators expostos.
"""

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

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

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    statement TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL,
    importance INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_confirmed_at TEXT,
    expires_at TEXT,
    supersedes_id INTEGER,
    source_origin TEXT NOT NULL,
    FOREIGN KEY(supersedes_id) REFERENCES memories(id)
);

CREATE TABLE IF NOT EXISTS memory_evidence (
    id INTEGER PRIMARY KEY,
    memory_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    weight REAL DEFAULT 1.0,
    relationship TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    topic TEXT,
    planned_minutes INTEGER NOT NULL,
    actual_minutes INTEGER,
    planned_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS study_plans (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    plan_date TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS study_plan_items (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    topic TEXT,
    duration_minutes INTEGER NOT NULL,
    priority INTEGER DEFAULT 1,
    deadline TEXT,
    reason TEXT,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(plan_id) REFERENCES study_plans(id) ON DELETE CASCADE
);
"""

VALID_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "USER_EXPLICIT",
        "USER_OBSERVED",
        "SYSTEM_OBSERVED",
        "AGENT_DERIVED",
        "DOCUMENT_TRUSTED",
        "DOCUMENT_UNTRUSTED",
        "TOOL_RESULT",
    }
)

VALID_SESSION_STATUSES: frozenset[str] = frozenset(
    {
        "planned",
        "completed",
        "partial",
        "skipped",
        "cancelled",
    }
)

VALID_PLAN_STATUSES: frozenset[str] = frozenset(
    {
        "draft",
        "active",
        "adapted",
        "completed",
        "cancelled",
    }
)

VALID_PLAN_ITEM_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "in_progress",
        "completed",
        "deferred",
        "reduced",
        "cancelled",
    }
)

VALID_MEMORY_TYPES: frozenset[str] = frozenset(
    {"episodic", "semantic", "inferential", "procedural"}
)

VALID_MEMORY_STATUSES: frozenset[str] = frozenset(
    {
        "candidate",
        "active",
        "superseded",
        "archived",
        "rejected",
        "revoked",
        "expired",
    }
)

VALID_EVIDENCE_RELATIONSHIPS: frozenset[str] = frozenset(
    {"supports", "contradicts", "illustrates"}
)


def _normalize_iso_utc(ts: str | datetime | None = None) -> str:
    """Retorna timestamp ISO-8601 em UTC rigoroso com microssegundos.

    Exemplo de saída: '2026-09-18T20:30:00.000000+00:00'.
    Garante ordenação léxica idêntica à ordem cronológica no SQLite TEXT.
    """
    if ts is None:
        dt = datetime.now(UTC)
    elif isinstance(ts, datetime):
        dt = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
    elif isinstance(ts, str):
        clean = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    else:
        raise TypeError(f"Timestamp inválido: {type(ts)}")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def connect(path: str) -> sqlite3.Connection:
    """Abre conexão, ativa WAL/busy_timeout, foreign_keys e garante o schema."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    return conn


def record_event(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    event_type: str,
    payload: Mapping[str, Any],
    source_type: str = "SYSTEM_OBSERVED",
    source_id: str | None = None,
    timestamp: str | datetime | None = None,
) -> int:
    """Registra um evento. Retorna o id."""
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(
            f"source_type '{source_type}' inválido. "
            f"Origens permitidas: {sorted(VALID_SOURCE_TYPES)}"
        )

    norm_timestamp = _normalize_iso_utc(timestamp)
    created_at = _normalize_iso_utc()
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)

    cur = conn.execute(
        """
        INSERT INTO events
            (user_id, event_type, timestamp, source_type, source_id,
             payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            event_type,
            norm_timestamp,
            source_type,
            source_id,
            payload_json,
            created_at,
        ),
    )
    conn.commit()
    assert cur.lastrowid is not None
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


def record_memory(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    memory_type: str,
    statement: str,
    status: str = "candidate",
    confidence: float | None = None,
    importance: int = 1,
    source_origin: str = "SYSTEM_OBSERVED",
    supersedes_id: int | None = None,
    created_at: str | datetime | None = None,
) -> int:
    """Registra uma memória (candidata ou ativa). Retorna o id."""
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(
            f"memory_type '{memory_type}' inválido. "
            f"Tipos permitidos: {sorted(VALID_MEMORY_TYPES)}"
        )
    if status not in VALID_MEMORY_STATUSES:
        raise ValueError(
            f"status '{status}' inválido. "
            f"Status permitidos: {sorted(VALID_MEMORY_STATUSES)}"
        )
    if source_origin not in VALID_SOURCE_TYPES:
        raise ValueError(
            f"source_origin '{source_origin}' inválido. "
            f"Origens permitidas: {sorted(VALID_SOURCE_TYPES)}"
        )

    norm_created_at = _normalize_iso_utc(created_at)
    cur = conn.execute(
        """
        INSERT INTO memories
            (user_id, memory_type, statement, status, confidence, importance,
             created_at, updated_at, last_confirmed_at, expires_at,
             supersedes_id, source_origin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            memory_type,
            statement,
            status,
            confidence,
            importance,
            norm_created_at,
            norm_created_at,
            None,
            None,
            supersedes_id,
            source_origin,
        ),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


def link_memory_evidence(
    conn: sqlite3.Connection,
    *,
    memory_id: int,
    event_id: int,
    weight: float = 1.0,
    relationship: str = "supports",
) -> int:
    """Vincula um evento como evidência para uma memória."""
    if relationship not in VALID_EVIDENCE_RELATIONSHIPS:
        raise ValueError(
            f"relationship '{relationship}' inválido. "
            f"Relações permitidas: {sorted(VALID_EVIDENCE_RELATIONSHIPS)}"
        )
    created_at = _normalize_iso_utc()
    cur = conn.execute(
        """
        INSERT INTO memory_evidence
            (memory_id, event_id, weight, relationship, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (memory_id, event_id, weight, relationship, created_at),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


def list_memories(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    status: str | None = None,
    memory_type: str | None = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """Lê memórias do usuário com filtros opcionais por status e tipo."""
    query = """
        SELECT id, user_id, memory_type, statement, status, confidence,
               importance, created_at, updated_at, last_confirmed_at,
               expires_at, supersedes_id, source_origin
        FROM memories
        WHERE user_id = ?
    """
    params: list[Any] = [user_id]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if memory_type is not None:
        query += " AND memory_type = ?"
        params.append(memory_type)

    query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    params.append(limit)
    return conn.execute(query, params).fetchall()


def get_memory_with_evidence(
    conn: sqlite3.Connection,
    memory_id: int,
) -> dict[str, Any] | None:
    """Recupera memória com sua cadeia de evidências para auditabilidade."""
    row = conn.execute(
        """
        SELECT id, user_id, memory_type, statement, status, confidence,
               importance, created_at, updated_at, last_confirmed_at,
               expires_at, supersedes_id, source_origin
        FROM memories
        WHERE id = ?
        """,
        (memory_id,),
    ).fetchone()
    if row is None:
        return None

    mem_dict: dict[str, Any] = dict(row)
    evidence_rows = conn.execute(
        """
        SELECT me.id, me.memory_id, me.event_id, me.weight, me.relationship,
               me.created_at, e.event_type, e.timestamp as event_timestamp,
               e.source_type, e.payload_json
        FROM memory_evidence me
        JOIN events e ON me.event_id = e.id
        WHERE me.memory_id = ?
        ORDER BY me.id ASC
        """,
        (memory_id,),
    ).fetchall()

    evidences: list[dict[str, Any]] = []
    for ev in evidence_rows:
        d = dict(ev)
        d["payload"] = json.loads(d.pop("payload_json"))
        evidences.append(d)

    mem_dict["evidence"] = evidences
    return mem_dict


def update_memory_status(
    conn: sqlite3.Connection,
    memory_id: int,
    *,
    status: str,
    confidence: float | None = None,
) -> None:
    """Atualiza status e opcionalmente a confiança de uma memória."""
    if status not in VALID_MEMORY_STATUSES:
        raise ValueError(
            f"status '{status}' inválido. "
            f"Status permitidos: {sorted(VALID_MEMORY_STATUSES)}"
        )
    updated_at = _normalize_iso_utc()
    if confidence is not None:
        conn.execute(
            """
            UPDATE memories
            SET status = ?, confidence = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, confidence, updated_at, memory_id),
        )
    else:
        conn.execute(
            """
            UPDATE memories
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, updated_at, memory_id),
        )
    conn.commit()


def supersede_memory(
    conn: sqlite3.Connection,
    *,
    old_memory_id: int,
    statement: str,
    confidence: float | None = None,
    importance: int = 1,
    source_origin: str = "USER_EXPLICIT",
) -> int:
    """Substitui uma memória por outra mantendo a trilha de auditoria."""
    old = conn.execute(
        "SELECT user_id, memory_type FROM memories WHERE id = ?",
        (old_memory_id,),
    ).fetchone()
    if old is None:
        raise ValueError(f"Memória id {old_memory_id} não encontrada.")

    updated_at = _normalize_iso_utc()
    conn.execute(
        "UPDATE memories SET status = 'superseded', updated_at = ? WHERE id = ?",
        (updated_at, old_memory_id),
    )

    return record_memory(
        conn,
        user_id=old["user_id"],
        memory_type=old["memory_type"],
        statement=statement,
        status="active",
        confidence=confidence,
        importance=importance,
        source_origin=source_origin,
        supersedes_id=old_memory_id,
        created_at=updated_at,
    )


def record_study_session(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    subject: str,
    planned_minutes: int,
    topic: str | None = None,
    actual_minutes: int | None = None,
    planned_at: str | datetime | None = None,
    started_at: str | datetime | None = None,
    finished_at: str | datetime | None = None,
    status: str = "planned",
    source: str = "USER_EXPLICIT",
    notes: str | None = None,
    created_at: str | datetime | None = None,
) -> int:
    """Registra uma sessão de estudo planejada ou realizada.

    Retorna o ID da sessão criada.
    """
    if status not in VALID_SESSION_STATUSES:
        allowed = sorted(VALID_SESSION_STATUSES)
        raise ValueError(f"Status de sessão inválido '{status}'. Permitidos: {allowed}")
    if planned_minutes < 0:
        raise ValueError("planned_minutes deve ser maior ou igual a zero.")
    if actual_minutes is not None and actual_minutes < 0:
        raise ValueError("actual_minutes deve ser maior ou igual a zero.")

    planned_at_norm = _normalize_iso_utc(planned_at) if planned_at else None
    started_at_norm = _normalize_iso_utc(started_at) if started_at else None
    finished_at_norm = _normalize_iso_utc(finished_at) if finished_at else None
    created_at_norm = _normalize_iso_utc(created_at)

    cursor = conn.execute(
        """
        INSERT INTO study_sessions (
            user_id, subject, topic, planned_minutes, actual_minutes,
            planned_at, started_at, finished_at, status, source, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            subject,
            topic,
            planned_minutes,
            actual_minutes,
            planned_at_norm,
            started_at_norm,
            finished_at_norm,
            status,
            source,
            notes,
            created_at_norm,
        ),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def update_study_session(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    status: str | None = None,
    actual_minutes: int | None = None,
    started_at: str | datetime | None = None,
    finished_at: str | datetime | None = None,
    notes: str | None = None,
) -> None:
    """Atualiza atributos de uma sessão de estudo existente."""
    existing = conn.execute(
        "SELECT id FROM study_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if existing is None:
        raise ValueError(f"Sessão de estudo id {session_id} não encontrada.")

    updates: list[str] = []
    params: list[Any] = []

    if status is not None:
        if status not in VALID_SESSION_STATUSES:
            allowed = sorted(VALID_SESSION_STATUSES)
            raise ValueError(
                f"Status de sessão inválido '{status}'. Permitidos: {allowed}"
            )
        updates.append("status = ?")
        params.append(status)

    if actual_minutes is not None:
        if actual_minutes < 0:
            raise ValueError("actual_minutes deve ser maior ou igual a zero.")
        updates.append("actual_minutes = ?")
        params.append(actual_minutes)

    if started_at is not None:
        updates.append("started_at = ?")
        params.append(_normalize_iso_utc(started_at))

    if finished_at is not None:
        updates.append("finished_at = ?")
        params.append(_normalize_iso_utc(finished_at))

    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)

    if not updates:
        return

    params.append(session_id)
    query = f"UPDATE study_sessions SET {', '.join(updates)} WHERE id = ?"
    conn.execute(query, params)
    conn.commit()


def get_study_session(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    """Retorna uma sessão de estudo pelo ID ou None se não existir."""
    row = conn.execute(
        "SELECT * FROM study_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return cast(sqlite3.Row | None, row)


def list_study_sessions(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    subject: str | None = None,
    status: str | None = None,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Lista sessões de estudo com filtros opcionais.

    Ordenadas por planned_at/created_at decrescente.
    """
    conditions: list[str] = ["user_id = ?"]
    params: list[Any] = [user_id]

    if subject is not None:
        conditions.append("subject = ?")
        params.append(subject)

    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    if since is not None:
        conditions.append("COALESCE(planned_at, created_at) >= ?")
        params.append(_normalize_iso_utc(since))

    if until is not None:
        conditions.append("COALESCE(planned_at, created_at) <= ?")
        params.append(_normalize_iso_utc(until))

    query = f"""
        SELECT * FROM study_sessions
        WHERE {" AND ".join(conditions)}
        ORDER BY COALESCE(planned_at, created_at) DESC, id DESC
    """
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    return conn.execute(query, params).fetchall()


def record_study_plan(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    plan_date: str,
    title: str,
    status: str = "active",
    notes: str | None = None,
    created_at: str | datetime | None = None,
) -> int:
    """Registra um plano diário de estudo."""
    if status not in VALID_PLAN_STATUSES:
        allowed = sorted(VALID_PLAN_STATUSES)
        raise ValueError(f"Status de plano inválido '{status}'. Permitidos: {allowed}")
    created_norm = _normalize_iso_utc(created_at)
    cursor = conn.execute(
        """
        INSERT INTO study_plans (
            user_id, plan_date, title, status, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, plan_date, title, status, notes, created_norm, created_norm),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def add_study_plan_item(
    conn: sqlite3.Connection,
    *,
    plan_id: int,
    subject: str,
    duration_minutes: int,
    topic: str | None = None,
    priority: int = 1,
    deadline: str | datetime | None = None,
    reason: str | None = None,
    status: str = "pending",
    source: str = "AGENT_PROPOSED",
    created_at: str | datetime | None = None,
) -> int:
    """Adiciona um item estruturado a um plano de estudo."""
    if status not in VALID_PLAN_ITEM_STATUSES:
        allowed = sorted(VALID_PLAN_ITEM_STATUSES)
        raise ValueError(f"Status de item inválido '{status}'. Permitidos: {allowed}")
    if duration_minutes <= 0:
        raise ValueError("duration_minutes deve ser maior que zero.")

    plan = conn.execute(
        "SELECT id FROM study_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    if plan is None:
        raise ValueError(f"Plano id {plan_id} não encontrado.")

    deadline_norm = _normalize_iso_utc(deadline) if deadline else None
    created_norm = _normalize_iso_utc(created_at)

    cursor = conn.execute(
        """
        INSERT INTO study_plan_items (
            plan_id, subject, topic, duration_minutes, priority,
            deadline, reason, status, source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            subject,
            topic,
            duration_minutes,
            priority,
            deadline_norm,
            reason,
            status,
            source,
            created_norm,
        ),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def get_study_plan(conn: sqlite3.Connection, plan_id: int) -> dict[str, Any] | None:
    """Recupera um plano e seus itens ordenados por prioridade."""
    row = conn.execute("SELECT * FROM study_plans WHERE id = ?", (plan_id,)).fetchone()
    if row is None:
        return None
    plan_dict: dict[str, Any] = dict(row)
    items = conn.execute(
        """
        SELECT * FROM study_plan_items
        WHERE plan_id = ?
        ORDER BY priority ASC, id ASC
        """,
        (plan_id,),
    ).fetchall()
    plan_dict["items"] = [dict(it) for it in items]
    return plan_dict


def list_study_plans(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    plan_date: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """Lista planos de estudo com filtros opcionais."""
    conditions: list[str] = ["user_id = ?"]
    params: list[Any] = [user_id]
    if plan_date is not None:
        conditions.append("plan_date = ?")
        params.append(plan_date)
    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    query = f"""
        SELECT * FROM study_plans
        WHERE {" AND ".join(conditions)}
        ORDER BY plan_date DESC, id DESC LIMIT ?
    """
    params.append(limit)
    return conn.execute(query, params).fetchall()


def update_plan_item_status(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    status: str,
    duration_minutes: int | None = None,
    reason: str | None = None,
) -> None:
    """Atualiza o status ou duração de um item do plano."""
    if status not in VALID_PLAN_ITEM_STATUSES:
        allowed = sorted(VALID_PLAN_ITEM_STATUSES)
        raise ValueError(f"Status de item inválido '{status}'. Permitidos: {allowed}")
    existing = conn.execute(
        "SELECT id, plan_id FROM study_plan_items WHERE id = ?", (item_id,)
    ).fetchone()
    if existing is None:
        raise ValueError(f"Item de plano id {item_id} não encontrado.")

    updates = ["status = ?"]
    params: list[Any] = [status]
    if duration_minutes is not None:
        if duration_minutes <= 0:
            raise ValueError("duration_minutes deve ser maior que zero.")
        updates.append("duration_minutes = ?")
        params.append(duration_minutes)
    if reason is not None:
        updates.append("reason = ?")
        params.append(reason)

    params.append(item_id)
    conn.execute(
        f"UPDATE study_plan_items SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    now_iso = _normalize_iso_utc()
    conn.execute(
        "UPDATE study_plans SET updated_at = ? WHERE id = ?",
        (now_iso, existing["plan_id"]),
    )
    conn.commit()
