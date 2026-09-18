"""Testes da pipeline de consolidação noturna (Dreaming: Light, REM e Deep)."""

import sqlite3
from pathlib import Path

import pytest

from quercus import adherence, dreaming, memory, persistence


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return persistence.connect(str(tmp_path / "test_dreaming.db"))


def test_light_tier_extracts_observations_without_mutating_memories(
    conn: sqlite3.Connection,
) -> None:
    # Registra uma sessão matutina concluída
    session_id = persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="História do Brasil",
        topic="Período Joanino",
        planned_minutes=90,
        actual_minutes=90,
        status="completed",
        started_at="2026-09-18T08:30:00Z",
        finished_at="2026-09-18T10:00:00Z",
    )
    # Registra evento correspondente
    persistence.record_event(
        conn,
        user_id="gabriel",
        event_type="STUDY_COMPLETED",
        source_type="USER_EXPLICIT",
        source_id=f"session-{session_id}",
        payload={"subject": "História do Brasil", "actual_minutes": 90},
        timestamp="2026-09-18T10:00:00Z",
    )

    # Extrai observações
    obs = dreaming.extract_study_observations(conn, user_id="gabriel")
    assert len(obs) >= 1
    assert "período matutino" in obs[0].statement

    # Nenhuma memória foi criada (Light tier não altera memórias)
    memories = persistence.list_memories(conn, user_id="gabriel")
    assert len(memories) == 0


def test_rem_daily_consolidation_creates_and_reinforces_candidate(
    conn: sqlite3.Connection,
) -> None:
    # Dia 1: primeira sessão matutina
    s1 = persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="História do Brasil",
        planned_minutes=60,
        actual_minutes=60,
        status="completed",
        started_at="2026-09-15T08:00:00Z",
        finished_at="2026-09-15T09:00:00Z",
    )
    adherence.complete_study_session(
        conn, session_id=s1, actual_minutes=60, finished_at="2026-09-15T09:00:00Z"
    )

    report_dia1 = dreaming.run_rem_consolidation(conn, user_id="gabriel")
    assert report_dia1.run_type == "REM"
    assert len(report_dia1.decisions) >= 1
    assert report_dia1.decisions[0].action == "created_candidate"

    # Confirma que status é 'candidate' e NÃO 'active'
    candidates = persistence.list_memories(conn, user_id="gabriel", status="candidate")
    assert len(candidates) == 1
    cand_id = candidates[0]["id"]
    conf_dia1 = candidates[0]["confidence"]

    # Dia 2: segunda sessão matutina
    s2 = persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="História do Brasil",
        planned_minutes=60,
        actual_minutes=65,
        status="completed",
        started_at="2026-09-16T08:15:00Z",
        finished_at="2026-09-16T09:20:00Z",
    )
    adherence.complete_study_session(
        conn, session_id=s2, actual_minutes=65, finished_at="2026-09-16T09:20:00Z"
    )

    report_dia2 = dreaming.run_rem_consolidation(conn, user_id="gabriel")
    assert report_dia2.decisions[0].action == "reinforced_candidate"
    assert report_dia2.decisions[0].memory_id == cand_id

    # Confirma fortalecimento e aumento da confiança
    cand_atualizado = persistence.get_memory_with_evidence(conn, cand_id)
    assert cand_atualizado is not None
    assert cand_atualizado["confidence"] > conf_dia1
    assert len(cand_atualizado["evidence"]) >= 2

    # Verifica evento probatório do REM
    events = persistence.list_events(conn, user_id="gabriel")
    rem_events = [e for e in events if e["event_type"] == "DREAM_REM_COMPLETED"]
    assert len(rem_events) == 2


