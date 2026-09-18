"""Cálculo determinístico de aderência de estudos e ciclo de vida de sessões.

Aritmética 100% determinística sem dependência ou delegação para LLMs.
"""

import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from quercus import persistence


@dataclass(frozen=True)
class SubjectAdherence:
    """Métricas de aderência agregadas por disciplina."""

    subject: str
    planned_minutes: int
    actual_minutes: int
    adherence_rate: float
    planned_sessions: int
    completed_sessions: int
    partial_sessions: int
    skipped_sessions: int
    cancelled_sessions: int


@dataclass(frozen=True)
class AdherenceMetrics:
    """Métricas de aderência gerais calculadas deterministicamente."""

    total_planned_minutes: int
    total_actual_minutes: int
    minutes_adherence_rate: float  # actual / planned (pode ser > 1.0 se estudou mais)
    total_sessions: int
    completed_sessions: int
    partial_sessions: int
    skipped_sessions: int
    cancelled_sessions: int
    completion_rate: float  # completed / total
    by_subject: dict[str, SubjectAdherence] = field(default_factory=dict)


@dataclass(frozen=True)
class DailyAdherence:
    """Consolidação diária de cumprimento de metas."""

    date_str: str
    metrics: AdherenceMetrics


@dataclass(frozen=True)
class WeeklyAdherence:
    """Consolidação semanal de cumprimento de metas."""

    week_start: str
    week_end: str
    metrics: AdherenceMetrics
    daily_metrics: dict[str, AdherenceMetrics] = field(default_factory=dict)


def calculate_metrics(
    sessions: Sequence[sqlite3.Row | Mapping[str, Any]],
) -> AdherenceMetrics:
    """Calcula métricas de aderência a partir de uma coleção de sessões."""
    total_planned = 0
    total_actual = 0
    completed = 0
    partial = 0
    skipped = 0
    cancelled = 0

    subj_planned: dict[str, int] = defaultdict(int)
    subj_actual: dict[str, int] = defaultdict(int)
    subj_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for s in sessions:
        subject = str(s["subject"])
        status = str(s["status"])
        planned_m = int(s["planned_minutes"] or 0)
        actual_m = int(s["actual_minutes"] or 0)

        total_planned += planned_m
        total_actual += actual_m

        subj_planned[subject] += planned_m
        subj_actual[subject] += actual_m
        subj_counts[subject][status] += 1

        if status == "completed":
            completed += 1
        elif status == "partial":
            partial += 1
        elif status == "skipped":
            skipped += 1
        elif status == "cancelled":
            cancelled += 1

    total_sessions = len(sessions)
    completion_rate = (
        round(completed / total_sessions, 4) if total_sessions > 0 else 0.0
    )
    minutes_adherence = (
        round(total_actual / total_planned, 4) if total_planned > 0 else 0.0
    )

    by_subject: dict[str, SubjectAdherence] = {}
    for subj, p_min in subj_planned.items():
        a_min = subj_actual[subj]
        counts = subj_counts[subj]
        subj_total = sum(counts.values())
        rate = round(a_min / p_min, 4) if p_min > 0 else 0.0
        by_subject[subj] = SubjectAdherence(
            subject=subj,
            planned_minutes=p_min,
            actual_minutes=a_min,
            adherence_rate=rate,
            planned_sessions=subj_total,
            completed_sessions=counts.get("completed", 0),
            partial_sessions=counts.get("partial", 0),
            skipped_sessions=counts.get("skipped", 0),
            cancelled_sessions=counts.get("cancelled", 0),
        )

    return AdherenceMetrics(
        total_planned_minutes=total_planned,
        total_actual_minutes=total_actual,
        minutes_adherence_rate=minutes_adherence,
        total_sessions=total_sessions,
        completed_sessions=completed,
        partial_sessions=partial,
        skipped_sessions=skipped,
        cancelled_sessions=cancelled,
        completion_rate=completion_rate,
        by_subject=by_subject,
    )


def _parse_target_date(target: date | str) -> date:
    if isinstance(target, date) and not isinstance(target, datetime):
        return target
    if isinstance(target, datetime):
        return target.date()
    return date.fromisoformat(target)


def calculate_daily_adherence(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    target_date: date | str,
) -> DailyAdherence:
    """Calcula a aderência de um dia específico em UTC."""
    parsed_date = _parse_target_date(target_date)
    date_str = parsed_date.isoformat()

    day_start = f"{date_str}T00:00:00.000000+00:00"
    day_end = f"{date_str}T23:59:59.999999+00:00"

    sessions = persistence.list_study_sessions(
        conn,
        user_id=user_id,
        since=day_start,
        until=day_end,
    )
    metrics = calculate_metrics(sessions)
    return DailyAdherence(date_str=date_str, metrics=metrics)


