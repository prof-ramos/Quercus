"""Prova do ciclo mínimo: observar → registrar → ler."""

import json

import pytest

from quercus import persistence


@pytest.fixture
def conn(tmp_path):
    return persistence.connect(str(tmp_path / "quercus.db"))


def test_schema_is_created_on_connect(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
    ).fetchall()
    assert rows[0]["name"] == "events"


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
    assert e["id"] == event_id
    assert e["user_id"] == "user_01"
    assert e["event_type"] == "STUDY_STARTED"
    assert json.loads(e["payload_json"]) == {
        "subject": "História do Brasil",
        "planned_min": 45,
    }
    assert e["source_type"] == "USER_OBSERVED"
    assert e["timestamp"]


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
    assert [e["event_type"] for e in events] == ["STUDY_COMPLETED", "STUDY_STARTED"]


def test_events_isolated_per_user(conn):
    persistence.record_event(conn, user_id="alice", event_type="X", payload={})
    persistence.record_event(conn, user_id="bob", event_type="Y", payload={})

    assert [
        e["event_type"] for e in persistence.list_events(conn, user_id="alice")
    ] == ["X"]
    assert [e["event_type"] for e in persistence.list_events(conn, user_id="bob")] == [
        "Y"
    ]
