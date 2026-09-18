"""Prova do ciclo mínimo: observar → registrar → ler."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quercus import persistence


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return persistence.connect(str(tmp_path / "quercus.db"))


def test_schema_is_created_on_connect(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
    ).fetchall()
    assert rows[0]["name"] == "events"


def test_record_and_read_one_event(conn: sqlite3.Connection) -> None:
    event_id = persistence.record_event(
        conn,
        user_id="user_01",
        event_type="STUDY_STARTED",
        payload={"subject": "História do Brasil", "planned_min": 45},
        source_type="USER_OBSERVED",
    )
    assert event_id > 0

    events = persistence.list_events(conn, user_id="user_01")
    assert len(events) == 1
    e = events[0]
    assert e["id"] == event_id
    assert e["user_id"] == "user_01"
    assert e["event_type"] == "STUDY_STARTED"
    assert json.loads(e["payload_json"]) == {
        "subject": "História do Brasil",
        "planned_min": 45,
    }
    assert e["source_type"] == "USER_OBSERVED"
    assert e["timestamp"]


def test_events_are_ordered_most_recent_first(conn: sqlite3.Connection) -> None:
    persistence.record_event(
        conn,
        user_id="user_01",
        event_type="STUDY_STARTED",
        payload={"subject": "A"},
        timestamp="2026-09-15T08:00:00+00:00",
    )
    persistence.record_event(
        conn,
        user_id="user_01",
        event_type="STUDY_COMPLETED",
        payload={"subject": "B"},
        timestamp="2026-09-17T08:00:00+00:00",
    )

    events = persistence.list_events(conn, user_id="user_01")
    assert [e["event_type"] for e in events] == ["STUDY_COMPLETED", "STUDY_STARTED"]


def test_events_isolated_per_user(conn: sqlite3.Connection) -> None:
    persistence.record_event(conn, user_id="alice", event_type="X", payload={})
    persistence.record_event(conn, user_id="bob", event_type="Y", payload={})

    assert [
        e["event_type"] for e in persistence.list_events(conn, user_id="alice")
    ] == ["X"]
    assert [e["event_type"] for e in persistence.list_events(conn, user_id="bob")] == [
        "Y"
    ]


def test_wal_mode_and_busy_timeout(conn: sqlite3.Connection) -> None:
    journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000


def test_invalid_source_type_raises_value_error(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="source_type 'INVALID' inválido"):
        persistence.record_event(
            conn,
            user_id="user_01",
            event_type="TEST",
            payload={},
            source_type="INVALID",
        )


def test_timestamp_lexical_order_across_different_offsets(
    conn: sqlite3.Connection,
) -> None:
    # Evento B: 20:00 UTC
    persistence.record_event(
        conn,
        user_id="user_01",
        event_type="EVENT_B",
        payload={},
        timestamp="2026-09-18T20:00:00+00:00",
    )
    # Evento A: 18:00 no fuso -03:00 -> 21:00 UTC (deve ordenar DEPOIS de B no DESC)
    persistence.record_event(
        conn,
        user_id="user_01",
        event_type="EVENT_A",
        payload={},
        timestamp="2026-09-18T18:00:00-03:00",
    )
    # Evento C: 22:00 com 'Z' -> 22:00 UTC (o mais recente)
    persistence.record_event(
        conn,
        user_id="user_01",
        event_type="EVENT_C",
        payload={},
        timestamp="2026-09-18T22:00:00Z",
    )

    events = persistence.list_events(conn, user_id="user_01")
    # Ordem DESC: mais recente primeiro (C=22h, A=21h, B=20h)
    assert [e["event_type"] for e in events] == ["EVENT_C", "EVENT_A", "EVENT_B"]


def test_payload_with_datetime_uuid_and_unicode(conn: sqlite3.Connection) -> None:
    sample_id = uuid.uuid4()
    now_dt = datetime(2026, 9, 18, 17, 30, tzinfo=UTC)

    event_id = persistence.record_event(
        conn,
        user_id="user_gabriel",
        event_type="STUDY_NOTE",
        payload={
            "session_id": sample_id,
            "created_at": now_dt,
            "note": (
                "Atenção ao Segundo Reinado: foco nas tarifas Alves Branco "
                "e na Lei Eusébio de Queirós 📚"
            ),
        },
        source_type="USER_EXPLICIT",
    )

    events = persistence.list_events(conn, user_id="user_gabriel")
    assert len(events) == 1
    e = events[0]
    assert e["id"] == event_id
    payload = json.loads(e["payload_json"])
    assert payload["session_id"] == str(sample_id)
    assert "Alves Branco" in payload["note"]


def test_list_events_limit_and_empty_user(conn: sqlite3.Connection) -> None:
    assert persistence.list_events(conn, user_id="non_existent") == []

    for i in range(5):
        persistence.record_event(
            conn,
            user_id="user_batch",
            event_type=f"STEP_{i}",
            payload={"i": i},
        )

    limited = persistence.list_events(conn, user_id="user_batch", limit=2)
    assert len(limited) == 2


def test_record_memory_and_link_evidence(conn: sqlite3.Connection) -> None:
    event_id = persistence.record_event(
        conn,
        user_id="user_01",
        event_type="STUDY_COMPLETED",
        payload={"subject": "História do Brasil", "minutes": 50},
        source_type="SYSTEM_OBSERVED",
    )

    mem_id = persistence.record_memory(
        conn,
        user_id="user_01",
        memory_type="inferential",
        statement="História tende a render melhor pela manhã.",
        status="candidate",
        confidence=0.75,
        importance=2,
    )
    assert mem_id > 0

    ev_id = persistence.link_memory_evidence(
        conn,
        memory_id=mem_id,
        event_id=event_id,
        weight=1.5,
        relationship="supports",
    )
    assert ev_id > 0

    mem_data = persistence.get_memory_with_evidence(conn, mem_id)
    assert mem_data is not None
    assert mem_data["id"] == mem_id
    assert mem_data["statement"] == "História tende a render melhor pela manhã."
    assert mem_data["confidence"] == 0.75
    assert len(mem_data["evidence"]) == 1

    ev = mem_data["evidence"][0]
    assert ev["event_id"] == event_id
    assert ev["relationship"] == "supports"
    assert ev["weight"] == 1.5
    assert ev["payload"]["subject"] == "História do Brasil"


def test_update_memory_status_and_confidence(conn: sqlite3.Connection) -> None:
    mem_id = persistence.record_memory(
        conn,
        user_id="user_01",
        memory_type="semantic",
        statement="Prefere blocos de 45 minutos.",
        status="candidate",
    )

    persistence.update_memory_status(conn, mem_id, status="active", confidence=0.9)

    memories = persistence.list_memories(conn, user_id="user_01", status="active")
    assert len(memories) == 1
    assert memories[0]["id"] == mem_id
    assert memories[0]["status"] == "active"
    assert memories[0]["confidence"] == 0.9


def test_supersede_memory_lifecycle(conn: sqlite3.Connection) -> None:
    old_id = persistence.record_memory(
        conn,
        user_id="user_01",
        memory_type="semantic",
        statement="Estuda 45 minutos por bloco.",
        status="active",
        source_origin="USER_EXPLICIT",
    )

    new_id = persistence.supersede_memory(
        conn,
        old_memory_id=old_id,
        statement="Estuda 30 minutos por bloco.",
        confidence=1.0,
        source_origin="USER_EXPLICIT",
    )
    assert new_id != old_id

    old_mem = persistence.get_memory_with_evidence(conn, old_id)
    assert old_mem is not None
    assert old_mem["status"] == "superseded"

    new_mem = persistence.get_memory_with_evidence(conn, new_id)
    assert new_mem is not None
    assert new_mem["status"] == "active"
    assert new_mem["supersedes_id"] == old_id
    assert new_mem["statement"] == "Estuda 30 minutos por bloco."


def test_list_memories_filtering(conn: sqlite3.Connection) -> None:
    persistence.record_memory(
        conn,
        user_id="user_02",
        memory_type="semantic",
        statement="Semântica 1",
        status="active",
    )
    persistence.record_memory(
        conn,
        user_id="user_02",
        memory_type="inferential",
        statement="Inferencial 1",
        status="candidate",
    )

    active_only = persistence.list_memories(conn, user_id="user_02", status="active")
    assert len(active_only) == 1
    assert active_only[0]["statement"] == "Semântica 1"

    inferential_only = persistence.list_memories(
        conn, user_id="user_02", memory_type="inferential"
    )
    assert len(inferential_only) == 1
    assert inferential_only[0]["statement"] == "Inferencial 1"


def test_foreign_key_cascade_and_restrict(conn: sqlite3.Connection) -> None:
    event_id = persistence.record_event(
        conn,
        user_id="user_fk",
        event_type="BASE_EVENT",
        payload={},
    )
    mem_id = persistence.record_memory(
        conn,
        user_id="user_fk",
        memory_type="semantic",
        statement="Memória vinculada",
    )
    persistence.link_memory_evidence(
        conn,
        memory_id=mem_id,
        event_id=event_id,
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
    conn.commit()

    ev_rows = conn.execute(
        "SELECT * FROM memory_evidence WHERE memory_id = ?", (mem_id,)
    ).fetchall()
    assert len(ev_rows) == 0


def test_invalid_memory_parameters_raise_error(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="memory_type 'invalid' inválido"):
        persistence.record_memory(
            conn,
            user_id="u",
            memory_type="invalid",
            statement="s",
        )

    with pytest.raises(ValueError, match="status 'invalid' inválido"):
        persistence.record_memory(
            conn,
            user_id="u",
            memory_type="semantic",
            statement="s",
            status="invalid",
        )

    with pytest.raises(ValueError, match="relationship 'invalid' inválido"):
        persistence.link_memory_evidence(
            conn,
            memory_id=1,
            event_id=1,
            relationship="invalid",
        )