def test_deep_consolidation_rejects_candidate_with_contradictions(
    conn: sqlite3.Connection,
) -> None:
    # Cria candidato com confiança alta mas com contradição não resolvida
    mem_id = persistence.record_memory(
        conn,
        user_id="gabriel",
        memory_type="inferential",
        statement="Alta capacidade de estudo após o almoço.",
        status="candidate",
        confidence=0.85,
    )
    e1 = persistence.record_event(
        conn,
        user_id="gabriel",
        event_type="STUDY_COMPLETED",
        payload={},
        source_type="USER_OBSERVED",
    )
    e2 = persistence.record_event(
        conn,
        user_id="gabriel",
        event_type="USER_CORRECTION",
        payload={"text": "Fico com muito sono após o almoço"},
        source_type="USER_EXPLICIT",
    )
    persistence.link_memory_evidence(
        conn, memory_id=mem_id, event_id=e1, relationship="supports"
    )
    persistence.link_memory_evidence(
        conn, memory_id=mem_id, event_id=e2, relationship="contradicts"
    )

    deep_report = dreaming.run_deep_consolidation(conn, user_id="gabriel")
    assert len(deep_report.decisions) == 1
    assert deep_report.decisions[0].action == "rejected"

    # Confirma status rejected
    mem = persistence.get_memory_with_evidence(conn, mem_id)
    assert mem is not None
    assert mem["status"] == "rejected"


def test_five_day_study_simulation_culminates_in_promoted_morning_memory(
    conn: sqlite3.Connection,
) -> None:
    """Critério 5 da Issue #6:

    Simula 5 dias de estudos matutinos culminando na consolidação
    de uma inferência de estudo matutino sustentada por dados no Deep dreaming.
    """
    dias = [
        ("2026-09-14", "História do Brasil", 60),
        ("2026-09-15", "História do Brasil", 75),
        ("2026-09-16", "Política Internacional", 60),
        ("2026-09-17", "Política Internacional", 90),
        ("2026-09-18", "Direito Internacional", 60),
    ]

    # Simula 5 dias de sessões matutinas com REM noturno diário
    for dia_str, materia, duracao in dias:
        sess_id = persistence.record_study_session(
            conn,
            user_id="cacd_gabriel",
            subject=materia,
            planned_minutes=duracao,
            actual_minutes=duracao,
            status="completed",
            started_at=f"{dia_str}T08:30:00Z",
            finished_at=f"{dia_str}T09:30:00Z",
            source="USER_EXPLICIT",
        )
        # Completa sessão e emite evento probatório
        adherence.complete_study_session(
            conn,
            session_id=sess_id,
            actual_minutes=duracao,
            finished_at=f"{dia_str}T09:30:00Z",
        )

        # Roda REM diário ao final de cada dia
        dreaming.run_rem_consolidation(conn, user_id="cacd_gabriel")

    # Verifica o estado dos candidatos antes do Deep:
    # Deve haver um candidato para estudo matutino acumulando evidências
    candidates = persistence.list_memories(
        conn, user_id="cacd_gabriel", status="candidate"
    )
    morning_cand = next(c for c in candidates if "período matutino" in c["statement"])
    morning_with_ev = persistence.get_memory_with_evidence(conn, morning_cand["id"])
    assert morning_with_ev is not None
    # Deve ter 5 evidências de suporte
    assert len(morning_with_ev["evidence"]) >= 5
    assert morning_cand["confidence"] >= 0.80

    # Roda a consolidação profunda semanal (Deep)
    deep_report = dreaming.run_deep_consolidation(
        conn,
        user_id="cacd_gabriel",
        config=memory.PromotionGateConfig(
            min_confidence=0.75,
            min_evidence_count=3,
        ),
    )

    # Decisões do Deep devem conter a promoção
    promoted_decisions = [d for d in deep_report.decisions if d.action == "promoted"]
    assert len(promoted_decisions) >= 1
    promoted_morning = next(
        d for d in promoted_decisions if "período matutino" in d.statement
    )
    assert promoted_morning.memory_id == morning_cand["id"]

    # Verifica integridade na base: status agora é 'active'
    active_mems = persistence.list_memories(
        conn, user_id="cacd_gabriel", status="active"
    )
    assert len(active_mems) >= 1
    promoted_mem = persistence.get_memory_with_evidence(conn, morning_cand["id"])
    assert promoted_mem is not None
    assert promoted_mem["status"] == "active"

    # Prova Forense: 'Por que você acha isso sobre mim?'
    # Cada uma das 5 sessões está preservada com seu timestamp original
    evidence_events = promoted_mem["evidence"]
    assert len(evidence_events) >= 5
    dates_found = {
        e["event_timestamp"][:10] for e in evidence_events if e["event_timestamp"]
    }
    assert dates_found == {
        "2026-09-14",
        "2026-09-15",
        "2026-09-16",
        "2026-09-17",
        "2026-09-18",
    }