def calculate_weekly_adherence(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    week_start: date | str,
) -> WeeklyAdherence:
    """Calcula a aderência de uma janela de 7 dias consecutivos."""
    start_dt = _parse_target_date(week_start)
    end_dt = start_dt + timedelta(days=6)

    start_str = start_dt.isoformat()
    end_str = end_dt.isoformat()

    since_iso = f"{start_str}T00:00:00.000000+00:00"
    until_iso = f"{end_str}T23:59:59.999999+00:00"

    all_sessions = persistence.list_study_sessions(
        conn,
        user_id=user_id,
        since=since_iso,
        until=until_iso,
    )

    overall_metrics = calculate_metrics(all_sessions)

    # Agrupar por dia individual dentro da semana
    daily_metrics: dict[str, AdherenceMetrics] = {}
    for offset in range(7):
        current_day = start_dt + timedelta(days=offset)
        curr_str = current_day.isoformat()
        day_since = f"{curr_str}T00:00:00.000000+00:00"
        day_until = f"{curr_str}T23:59:59.999999+00:00"
        day_sessions = [
            s
            for s in all_sessions
            if day_since <= (s["planned_at"] or s["created_at"]) <= day_until
        ]
        daily_metrics[curr_str] = calculate_metrics(day_sessions)

    return WeeklyAdherence(
        week_start=start_str,
        week_end=end_str,
        metrics=overall_metrics,
        daily_metrics=daily_metrics,
    )


def start_study_session(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    started_at: str | datetime | None = None,
) -> None:
    """Inicia formalmente uma sessão de estudo e registra evento probatório."""
    session = persistence.get_study_session(conn, session_id)
    if session is None:
        raise ValueError(f"Sessão id {session_id} não encontrada.")

    start_time = persistence._normalize_iso_utc(started_at)
    persistence.update_study_session(
        conn,
        session_id=session_id,
        status="partial",
        started_at=start_time,
    )
    persistence.record_event(
        conn,
        user_id=session["user_id"],
        event_type="STUDY_STARTED",
        source_type="USER_EXPLICIT",
        source_id=f"session-{session_id}",
        payload={
            "session_id": session_id,
            "subject": session["subject"],
            "topic": session["topic"],
            "planned_minutes": session["planned_minutes"],
            "started_at": start_time,
        },
        timestamp=start_time,
    )


def complete_study_session(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    actual_minutes: int,
    finished_at: str | datetime | None = None,
    notes: str | None = None,
    status: str = "completed",
) -> None:
    """Conclui (total ou parcialmente) uma sessão e registra evento probatório."""
    session = persistence.get_study_session(conn, session_id)
    if session is None:
        raise ValueError(f"Sessão id {session_id} não encontrada.")

    if status not in ("completed", "partial"):
        raise ValueError("Status de conclusão deve ser 'completed' ou 'partial'.")

    finish_time = persistence._normalize_iso_utc(finished_at)
    persistence.update_study_session(
        conn,
        session_id=session_id,
        status=status,
        actual_minutes=actual_minutes,
        finished_at=finish_time,
        notes=notes,
    )
    persistence.record_event(
        conn,
        user_id=session["user_id"],
        event_type="STUDY_COMPLETED",
        source_type="USER_EXPLICIT",
        source_id=f"session-{session_id}",
        payload={
            "session_id": session_id,
            "subject": session["subject"],
            "topic": session["topic"],
            "planned_minutes": session["planned_minutes"],
            "actual_minutes": actual_minutes,
            "status": status,
            "finished_at": finish_time,
            "notes": notes,
        },
        timestamp=finish_time,
    )


def skip_study_session(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    notes: str | None = None,
) -> None:
    """Marca uma sessão como pulada e registra evento probatório."""
    session = persistence.get_study_session(conn, session_id)
    if session is None:
        raise ValueError(f"Sessão id {session_id} não encontrada.")

    now_iso = persistence._normalize_iso_utc()
    persistence.update_study_session(
        conn,
        session_id=session_id,
        status="skipped",
        notes=notes,
    )
    persistence.record_event(
        conn,
        user_id=session["user_id"],
        event_type="STUDY_SKIPPED",
        source_type="USER_EXPLICIT",
        source_id=f"session-{session_id}",
        payload={
            "session_id": session_id,
            "subject": session["subject"],
            "topic": session["topic"],
            "planned_minutes": session["planned_minutes"],
            "status": "skipped",
            "notes": notes,
        },
        timestamp=now_iso,
    )
