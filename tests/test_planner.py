"""Testes de planejamento diário, persistência e motor de adaptação noturna."""

import sqlite3
from pathlib import Path

import pytest

from quercus import persistence, planner


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return persistence.connect(str(tmp_path / "test_planner.db"))


def test_study_plan_and_items_persistence(conn: sqlite3.Connection) -> None:
    plan_id = persistence.record_study_plan(
        conn,
        user_id="gabriel",
        plan_date="2026-09-18",
        title="Plano de Sexta-feira",
    )
    assert plan_id > 0

    item1 = persistence.add_study_plan_item(
        conn,
        plan_id=plan_id,
        subject="História do Brasil",
        duration_minutes=60,
        topic="Segundo Reinado",
        priority=1,
    )
    item2 = persistence.add_study_plan_item(
        conn,
        plan_id=plan_id,
        subject="Política Internacional",
        duration_minutes=45,
        priority=2,
    )
    assert item1 > 0
    assert item2 > 0

    # Recupera o plano completo
    full_plan = persistence.get_study_plan(conn, plan_id)
    assert full_plan is not None
    assert full_plan["title"] == "Plano de Sexta-feira"
    assert len(full_plan["items"]) == 2
    assert full_plan["items"][0]["subject"] == "História do Brasil"
    assert full_plan["items"][1]["subject"] == "Política Internacional"

    # Atualiza status de um item
    persistence.update_plan_item_status(
        conn, item_id=item1, status="completed", reason="Concluído com sucesso"
    )
    updated_plan = persistence.get_study_plan(conn, plan_id)
    assert updated_plan is not None
    assert updated_plan["items"][0]["status"] == "completed"


def test_nightly_adaptation_complete_adherence(conn: sqlite3.Connection) -> None:
    plan_id = persistence.record_study_plan(
        conn,
        user_id="gabriel",
        plan_date="2026-09-18",
        title="Meta Cumprida",
    )
    persistence.add_study_plan_item(
        conn,
        plan_id=plan_id,
        subject="História do Brasil",
        duration_minutes=60,
        priority=1,
    )

    # Registra sessão de estudo completada
    persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="História do Brasil",
        planned_minutes=60,
        actual_minutes=60,
        status="completed",
        planned_at="2026-09-18T09:00:00Z",
        finished_at="2026-09-18T10:00:00Z",
    )

    report = planner.adapt_daily_plan(conn, plan_id=plan_id)
    assert report.completion_rate == 1.0
    assert len(report.decisions) == 1
    assert report.decisions[0].strategy == "manter"

    # Confirma status do plano adaptado
    plan = persistence.get_study_plan(conn, plan_id)
    assert plan is not None
    assert plan["status"] == "adapted"


def test_nightly_adaptation_divergent_scenarios_and_memory_awareness(
    conn: sqlite3.Connection,
) -> None:
    # Memória ativa de fadiga noturna
    persistence.record_memory(
        conn,
        user_id="gabriel",
        memory_type="inferential",
        statement="Baixo rendimento cognitivo em sessões extensas à noite.",
        status="active",
        confidence=0.88,
    )

    plan_id = persistence.record_study_plan(
        conn,
        user_id="gabriel",
        plan_date="2026-09-18",
        title="Dia de Ajuste",
    )
    # Item 1: HB (90 min) - realizou 80 min (falta 10 <= 20) -> reduzir
    it1 = persistence.add_study_plan_item(
        conn,
        plan_id=plan_id,
        subject="História do Brasil",
        duration_minutes=90,
        priority=1,
    )
    # Item 2: PI (60 min) - realizou 20 min (falta 40 > 20) -> adiar
    it2 = persistence.add_study_plan_item(
        conn,
        plan_id=plan_id,
        subject="Política Internacional",
        duration_minutes=60,
        priority=1,
    )
    # Item 3: DI (90 min) - prioridade 1 com memória de fadiga -> redistribuir
    it3 = persistence.add_study_plan_item(
        conn,
        plan_id=plan_id,
        subject="Direito Internacional",
        duration_minutes=90,
        priority=1,
    )
    # Item 4: Inglês (45 min) - não iniciado, prioridade 3 -> cancelar
    it4 = persistence.add_study_plan_item(
        conn,
        plan_id=plan_id,
        subject="Língua Inglesa",
        duration_minutes=45,
        priority=3,
    )

    # Realizou 80 min de HB e 20 min de PI
    persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="História do Brasil",
        planned_minutes=90,
        actual_minutes=80,
        status="partial",
        planned_at="2026-09-18T09:00:00Z",
    )
    persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="Política Internacional",
        planned_minutes=60,
        actual_minutes=20,
        status="partial",
        planned_at="2026-09-18T14:00:00Z",
    )

    report = planner.adapt_daily_plan(conn, plan_id=plan_id)

    decisions_map = {d.item_id: d for d in report.decisions}
    assert decisions_map[it1].strategy == "reduzir"
    assert decisions_map[it1].adapted_duration == 80

    assert decisions_map[it2].strategy == "adiar"
    assert decisions_map[it2].adapted_duration == 40
    assert decisions_map[it2].target_date == "2026-09-19"

    assert decisions_map[it3].strategy == "redistribuir"
    assert decisions_map[it3].adapted_duration == 45
    assert decisions_map[it3].target_date == "2026-09-19"

    assert decisions_map[it4].strategy == "cancelar"
    assert decisions_map[it4].adapted_duration == 0

    # Verifica que o evento PLAN_ADAPTED foi registrado
    events = persistence.list_events(conn, user_id="gabriel")
    plan_events = [e for e in events if e["event_type"] == "PLAN_ADAPTED"]
    assert len(plan_events) == 1
    import json

    payload = json.loads(plan_events[0]["payload_json"])
    assert payload["plan_id"] == plan_id


def test_conversational_formatting_and_response(conn: sqlite3.Connection) -> None:
    plan_id = persistence.record_study_plan(
        conn,
        user_id="gabriel",
        plan_date="2026-09-18",
        title="Plano de Teste Conversacional",
    )
    persistence.add_study_plan_item(
        conn,
        plan_id=plan_id,
        subject="História do Brasil",
        duration_minutes=60,
        priority=1,
    )

    plan = persistence.get_study_plan(conn, plan_id)
    assert plan is not None

    chat_text = planner.format_plan_for_chat(plan)
    assert "Plano de Teste Conversacional" in chat_text
    assert "História do Brasil" in chat_text

    # Testa aceitação
    resp_accept = planner.handle_plan_response(conn, plan_id=plan_id, action="accept")
    assert "aceito e ativado" in resp_accept
    updated_plan = persistence.get_study_plan(conn, plan_id)
    assert updated_plan is not None
    assert updated_plan["status"] == "active"

    # Testa rejeição
    resp_reject = planner.handle_plan_response(conn, plan_id=plan_id, action="reject")
    assert "retornou para rascunho" in resp_reject
    draft_plan = persistence.get_study_plan(conn, plan_id)
    assert draft_plan is not None
    assert draft_plan["status"] == "draft"
