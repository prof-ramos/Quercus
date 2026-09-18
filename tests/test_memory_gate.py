"""Testes do gate determinístico de promoção e ciclo de vida de memórias."""

import sqlite3
from pathlib import Path

from quercus import memory, persistence


def _create_conn(tmp_path: Path) -> sqlite3.Connection:
    return persistence.connect(str(tmp_path / "test_memory.db"))


def test_gate_rejects_insufficient_evidence(tmp_path: Path) -> None:
    conn = _create_conn(tmp_path)
    mem_id = persistence.record_memory(
        conn,
        user_id="user_01",
        memory_type="inferential",
        statement="Rendimento superior pela manhã.",
        status="candidate",
        confidence=0.85,
    )
    # Apenas 1 evidência de suporte (limiar padrão é 3)
    ev_event = persistence.record_event(
        conn, user_id="user_01", event_type="STUDY_SESSION", payload={}
    )
    persistence.link_memory_evidence(conn, memory_id=mem_id, event_id=ev_event)

    decision = memory.evaluate_promotion(conn, mem_id)
    assert not decision.eligible
    assert "Contagem de evidências insuficiente" in decision.reason

    # Tenta promover
    promote_res = memory.promote_candidate(conn, mem_id)
    assert not promote_res.eligible

    # Confirma que continuou candidate
    mem = persistence.get_memory_with_evidence(conn, mem_id)
    assert mem is not None
    assert mem["status"] == "candidate"


def test_gate_rejects_low_confidence(tmp_path: Path) -> None:
    conn = _create_conn(tmp_path)
    mem_id = persistence.record_memory(
        conn,
        user_id="user_01",
        memory_type="inferential",
        statement="Rendimento superior pela manhã.",
        status="candidate",
        confidence=0.50,  # abaixo de 0.70
    )
    for i in range(3):
        e_id = persistence.record_event(
            conn,
            user_id="user_01",
            event_type=f"STUDY_{i}",
            payload={},
            source_type="SYSTEM_OBSERVED",
        )
        persistence.link_memory_evidence(conn, memory_id=mem_id, event_id=e_id)

    decision = memory.evaluate_promotion(conn, mem_id)
    assert not decision.eligible
    assert "Confiança insuficiente" in decision.reason


def test_gate_rejects_unresolved_contradictions(tmp_path: Path) -> None:
    conn = _create_conn(tmp_path)
    mem_id = persistence.record_memory(
        conn,
        user_id="user_01",
        memory_type="inferential",
        statement="Rendimento superior pela manhã.",
        status="candidate",
        confidence=0.85,
    )
    for i in range(3):
        e_id = persistence.record_event(
            conn, user_id="user_01", event_type=f"STUDY_{i}", payload={}
        )
        persistence.link_memory_evidence(
            conn, memory_id=mem_id, event_id=e_id, relationship="supports"
        )

    # Adiciona 1 contradição
    contra_id = persistence.record_event(
        conn, user_id="user_01", event_type="STUDY_FAILED", payload={}
    )
    persistence.link_memory_evidence(
        conn, memory_id=mem_id, event_id=contra_id, relationship="contradicts"
    )

    decision = memory.evaluate_promotion(conn, mem_id)
    assert not decision.eligible
    assert "evidência(s) de contradição" in decision.reason


def test_gate_promotes_candidate_successfully(tmp_path: Path) -> None:
    conn = _create_conn(tmp_path)
    mem_id = persistence.record_memory(
        conn,
        user_id="user_01",
        memory_type="inferential",
        statement="História do Brasil rende melhor antes do expediente.",
        status="candidate",
        confidence=0.88,
    )

    # Adiciona 3 evidências de suporte com fontes válidas
    for i in range(3):
        e_id = persistence.record_event(
            conn,
            user_id="user_01",
            event_type=f"STUDY_SESSION_{i}",
            payload={"minutes": 45},
            source_type="USER_OBSERVED",
        )
        persistence.link_memory_evidence(
            conn, memory_id=mem_id, event_id=e_id, relationship="supports"
        )

    decision = memory.promote_candidate(conn, mem_id)
    assert decision.eligible
    assert "atendidos integralmente" in decision.reason

    # Status deve ser 'active'
    mem = persistence.get_memory_with_evidence(conn, mem_id)
    assert mem is not None
    assert mem["status"] == "active"

    # Evento MEMORY_PROMOTED deve constar no events
    events = persistence.list_events(conn, user_id="user_01")
    promoted_events = [e for e in events if e["event_type"] == "MEMORY_PROMOTED"]
    assert len(promoted_events) == 1
    assert promoted_events[0]["source_type"] == "AGENT_DERIVED"


def test_record_explicit_preference_bypasses_repetition_gate(
    tmp_path: Path,
) -> None:
    conn = _create_conn(tmp_path)
    mem_id = memory.record_explicit_preference(
        conn,
        user_id="user_gabriel",
        statement="Não quero estudar no horário de almoço.",
        memory_type="semantic",
        importance=2,
    )

    mem = persistence.get_memory_with_evidence(conn, mem_id)
    assert mem is not None
    assert mem["status"] == "active"
    assert mem["confidence"] == 1.0
    assert mem["source_origin"] == "USER_EXPLICIT"
    assert len(mem["evidence"]) == 1

    initial_ev = mem["evidence"][0]
    assert initial_ev["relationship"] == "supports"
    assert initial_ev["source_type"] == "USER_EXPLICIT"


def test_supersede_preference_audit_trail(tmp_path: Path) -> None:
    conn = _create_conn(tmp_path)
    old_id = memory.record_explicit_preference(
        conn,
        user_id="user_gabriel",
        statement="Estudar 45 minutos por bloco.",
    )

    new_id = memory.supersede_preference(
        conn,
        old_memory_id=old_id,
        new_statement="Estudar 30 minutos por bloco.",
        reason="Mudança de rotina profissional",
    )

    assert new_id != old_id

    # Memória antiga está 'superseded'
    old_mem = persistence.get_memory_with_evidence(conn, old_id)
    assert old_mem is not None
    assert old_mem["status"] == "superseded"

    # Nova memória está 'active' com referência à antiga
    new_mem = persistence.get_memory_with_evidence(conn, new_id)
    assert new_mem is not None
    assert new_mem["status"] == "active"
    assert new_mem["supersedes_id"] == old_id
    assert new_mem["statement"] == "Estudar 30 minutos por bloco."

    # Evento de auditoria MEMORY_SUPERSEDED registrado
    events = persistence.list_events(conn, user_id="user_gabriel")
    audit_events = [e for e in events if e["event_type"] == "MEMORY_SUPERSEDED"]
    assert len(audit_events) == 1
