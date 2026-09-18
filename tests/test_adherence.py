"""Testes do cálculo determinístico de aderência e ciclo de vida de estudos."""

import sqlite3
from pathlib import Path

import pytest

from quercus import adherence, persistence


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return persistence.connect(str(tmp_path / "quercus_test.db"))


def test_calculate_metrics_empty() -> None:
    metrics = adherence.calculate_metrics([])
    assert metrics.total_sessions == 0
    assert metrics.total_planned_minutes == 0
    assert metrics.total_actual_minutes == 0
    assert metrics.completion_rate == 0.0
    assert metrics.minutes_adherence_rate == 0.0
    assert metrics.by_subject == {}


def test_calculate_metrics_various_statuses_and_subjects() -> None:
    mock_sessions = [
        {
            "subject": "História do Brasil",
            "status": "completed",
            "planned_minutes": 60,
            "actual_minutes": 60,
        },
        {
            "subject": "História do Brasil",
            "status": "partial",
            "planned_minutes": 60,
            "actual_minutes": 30,
        },
        {
            "subject": "Política Internacional",
            "status": "skipped",
            "planned_minutes": 60,
            "actual_minutes": 0,
        },
        {
            "subject": "Economia",
            "status": "cancelled",
            "planned_minutes": 90,
            "actual_minutes": 0,
        },
    ]

    metrics = adherence.calculate_metrics(mock_sessions)

    assert metrics.total_sessions == 4
    assert metrics.completed_sessions == 1
    assert metrics.partial_sessions == 1
    assert metrics.skipped_sessions == 1
    assert metrics.cancelled_sessions == 1
    assert metrics.total_planned_minutes == 270
    assert metrics.total_actual_minutes == 90
    assert metrics.completion_rate == 0.25
    assert metrics.minutes_adherence_rate == round(90 / 270, 4)

    hb = metrics.by_subject["História do Brasil"]
    assert hb.planned_sessions == 2
    assert hb.completed_sessions == 1
    assert hb.partial_sessions == 1
    assert hb.planned_minutes == 120
    assert hb.actual_minutes == 90
    assert hb.adherence_rate == 0.75

    pi = metrics.by_subject["Política Internacional"]
    assert pi.planned_sessions == 1
    assert pi.skipped_sessions == 1
    assert pi.planned_minutes == 60
    assert pi.actual_minutes == 0
    assert pi.adherence_rate == 0.0

    eco = metrics.by_subject["Economia"]
    assert eco.planned_sessions == 1
    assert eco.cancelled_sessions == 1
    assert eco.adherence_rate == 0.0


def test_daily_adherence_aggregation(conn: sqlite3.Connection) -> None:
    # 2 sessões no dia alvo (2026-09-18)
    persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="Direito Internacional",
        planned_minutes=60,
        actual_minutes=60,
        status="completed",
        planned_at="2026-09-18T10:00:00Z",
    )
    persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="Língua Portuguesa",
        planned_minutes=45,
        actual_minutes=45,
        status="completed",
        planned_at="2026-09-18T15:00:00Z",
    )

    # 1 sessão em outro dia (2026-09-19)
    persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="História Mundial",
        planned_minutes=90,
        actual_minutes=0,
        status="planned",
        planned_at="2026-09-19T09:00:00Z",
    )

    daily = adherence.calculate_daily_adherence(
        conn,
        user_id="gabriel",
        target_date="2026-09-18",
    )

    assert daily.date_str == "2026-09-18"
    assert daily.metrics.total_sessions == 2
    assert daily.metrics.completed_sessions == 2
    assert daily.metrics.total_planned_minutes == 105
    assert daily.metrics.total_actual_minutes == 105
    assert daily.metrics.completion_rate == 1.0
    assert daily.metrics.minutes_adherence_rate == 1.0
    assert len(daily.metrics.by_subject) == 2


def test_weekly_adherence_and_daily_breakdown(conn: sqlite3.Connection) -> None:
    # Cria sessões espalhadas na semana que começa em 2026-09-14 (segunda-feira)
    persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="Política Internacional",
        planned_minutes=60,
        actual_minutes=60,
        status="completed",
        planned_at="2026-09-14T09:00:00Z",
    )
    persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="História do Brasil",
        planned_minutes=60,
        actual_minutes=30,
        status="partial",
        planned_at="2026-09-16T14:00:00Z",
    )

    weekly = adherence.calculate_weekly_adherence(
        conn,
        user_id="gabriel",
        week_start="2026-09-14",
    )

    assert weekly.week_start == "2026-09-14"
    assert weekly.week_end == "2026-09-20"
    assert weekly.metrics.total_sessions == 2
    assert weekly.metrics.completed_sessions == 1
    assert weekly.metrics.partial_sessions == 1
    assert weekly.metrics.total_planned_minutes == 120
    assert weekly.metrics.total_actual_minutes == 90
    assert weekly.metrics.completion_rate == 0.5
    assert weekly.metrics.minutes_adherence_rate == 0.75

    # 7 dias devem estar presentes no breakdown
    assert len(weekly.daily_metrics) == 7
    assert "2026-09-14" in weekly.daily_metrics
    assert weekly.daily_metrics["2026-09-14"].total_sessions == 1
    assert weekly.daily_metrics["2026-09-15"].total_sessions == 0
    assert weekly.daily_metrics["2026-09-16"].total_sessions == 1


def test_study_session_lifecycle_flow(conn: sqlite3.Connection) -> None:
    # 1. Planejamento
    session_id = persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="Geografia",
        topic="Urbanização e Redes Urbanas",
        planned_minutes=60,
        planned_at="2026-09-18T16:00:00Z",
    )

    # 2. Início do estudo
    adherence.start_study_session(
        conn,
        session_id=session_id,
        started_at="2026-09-18T16:05:00Z",
    )
    s_after_start = persistence.get_study_session(conn, session_id)
    assert s_after_start is not None
    assert s_after_start["status"] == "partial"
    assert s_after_start["started_at"] == "2026-09-18T16:05:00.000000+00:00"

    # 3. Conclusão do estudo
    adherence.complete_study_session(
        conn,
        session_id=session_id,
        actual_minutes=55,
        finished_at="2026-09-18T17:00:00Z",
        notes="Foco em conurbação e metropolização brasileira",
    )
    s_after_finish = persistence.get_study_session(conn, session_id)
    assert s_after_finish is not None
    assert s_after_finish["status"] == "completed"
    assert s_after_finish["actual_minutes"] == 55
    assert s_after_finish["finished_at"] == "2026-09-18T17:00:00.000000+00:00"
    assert s_after_finish["notes"] == "Foco em conurbação e metropolização brasileira"

    # 4. Segunda sessão que é pulada
    skip_id = persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="Inglês",
        planned_minutes=30,
    )
    adherence.skip_study_session(
        conn,
        session_id=skip_id,
        notes="Imprevisto de trabalho",
    )
    s_skipped = persistence.get_study_session(conn, skip_id)
    assert s_skipped is not None
    assert s_skipped["status"] == "skipped"

    # 5. Validação de auditoria nos eventos
    events = persistence.list_events(conn, user_id="gabriel")
    event_types = [e["event_type"] for e in events]
    assert "STUDY_SKIPPED" in event_types
    assert "STUDY_COMPLETED" in event_types
    assert "STUDY_STARTED" in event_types
