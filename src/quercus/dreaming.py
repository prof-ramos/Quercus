"""Pipeline de Consolidação Noturna (Dreaming / REM diário e Deep semanal).

Implementa:
- Tier Light: extração de observações e padrões a partir de eventos.
- Tier REM (diário): identificação de recorrências e reforço de candidatos.
- Tier Deep (semanal / sob demanda): avaliação no promotion gate.
- Trilha transparente em DREAMS / eventos de auditoria com consolidation_id.
"""

import sqlite3
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, time

from quercus import memory, persistence


@dataclass(frozen=True)
class PatternObservation:
    """Observação preliminar extraída de eventos ou sessões."""

    statement: str
    memory_type: str
    event_ids: list[int]
    confidence: float
    source_origin: str = "AGENT_DERIVED"


@dataclass(frozen=True)
class DreamDecision:
    """Decisão individual tomada durante uma rodada de Dreaming."""

    memory_id: int
    statement: str
    action: str  # created_candidate, reinforced_candidate, promoted, etc.
    reason: str
    confidence: float | None
    evidence_count: int


@dataclass(frozen=True)
class DreamReport:
    """Relatório estruturado de consolidação (diário DREAMS)."""

    consolidation_id: str
    user_id: str
    run_type: str  # REM ou DEEP
    timestamp: str
    decisions: list[DreamDecision] = field(default_factory=list)
    summary: str = ""


def extract_study_observations(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> list[PatternObservation]:
    """Extrai observações estruturadas de estudo sem alterar memórias (Light tier)."""
    sessions = persistence.list_study_sessions(
        conn,
        user_id=user_id,
        since=since,
        until=until,
    )

    observations: list[PatternObservation] = []
    if not sessions:
        return observations

    # 1. Análise de padrão matutino: sessões iniciadas entre 06:00 e 12:00
    morning_sessions: list[sqlite3.Row] = []
    subject_completed: dict[str, list[sqlite3.Row]] = defaultdict(list)

    for s in sessions:
        if s["status"] == "completed":
            subject_completed[s["subject"]].append(s)

        # Analisar horário de início ou planejado
        ts_str = s["started_at"] or s["planned_at"] or s["created_at"]
        if ts_str:
            clean_ts = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts).astimezone(UTC)
            if time(6, 0) <= dt.time() < time(12, 0) and s["status"] in (
                "completed",
                "partial",
            ):
                morning_sessions.append(s)

    # Identifica padrão matutino se houver sessões matutinas com bom rendimento
    if len(morning_sessions) >= 1:
        # Busca eventos relacionados ou cria eventos observados para as sessões
        ev_ids: list[int] = []
        for ms in morning_sessions:
            # Busca eventos de estudo correspondentes
            ev_list = conn.execute(
                """
                SELECT id FROM events
                WHERE user_id = ? AND source_id = ?
                ORDER BY id ASC
                """,
                (user_id, f"session-{ms['id']}"),
            ).fetchall()
            for r in ev_list:
                ev_ids.append(r["id"])

            # Se não houver evento explícito, cria um evento SYSTEM_OBSERVED
            if not ev_list:
                eid = persistence.record_event(
                    conn,
                    user_id=user_id,
                    event_type="STUDY_OBSERVATION",
                    source_type="SYSTEM_OBSERVED",
                    source_id=f"session-{ms['id']}",
                    payload={
                        "session_id": ms["id"],
                        "subject": ms["subject"],
                        "actual_minutes": ms["actual_minutes"],
                        "pattern": "morning_study",
                    },
                    timestamp=ms["started_at"] or ms["created_at"],
                )
                ev_ids.append(eid)

        observations.append(
            PatternObservation(
                statement=(
                    "Rendimento consistente e preferência por blocos "
                    "de estudo no período matutino."
                ),
                memory_type="inferential",
                event_ids=ev_ids,
                confidence=min(0.90, round(0.60 + len(morning_sessions) * 0.08, 2)),
            )
        )

    # 2. Análise de consistência por matéria
    for subject, s_list in subject_completed.items():
        if len(s_list) >= 2:
            s_ev_ids: list[int] = []
            for s in s_list:
                ev_list = conn.execute(
                    """
                    SELECT id FROM events
                    WHERE user_id = ? AND source_id = ?
                    """,
                    (user_id, f"session-{s['id']}"),
                ).fetchall()
                for r in ev_list:
                    s_ev_ids.append(r["id"])
            if s_ev_ids:
                observations.append(
                    PatternObservation(
                        statement=(
                            f"Foco constante e alta taxa de conclusão em {subject}."
                        ),
                        memory_type="inferential",
                        event_ids=s_ev_ids,
                        confidence=min(0.85, round(0.65 + len(s_list) * 0.05, 2)),
                    )
                )

    return observations


