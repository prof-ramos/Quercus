"""Montador de contexto do agente, frozen snapshot e barreiras de segurança.

Implementa:
- Montagem do system prompt dinâmico integrando IDENTITY.md e VOICE.md.
- Exclusão estrita de docs/ORIGIN.md no prompt de turno.
- Padrão FrozenSnapshot para estabilidade de contexto e prefix caching do LLM.
- Sanitizador de segredos (API keys, senhas, tokens).
- Barreira contra contaminação de memória (memory poisoning) por fontes externas.
"""

import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from quercus import persistence

# Padrões de detecção e redação de credenciais
SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b(api[_-]?key|secret|password|passwd|auth_token|access_token|bearer)\b\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{8,})['\"]?"
    ),
    re.compile(r"\b(sk-[A-Za-z0-9]{20,})\b"),
    re.compile(r"\b(\d{8,10}:[A-Za-z0-9_-]{35})\b"),
    re.compile(r"\b(eyJ[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,})\b"),
]

# Padrões suspeitos de injeção em fontes não-confiáveis (memory poisoning)
POISONING_PATTERNS = [
    re.compile(
        r"(?i)\b(ignore|esque[çc]a)\b.*\b(instru[çc][õo]es|regras|diretrizes)\b"
    ),
    re.compile(r"(?i)\b(voc[êe]\s+agora\s+é|you\s+are\s+now)\b"),
    re.compile(r"(?i)\b(o\s+aluno\s+(prefere|passou\s+a|decidiu|agora))\b"),
    re.compile(r"(?i)\b(aluno\s+n[ãa]o\s+quer\s+mais)\b"),
    re.compile(r"(?i)\b(memory_override|system_prompt_override)\b"),
]


def sanitize_secrets(text: str) -> str:
    """Substitui credenciais e chaves de API expostas por marcadores de redação."""
    sanitized = text
    # Padrões chave-valor
    sanitized = SECRET_PATTERNS[0].sub(r"\1=[REDACTED_SECRET]", sanitized)
    # Padrão OpenAI sk-
    sanitized = SECRET_PATTERNS[1].sub("[REDACTED_API_KEY]", sanitized)
    # Padrão Telegram bot token
    sanitized = SECRET_PATTERNS[2].sub("[REDACTED_TELEGRAM_TOKEN]", sanitized)
    # Padrão JWT
    sanitized = SECRET_PATTERNS[3].sub("[REDACTED_JWT]", sanitized)
    return sanitized


def check_memory_poisoning(text: str, source_type: str) -> bool:
    """Verifica se dados de fontes externas tentam manipular o perfil pessoal do aluno.

    Fontes não confiáveis (DOCUMENT_UNTRUSTED, TOOL_RESULT) não podem conter
    tentativas de override de instruções nem declarações de perfil do aluno.
    """
    if source_type not in {"DOCUMENT_UNTRUSTED", "TOOL_RESULT"}:
        return False

    for pat in POISONING_PATTERNS:
        if pat.search(text):
            return True
    return False


@dataclass(frozen=True)
class OperationalState:
    """Estado operacional volátil do aluno (não é memória consolidada)."""

    target_exam: str = "CACD"
    current_cycle: str = "Ciclo Base"
    weekly_goal_hours: float = 25.0
    vocative: str = "gafanhoto"
    scripture_enabled: bool = False


@dataclass(frozen=True)
class ActiveMemoryItem:
    """Item imutável de memória ativa para o snapshot do turno."""

    id: int
    memory_type: str
    statement: str
    confidence: float | None
    source_origin: str


@dataclass(frozen=True)
class FrozenSnapshot:
    """Snapshot congelado de memórias e estado estático no início do turno."""

    snapshot_id: str
    user_id: str
    created_at: str
    active_memories: tuple[ActiveMemoryItem, ...]
    operational_state: OperationalState
    static_prefix: str


