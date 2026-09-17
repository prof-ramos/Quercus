"""Prova do ciclo mínimo: observar → registrar → ler."""

from __future__ import annotations

import pytest

from quercus import persistence


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "quercus.db"
    return persistence.connect(str(db_path))


def test_schema_is_created_on_connect(tmp_path):
    db_path = tmp_path / "quercus.db"
    conn = persistence.connect(str(db_path))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
    ).fetchall()
    assert rows == [("events",)]
    conn.close()


def test_record_and_read_one_event(conn):
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
    assert e.id == event_id
    assert e.user_id == "user_01"
    assert e.event_type == "STUDY_STARTED"
    assert e.payload == {"subject": "História do Brasil", "planned_min": 45}
    assert e.source_type == "USER_OBSERVED"
    assert e.timestamp  # não vazio


def test_events_are_ordered_most_recent_first(conn):
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
    assert [e.event_type for e in events] == ["STUDY_COMPLETED", "STUDY_STARTED"]


def test_events_isolated_per_user(conn):
    persistence.record_event(conn, user_id="alice", event_type="X", payload={})
    persistence.record_event(conn, user_id="bob", event_type="Y", payload={})

    alice_events = persistence.list_events(conn, user_id="alice")
    bob_events = persistence.list_events(conn, user_id="bob")
    assert [e.event_type for e in alice_events] == ["X"]
    assert [e.event_type for e in bob_events] == ["Y"]


def test_append_only_no_update_path(conn):
    """Garantia estrutural: não expomos UPDATE nem DELETE em events."""
    persistence.record_event(conn, user_id="user_01", event_type="X", payload={"v": 1})
    # Tentativa de UPDATE direto deve funcionar (SQLite permite), mas o
    # módulo não oferece essa operação. Aqui só verificamos que não há
    # método público de update/delete.
    public_api = [
        name
        for name in dir(persistence)
        if not name.startswith("_") and callable(getattr(persistence, name))
    ]
    forbidden = {"update_event", "delete_event", "mutate_event"}
    assert forbidden.isdisjoint(public_api), (
        f"API pública não deve expor mutação de events; encontrado: "
        f"{forbidden & set(public_api)}"
    )
