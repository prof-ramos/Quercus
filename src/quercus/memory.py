"""Submódulo de gerenciamento de memórias e promotion gate.

Implementa o gate determinístico de promoção (TODO.md §6),
tratamento de USER_EXPLICIT (TODO.md §7) e supersessão auditável (TODO.md §8).
"""

import sqlite3
from dataclasses import dataclass

from quercus import persistence


@dataclass(frozen=True)
class PromotionGateConfig:
    min_confidence: float = 0.70
    min_evidence_count: int = 3
    min_source_diversity: int = 1
    allow_contradictions: bool = False


@dataclass(frozen=True)
class PromotionDecision:
    eligible: bool
    reason: str
    confidence: float | None
    evidence_count: int
    contradiction_count: int
    source_diversity: int


def evaluate_promotion(
    conn: sqlite3.Connection,
    memory_id: int,
    config: PromotionGateConfig | None = None,
) -> PromotionDecision:
    """Avalia se uma memória candidata atende aos critérios do gate determinístico."""
    cfg = config or PromotionGateConfig()
    mem = persistence.get_memory_with_evidence(conn, memory_id)
    if mem is None:
        return PromotionDecision(
            eligible=False,
            reason="Memória não encontrada.",
            confidence=None,
            evidence_count=0,
            contradiction_count=0,
            source_diversity=0,
        )

    if mem["status"] != "candidate":
        return PromotionDecision(
            eligible=False,
            reason=f"Status atual '{mem['status']}' não é 'candidate'.",
            confidence=mem["confidence"],
            evidence_count=len(mem["evidence"]),
            contradiction_count=0,
            source_diversity=0,
        )

    conf = mem["confidence"]
    if conf is None or conf < cfg.min_confidence:
        return PromotionDecision(
            eligible=False,
            reason=f"Confiança insuficiente ({conf} < {cfg.min_confidence}).",
            confidence=conf,
            evidence_count=len(mem["evidence"]),
            contradiction_count=0,
            source_diversity=0,
        )

    evidences = mem["evidence"]
    supporting = [e for e in evidences if e["relationship"] == "supports"]
    contradicting = [e for e in evidences if e["relationship"] == "contradicts"]

    if not cfg.allow_contradictions and len(contradicting) > 0:
        return PromotionDecision(
            eligible=False,
            reason=(
                f"Candidato possui {len(contradicting)} evidência(s) de contradição."
            ),
            confidence=conf,
            evidence_count=len(supporting),
            contradiction_count=len(contradicting),
            source_diversity=0,
        )

    if len(supporting) < cfg.min_evidence_count:
        return PromotionDecision(
            eligible=False,
            reason=(
                f"Contagem de evidências insuficiente "
                f"({len(supporting)} < {cfg.min_evidence_count})."
            ),
            confidence=conf,
            evidence_count=len(supporting),
            contradiction_count=len(contradicting),
            source_diversity=0,
        )

    distinct_sources = {e["source_type"] for e in supporting}
    if len(distinct_sources) < cfg.min_source_diversity:
        return PromotionDecision(
            eligible=False,
            reason=(
                f"Diversidade de fontes insuficiente "
                f"({len(distinct_sources)} < {cfg.min_source_diversity})."
            ),
            confidence=conf,
            evidence_count=len(supporting),
            contradiction_count=len(contradicting),
            source_diversity=len(distinct_sources),
        )

    return PromotionDecision(
        eligible=True,
        reason="Critérios do gate determinístico atendidos integralmente.",
        confidence=conf,
        evidence_count=len(supporting),
        contradiction_count=len(contradicting),
        source_diversity=len(distinct_sources),
    )


def promote_candidate(
    conn: sqlite3.Connection,
    memory_id: int,
    config: PromotionGateConfig | None = None,
) -> PromotionDecision:
    """Aplica o gate e, se elegível, promove o candidato para 'active' com auditoria."""
    decision = evaluate_promotion(conn, memory_id, config)
    if not decision.eligible:
        return decision

    mem = persistence.get_memory_with_evidence(conn, memory_id)
    assert mem is not None

    persistence.update_memory_status(conn, memory_id, status="active")

    persistence.record_event(
        conn,
        user_id=mem["user_id"],
        event_type="MEMORY_PROMOTED",
        payload={
            "memory_id": memory_id,
            "statement": mem["statement"],
            "confidence": mem["confidence"],
            "evidence_count": decision.evidence_count,
            "reason": decision.reason,
        },
        source_type="AGENT_DERIVED",
        source_id=str(memory_id),
    )
    return decision


def record_explicit_preference(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    statement: str,
    memory_type: str = "semantic",
    importance: int = 1,
) -> int:
    """Registra uma preferência dita diretamente pelo usuário (USER_EXPLICIT).

    Não passa por gate de repetição (TODO.md §7), mas preserva proveniência,
    registra o evento de auditoria e cria a evidência de suporte inicial.
    """
    event_id = persistence.record_event(
        conn,
        user_id=user_id,
        event_type="USER_PREFERENCE",
        payload={"statement": statement, "memory_type": memory_type},
        source_type="USER_EXPLICIT",
    )

    mem_id = persistence.record_memory(
        conn,
        user_id=user_id,
        memory_type=memory_type,
        statement=statement,
        status="active",
        confidence=1.0,
        importance=importance,
        source_origin="USER_EXPLICIT",
    )

    persistence.link_memory_evidence(
        conn,
        memory_id=mem_id,
        event_id=event_id,
        weight=1.0,
        relationship="supports",
    )
    return mem_id


def supersede_preference(
    conn: sqlite3.Connection,
    *,
    old_memory_id: int,
    new_statement: str,
    reason: str | None = None,
    source_origin: str = "USER_EXPLICIT",
) -> int:
    """Substitui uma preferência ou memória ativa mantendo trilha de auditoria."""
    old_mem = persistence.get_memory_with_evidence(conn, old_memory_id)
    if old_mem is None:
        raise ValueError(f"Memória {old_memory_id} inexistente.")

    conf = 1.0 if source_origin == "USER_EXPLICIT" else old_mem["confidence"]
    new_mem_id = persistence.supersede_memory(
        conn,
        old_memory_id=old_memory_id,
        statement=new_statement,
        confidence=conf,
        importance=old_mem["importance"],
        source_origin=source_origin,
    )

    audit_event_id = persistence.record_event(
        conn,
        user_id=old_mem["user_id"],
        event_type="MEMORY_SUPERSEDED",
        payload={
            "old_memory_id": old_memory_id,
            "new_memory_id": new_mem_id,
            "old_statement": old_mem["statement"],
            "new_statement": new_statement,
            "reason": reason,
        },
        source_type=source_origin,
        source_id=str(new_mem_id),
    )

    persistence.link_memory_evidence(
        conn,
        memory_id=new_mem_id,
        event_id=audit_event_id,
        weight=1.0,
        relationship="supports",
    )
    return new_mem_id