class ContextAssembler:
    """Montador de prompts dinâmicos com frozen snapshot e garantias de segurança."""

    def __init__(self, docs_dir: Path | None = None) -> None:
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        self.docs_dir = docs_dir or (repo_root / "docs")
        self._identity_text: str = ""
        self._voice_text: str = ""
        self._load_core_docs()

    def _load_core_docs(self) -> None:
        """Carrega IDENTITY.md e VOICE.md (ORIGIN.md nunca entra no prompt)."""
        identity_path = self.docs_dir / "IDENTITY.md"
        voice_path = self.docs_dir / "VOICE.md"
        origin_path = self.docs_dir / "ORIGIN.md"

        if identity_path.exists():
            self._identity_text = identity_path.read_text(encoding="utf-8").strip()
        else:
            self._identity_text = (
                "Quercus — Agente pessoal de preparação para concursos."
            )

        if voice_path.exists():
            self._voice_text = voice_path.read_text(encoding="utf-8").strip()
        else:
            self._voice_text = (
                "Voz: Chão (trabalho, ritmo, sem floreio). Empurrão raro."
            )

        # Invariante de Segurança: ORIGIN.md nunca pode estar no corpo carregado
        if origin_path.exists():
            origin_content = origin_path.read_text(encoding="utf-8")
            assert origin_content not in self._identity_text
            assert origin_content not in self._voice_text

    def create_snapshot(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        operational_state: OperationalState | None = None,
    ) -> FrozenSnapshot:
        """Captura o snapshot congelado das memórias ativas no início do turno."""
        op_state = operational_state or OperationalState()

        # Busca apenas memórias ativas consolidadas
        active_rows = persistence.list_memories(
            conn, user_id=user_id, status="active", limit=100
        )
        items: list[ActiveMemoryItem] = []
        for r in active_rows:
            items.append(
                ActiveMemoryItem(
                    id=r["id"],
                    memory_type=r["memory_type"],
                    statement=sanitize_secrets(r["statement"]),
                    confidence=r["confidence"],
                    source_origin=r["source_origin"],
                )
            )

        # Monta prefixo estático (IDENTITY + VOICE)
        scripture_rule = (
            "- Registro Escritura: HABILITADO sob demanda (citação breve)."
            if op_state.scripture_enabled
            else "- Registro Escritura: DESABILITADO (usar Chão e Empurrão)."
        )

        static_prefix = (
            f"=== IDENTIDADE DO AGENTE ===\n"
            f"{self._identity_text}\n\n"
            f"=== REGISTRO DE VOZ E CONDUTA ===\n"
            f"{self._voice_text}\n\n"
            f"=== CONFIGURAÇÃO DO ALUNO ===\n"
            f"- Vocativo canônico: {op_state.vocative}\n"
            f"- Prova alvo: {op_state.target_exam}\n"
            f"- Ciclo operacional: {op_state.current_cycle}\n"
            f"- Meta semanal: {op_state.weekly_goal_hours:.1f} horas\n"
            f"{scripture_rule}"
        )

        return FrozenSnapshot(
            snapshot_id=str(uuid.uuid4()),
            user_id=user_id,
            created_at=persistence._normalize_iso_utc(),
            active_memories=tuple(items),
            operational_state=op_state,
            static_prefix=static_prefix,
        )

    def assemble_system_prompt(
        self,
        snapshot: FrozenSnapshot,
        *,
        today_summary: str = "",
        recent_adherence: str = "",
    ) -> str:
        """Monta o system prompt final a partir do snapshot congelado."""
        memories_section = "=== MEMÓRIAS ATIVAS CONSOLIDADAS ===\n"
        if snapshot.active_memories:
            for m in snapshot.active_memories:
                conf_str = f" [conf: {m.confidence:.2f}]" if m.confidence else ""
                stmt = m.statement
                memories_section += f"- [{m.memory_type.upper()}]{conf_str} {stmt}\n"
        else:
            memories_section += "(Nenhuma memória ativa consolidada no momento.)\n"

        context_section = "=== CONTEXTO OPERACIONAL DO DIA ===\n"
        if today_summary:
            clean_summary = sanitize_secrets(today_summary)
            context_section += f"Sessões de hoje:\n{clean_summary}\n"
        if recent_adherence:
            clean_adh = sanitize_secrets(recent_adherence)
            context_section += f"Aderência recente:\n{clean_adh}\n"

        prompt = (
            f"{snapshot.static_prefix}\n\n"
            f"{memories_section}\n"
            f"{context_section.strip()}\n"
        )
        return prompt.strip()
