"""Planejamento diário estruturado e adaptação noturna de carga.

Aritmética determinística de agenda: o LLM decide prioridades, o código decide encaixes.
Estratégias: manter | adiar | redistribuir | reduzir | cancelar | substituir.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from quercus import persistence


@dataclass(frozen=True)
class ItemAdaptationDecision:
    """Decisão individual de adaptação sobre um item do plano."""

    item_id: int
    subject: str
    topic: str | None
    strategy: str  # manter, adiar, redistribuir, reduzir, cancelar
    original_duration: int
    adapted_duration: int
    reason: str
    target_date: str | None = None


@dataclass(frozen=True)
class PlanAdaptationReport:
    """Relatório estruturado de adaptação noturna de carga."""

    plan_id: int
    plan_date: str
    user_id: str
    planned_minutes: int
    actual_minutes: int
    completion_rate: float
    decisions: list[ItemAdaptationDecision] = field(default_factory=list)
    summary: str = ""


def adapt_daily_plan(
    conn: sqlite3.Connection,
    *,
    plan_id: int,
) -> PlanAdaptationReport:
    """Avalia o realizado contra o planejado e adapta a carga deterministicamente."""
    plan = persistence.get_study_plan(conn, plan_id)
    if plan is None:
        raise ValueError(f"Plano id {plan_id} não encontrado.")

    user_id = str(plan["user_id"])
    plan_date_str = str(plan["plan_date"])
    plan_date_dt = date.fromisoformat(plan_date_str)
    tomorrow_str = (plan_date_dt + timedelta(days=1)).isoformat()

    # Busca sessões de estudo realizadas no dia do plano
    day_start = f"{plan_date_str}T00:00:00.000000+00:00"
    day_end = f"{plan_date_str}T23:59:59.999999+00:00"
    sessions = persistence.list_study_sessions(
        conn, user_id=user_id, since=day_start, until=day_end
    )

    # Agrupa minutos realizados por disciplina
    actual_by_subject: dict[str, int] = defaultdict(int)
    for s in sessions:
        if s["status"] in ("completed", "partial"):
            actual_by_subject[s["subject"]] += int(s["actual_minutes"] or 0)

    # Consulta memórias ativas do aluno para personalizar adaptação
    active_mems = persistence.list_memories(conn, user_id=user_id, status="active")
    mem_statements = [m["statement"].lower() for m in active_mems]
    night_fatigue = any(
        "noite" in s or "almoço" in s or "sono" in s for s in mem_statements
    )

    items = plan.get("items", [])
    total_planned = sum(int(it["duration_minutes"]) for it in items)
    total_actual = sum(actual_by_subject.values())

    decisions: list[ItemAdaptationDecision] = []

    for it in items:
        item_id = int(it["id"])
        subject = str(it["subject"])
        topic = it["topic"]
        planned_dur = int(it["duration_minutes"])
        priority = int(it["priority"] or 1)
        realized = actual_by_subject.get(subject, 0)

        # Abate do realizado disponível
        minutes_done = min(planned_dur, realized)
        actual_by_subject[subject] = max(0, realized - minutes_done)

        if minutes_done >= planned_dur:
            # Item 100% cumprido
            persistence.update_plan_item_status(
                conn,
                item_id=item_id,
                status="completed",
                reason="Cumprido integralmente conforme planejado.",
            )
            decisions.append(
                ItemAdaptationDecision(
                    item_id=item_id,
                    subject=subject,
                    topic=topic,
                    strategy="manter",
                    original_duration=planned_dur,
                    adapted_duration=planned_dur,
                    reason="Meta atingida com sucesso.",
                )
            )
        elif minutes_done > 0:
            # Item parcialmente cumprido
            remaining = planned_dur - minutes_done
            if remaining <= 20:
                # Quase terminado: conclui e encerra sem carregar atraso
                persistence.update_plan_item_status(
                    conn,
                    item_id=item_id,
                    status="completed",
                    duration_minutes=minutes_done,
                    reason=f"Concluído com ajuste ({minutes_done} min realizados).",
                )
                decisions.append(
                    ItemAdaptationDecision(
                        item_id=item_id,
                        subject=subject,
                        topic=topic,
                        strategy="reduzir",
                        original_duration=planned_dur,
                        adapted_duration=minutes_done,
                        reason=(
                            f"Redução de {remaining} min residuais para "
                            f"evitar acúmulo de carga."
                        ),
                    )
                )
            else:
                # Parcial relevante: adia o saldo para o dia seguinte
                persistence.update_plan_item_status(
                    conn,
                    item_id=item_id,
                    status="deferred",
                    reason=f"{remaining} min remanescentes transferidos.",
                )
                decisions.append(
                    ItemAdaptationDecision(
                        item_id=item_id,
                        subject=subject,
                        topic=topic,
                        strategy="adiar",
                        original_duration=planned_dur,
                        adapted_duration=remaining,
                        reason=(
                            f"Item parcialmente estudado "
                            f"({minutes_done}/{planned_dur} min). "
                            f"Saldo de {remaining} min alocado para {tomorrow_str}."
                        ),
                        target_date=tomorrow_str,
                    )
                )
        else:
            # Item não iniciado (0 minutos realizados)
            if priority == 1:
                # Prioridade máxima: adiar ou redistribuir
                if planned_dur >= 90 or night_fatigue:
                    # Bloco pesado ou fadiga noturna: fraciona em 2 blocos
                    half_dur = planned_dur // 2
                    persistence.update_plan_item_status(
                        conn,
                        item_id=item_id,
                        status="deferred",
                        reason=f"Redistribuído em blocos de {half_dur} min.",
                    )
                    decisions.append(
                        ItemAdaptationDecision(
                            item_id=item_id,
                            subject=subject,
                            topic=topic,
                            strategy="redistribuir",
                            original_duration=planned_dur,
                            adapted_duration=half_dur,
                            reason=(
                                f"Carga pesada de {planned_dur} min fracionada em 2 "
                                f"sessões de {half_dur} min para preservar rendimento."
                            ),
                            target_date=tomorrow_str,
                        )
                    )
                else:
                    # Adia integralmente para o dia seguinte
                    persistence.update_plan_item_status(
                        conn,
                        item_id=item_id,
                        status="deferred",
                        reason=f"Transferido para {tomorrow_str}.",
                    )
                    decisions.append(
                        ItemAdaptationDecision(
                            item_id=item_id,
                            subject=subject,
                            topic=topic,
                            strategy="adiar",
                            original_duration=planned_dur,
                            adapted_duration=planned_dur,
                            reason=(
                                f"Prioridade alta não realizada. "
                                f"Alocada para {tomorrow_str}."
                            ),
                            target_date=tomorrow_str,
                        )
                    )
            elif priority == 2:
                # Prioridade média: reduz duração se tempo estiver apertado
                compressed = max(30, planned_dur // 2)
                persistence.update_plan_item_status(
                    conn,
                    item_id=item_id,
                    status="deferred",
                    duration_minutes=compressed,
                    reason=f"Carga reduzida para {compressed} min.",
                )
                decisions.append(
                    ItemAdaptationDecision(
                        item_id=item_id,
                        subject=subject,
                        topic=topic,
                        strategy="reduzir",
                        original_duration=planned_dur,
                        adapted_duration=compressed,
                        reason=(
                            f"Prioridade média reduzida de {planned_dur} para "
                            f"{compressed} min para proteger o descanso."
                        ),
                        target_date=tomorrow_str,
                    )
                )
            else:
                # Prioridade baixa (3): cancelar sem culpa para proteger o cronograma
                persistence.update_plan_item_status(
                    conn,
                    item_id=item_id,
                    status="cancelled",
                    reason="Cancelado para evitar efeito bola de neve.",
                )
                decisions.append(
                    ItemAdaptationDecision(
                        item_id=item_id,
                        subject=subject,
                        topic=topic,
                        strategy="cancelar",
                        original_duration=planned_dur,
                        adapted_duration=0,
                        reason=(
                            "Item de prioridade baixa cancelado para evitar "
                            "endividamento de horas de estudo."
                        ),
                    )
                )

    completion_rate = (
        round(total_actual / total_planned, 4) if total_planned > 0 else 0.0
    )

    pct = completion_rate * 100
    summary = (
        f"Adaptação de {plan_date_str}: {total_actual}/{total_planned} min "
        f"({pct:.1f}% de adesão). {len(decisions)} decisão(ões) de carga."
    )

    # Atualiza status do plano para 'adapted'
    conn.execute(
        "UPDATE study_plans SET status = 'adapted', updated_at = ? WHERE id = ?",
        (persistence._normalize_iso_utc(), plan_id),
    )
    conn.commit()

    # Registra evento probatório de auditoria
    persistence.record_event(
        conn,
        user_id=user_id,
        event_type="PLAN_ADAPTED",
        source_type="AGENT_DERIVED",
        source_id=f"plan-{plan_id}",
        payload={
            "plan_id": plan_id,
            "plan_date": plan_date_str,
            "total_planned_minutes": total_planned,
            "total_actual_minutes": total_actual,
            "completion_rate": completion_rate,
            "decisions": [
                {
                    "item_id": d.item_id,
                    "subject": d.subject,
                    "topic": d.topic,
                    "strategy": d.strategy,
                    "original_duration": d.original_duration,
                    "adapted_duration": d.adapted_duration,
                    "reason": d.reason,
                    "target_date": d.target_date,
                }
                for d in decisions
            ],
            "summary": summary,
        },
    )

    return PlanAdaptationReport(
        plan_id=plan_id,
        plan_date=plan_date_str,
        user_id=user_id,
        planned_minutes=total_planned,
        actual_minutes=total_actual,
        completion_rate=completion_rate,
        decisions=decisions,
        summary=summary,
    )


def format_plan_for_chat(
    plan: dict[str, Any],
    adaptation: PlanAdaptationReport | None = None,
) -> str:
    """Formata o plano diário e eventuais adaptações em texto limpo para o Telegram."""
    date_str = plan.get("plan_date", "hoje")
    title = plan.get("title", "Plano de Estudo")
    items = plan.get("items", [])

    lines = [
        f"📋 *{title}* ({date_str})",
        "",
    ]

    for it in items:
        topic_str = f" — {it['topic']}" if it.get("topic") else ""
        dur = it["duration_minutes"]
        prio = f"P{it.get('priority', 1)}"
        status = it.get("status", "pending")
        icon = "⏳"
        if status == "completed":
            icon = "✅"
        elif status == "deferred":
            icon = "➡️"
        elif status == "reduced":
            icon = "📉"
        elif status == "cancelled":
            icon = "❌"

        lines.append(f"{icon} *{it['subject']}*{topic_str} | {dur} min [{prio}]")

    if adaptation:
        lines.append("")
        lines.append("🌙 *Adaptação Noturna de Carga:*")
        for d in adaptation.decisions:
            if d.strategy != "manter":
                lines.append(f"• *{d.subject}* [{d.strategy.upper()}]: {d.reason}")

    return "\n".join(lines)


def handle_plan_response(
    conn: sqlite3.Connection,
    *,
    plan_id: int,
    action: str,  # accept, reject, edit
) -> str:
    """Processa a resposta do aluno via chat à proposta de plano ou adaptação."""
    plan = persistence.get_study_plan(conn, plan_id)
    if plan is None:
        return "Plano não encontrado."

    if action == "accept":
        conn.execute(
            "UPDATE study_plans SET status = 'active', updated_at = ? WHERE id = ?",
            (persistence._normalize_iso_utc(), plan_id),
        )
        conn.commit()
        return "✅ Plano aceito e ativado na sua agenda de estudos."
    elif action == "reject":
        conn.execute(
            "UPDATE study_plans SET status = 'draft', updated_at = ? WHERE id = ?",
            (persistence._normalize_iso_utc(), plan_id),
        )
        conn.commit()
        return (
            "🔄 Adaptação rejeitada. "
            "O plano retornou para rascunho para ajustes manuais."
        )
    elif action == "edit":
        return "✏️ Para editar, envie a matéria e o tempo (ex: 'Mude HB para 60 min')."
    else:
        return f"Ação desconhecida '{action}'."