def run_rem_consolidation(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> DreamReport:
    """Executa consolidação diária (REM): recorrências e reforço de candidatos."""
    consolidation_id = str(uuid.uuid4())
    timestamp = persistence._normalize_iso_utc()
    decisions: list[DreamDecision] = []

    observations = extract_study_observations(
        conn,
        user_id=user_id,
        since=since,
        until=until,
    )

    # Busca memórias existentes do usuário
    existing_memories = persistence.list_memories(conn, user_id=user_id, limit=200)
    candidate_map = {
        m["statement"]: m for m in existing_memories if m["status"] == "candidate"
    }
    active_map = {
        m["statement"]: m for m in existing_memories if m["status"] == "active"
    }

    for obs in observations:
        # Se a afirmação já está consolidada como active, não cria candidato duplicado
        if obs.statement in active_map:
            continue

        if obs.statement in candidate_map:
            # Reforça candidato existente
            cand = candidate_map[obs.statement]
            cand_id = cand["id"]

            # Obtém evidências já vinculadas
            existing_ev = conn.execute(
                "SELECT event_id FROM memory_evidence WHERE memory_id = ?",
                (cand_id,),
            ).fetchall()
            existing_ev_ids = {r["event_id"] for r in existing_ev}

            new_linked = 0
            for eid in obs.event_ids:
                if eid not in existing_ev_ids:
                    persistence.link_memory_evidence(
                        conn,
                        memory_id=cand_id,
                        event_id=eid,
                        relationship="supports",
                    )
                    existing_ev_ids.add(eid)
                    new_linked += 1

            # Incrementa confiança com novas evidências observadas
            curr_conf = float(cand["confidence"] or 0.60)
            new_conf = min(0.95, round(curr_conf + (new_linked * 0.08), 2))
            persistence.update_memory_status(
                conn,
                memory_id=cand_id,
                status="candidate",
                confidence=new_conf,
            )

            total_ev_count = len(existing_ev_ids)
            decisions.append(
                DreamDecision(
                    memory_id=cand_id,
                    statement=obs.statement,
                    action="reinforced_candidate",
                    reason=(
                        f"Candidato reforçado com {new_linked} nova(s) evidência(s). "
                        f"Total: {total_ev_count} evidências. "
                        f"Confiança: {new_conf:.2f}."
                    ),
                    confidence=new_conf,
                    evidence_count=total_ev_count,
                )
            )
        else:
            # Cria novo candidato na tabela memories
            new_cand_id = persistence.record_memory(
                conn,
                user_id=user_id,
                memory_type=obs.memory_type,
                statement=obs.statement,
                status="candidate",
                confidence=obs.confidence,
                importance=1,
                source_origin=obs.source_origin,
            )
            for eid in obs.event_ids:
                persistence.link_memory_evidence(
                    conn,
                    memory_id=new_cand_id,
                    event_id=eid,
                    relationship="supports",
                )

            decisions.append(
                DreamDecision(
                    memory_id=new_cand_id,
                    statement=obs.statement,
                    action="created_candidate",
                    reason=(
                        f"Novo candidato formulado a partir de observações "
                        f"com {len(obs.event_ids)} evidência(s) inicial(is)."
                    ),
                    confidence=obs.confidence,
                    evidence_count=len(obs.event_ids),
                )
            )

    # Emite evento probatório da rodada REM
    summary = (
        f"Consolidação REM concluída. {len(decisions)} decisão(ões) de candidatos."
    )
    persistence.record_event(
        conn,
        user_id=user_id,
        event_type="DREAM_REM_COMPLETED",
        source_type="AGENT_DERIVED",
        source_id=f"dream-rem-{consolidation_id}",
        payload={
            "consolidation_id": consolidation_id,
            "run_type": "REM",
            "decisions_count": len(decisions),
            "decisions": [
                {
                    "memory_id": d.memory_id,
                    "action": d.action,
                    "statement": d.statement,
                    "reason": d.reason,
                    "confidence": d.confidence,
                    "evidence_count": d.evidence_count,
                }
                for d in decisions
            ],
            "summary": summary,
        },
        timestamp=timestamp,
    )

    return DreamReport(
        consolidation_id=consolidation_id,
        user_id=user_id,
        run_type="REM",
        timestamp=timestamp,
        decisions=decisions,
        summary=summary,
    )


def run_deep_consolidation(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    config: memory.PromotionGateConfig | None = None,
) -> DreamReport:
    """Executa consolidação profunda (Deep): avalia candidatos no promotion gate."""
    consolidation_id = str(uuid.uuid4())
    timestamp = persistence._normalize_iso_utc()
    decisions: list[DreamDecision] = []

    cfg = config or memory.PromotionGateConfig()

    candidates = persistence.list_memories(
        conn, user_id=user_id, status="candidate", limit=200
    )

    for cand in candidates:
        cand_id = cand["id"]
        eval_result = memory.evaluate_promotion(conn, cand_id, config=cfg)

        if eval_result.eligible:
            # Promove deterministicamente para active
            memory.promote_candidate(conn, cand_id, config=cfg)
            decisions.append(
                DreamDecision(
                    memory_id=cand_id,
                    statement=cand["statement"],
                    action="promoted",
                    reason=eval_result.reason,
                    confidence=eval_result.confidence,
                    evidence_count=eval_result.evidence_count,
                )
            )
        elif eval_result.contradiction_count > 0 and not cfg.allow_contradictions:
            # Se houver contradições não permitidas, rejeita
            persistence.update_memory_status(conn, memory_id=cand_id, status="rejected")
            decisions.append(
                DreamDecision(
                    memory_id=cand_id,
                    statement=cand["statement"],
                    action="rejected",
                    reason=eval_result.reason,
                    confidence=eval_result.confidence,
                    evidence_count=eval_result.evidence_count,
                )
            )
        else:
            # Mantém candidato aguardando mais evidências
            decisions.append(
                DreamDecision(
                    memory_id=cand_id,
                    statement=cand["statement"],
                    action="kept_candidate",
                    reason=eval_result.reason,
                    confidence=eval_result.confidence,
                    evidence_count=eval_result.evidence_count,
                )
            )

    promoted_count = sum(1 for d in decisions if d.action == "promoted")
    rejected_count = sum(1 for d in decisions if d.action == "rejected")
    kept_count = sum(1 for d in decisions if d.action == "kept_candidate")

    summary = (
        f"Consolidação Deep concluída. Promovidas: {promoted_count}, "
        f"Rejeitadas: {rejected_count}, Mantidas como candidato: {kept_count}."
    )

    persistence.record_event(
        conn,
        user_id=user_id,
        event_type="DREAM_DEEP_COMPLETED",
        source_type="AGENT_DERIVED",
        source_id=f"dream-deep-{consolidation_id}",
        payload={
            "consolidation_id": consolidation_id,
            "run_type": "DEEP",
            "promoted_count": promoted_count,
            "rejected_count": rejected_count,
            "kept_count": kept_count,
            "decisions": [
                {
                    "memory_id": d.memory_id,
                    "action": d.action,
                    "statement": d.statement,
                    "reason": d.reason,
                    "confidence": d.confidence,
                    "evidence_count": d.evidence_count,
                }
                for d in decisions
            ],
            "summary": summary,
        },
        timestamp=timestamp,
    )

    return DreamReport(
        consolidation_id=consolidation_id,
        user_id=user_id,
        run_type="DEEP",
        timestamp=timestamp,
        decisions=decisions,
        summary=summary,
    )
