# Plan 003: Implementar schema e operações de persistência para study_sessions, memories e memory_evidence

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 4d86a8c..HEAD -- src/quercus/persistence.py tests/test_persistence.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/002-persistence-correctness-wal-timestamps.md
- **Category**: tech-debt
- **Planned at**: commit `4d86a8c`, 2026-09-18

## Why this matters

A premissa central do Quercus é *"Ele aprende o concurseiro"* e a prova do ciclo *"observar → registrar → lembrar → consolidar → utilizar"*. Atualmente, apenas a tabela `events` está implementada no banco. Sem as tabelas `study_sessions`, `memories` e `memory_evidence` (especificadas no `TODO.md §4`), é impossível persistir sessões de estudo do CACD, candidatos do Dreaming, memórias consolidadas ou os vínculos probatórios necessários para o princípio de auditabilidade (*"Por que você acha isso sobre mim?"*). Este plano materializa essas três entidades relacionais e suas funções de persistência puras em Python/SQLite sem dependência de ORMs pesados.

## Current state

- `src/quercus/persistence.py`:
  - Contém apenas a tabela `events` em `SCHEMA`.
  - Contém funções: `connect()`, `record_event()`, `list_events()`.
- `TODO.md` (§4, linhas 102-148):
  - Especifica os atributos das tabelas `study_sessions`, `memories` e `memory_evidence`.
  - Define os status de sessão: `planned | completed | partial | skipped | cancelled`.
  - Define os tipos de memória: `episodic | semantic | inferential | procedural`.
  - Define os status de memória: `candidate | active | superseded | archived | rejected | revoked | expired`.
- Estilo arquitetural: stdlib pura (`sqlite3`, `json`, `datetime`), sem ORM, queries parametrizadas com `?`, retorno `sqlite3.Row` para conveniência de leitura.

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| Tests     | `.venv/bin/pytest -v`    | exit 0              |
| Lint      | `.venv/bin/ruff check .` | exit 0              |
| Typecheck | `.venv/bin/mypy src tests` | exit 0            |

## Scope

**In scope** (the only files you should modify):
- `src/quercus/persistence.py`
- `tests/test_persistence.py`

**Out of scope** (do NOT touch):
- `src/quercus/agent/*`, `src/quercus/channels/*` (camadas superiores não devem ser criadas aqui).
- `README.md`, `docs/*`, `pyproject.toml`.

## Git workflow

- Branch: `advisor/003-data-model-memories-sessions`
- Commit message style: `feat(persistence): implement study_sessions, memories and memory_evidence`
- Do NOT push or open a PR unless instructed by the operator.

## Steps

### Step 1: Expandir o DDL do SCHEMA em `src/quercus/persistence.py`

Adicionar ao `SCHEMA` a criação das tabelas `study_sessions`, `memories` e `memory_evidence`, além de garantir que `PRAGMA foreign_keys = ON;` seja executado em `connect()` para manter a integridade referencial:

```sql
CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    topic TEXT,
    planned_minutes INTEGER NOT NULL,
    actual_minutes INTEGER,
    planned_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    status TEXT NOT NULL, -- planned, completed, partial, skipped, cancelled
    source TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    memory_type TEXT NOT NULL, -- episodic, semantic, inferential, procedural
    statement TEXT NOT NULL,
    status TEXT NOT NULL, -- candidate, active, superseded, archived, rejected, revoked, expired
    confidence REAL,
    importance INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_confirmed_at TEXT,
    expires_at TEXT,
    supersedes_id INTEGER,
    source_origin TEXT NOT NULL,
    FOREIGN KEY(supersedes_id) REFERENCES memories(id)
);

CREATE TABLE IF NOT EXISTS memory_evidence (
    id INTEGER PRIMARY KEY,
    memory_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    weight REAL DEFAULT 1.0,
    relationship TEXT NOT NULL, -- supports, contradicts, illustrates
    created_at TEXT NOT NULL,
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE RESTRICT
);
```

Em `connect(path: str)`: adicionar `conn.execute("PRAGMA foreign_keys = ON;")`.

**Verify**: Conectar e verificar se as 4 tabelas existem em `sqlite_master`.

### Step 2: Implementar funções de persistência para `study_sessions`

Em `src/quercus/persistence.py`, adicionar:

1. Constante de validação de status:
```python
VALID_SESSION_STATUSES: frozenset[str] = frozenset({
    "planned", "completed", "partial", "skipped", "cancelled"
})
```

2. `record_study_session`:
```python
def record_study_session(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    subject: str,
    planned_minutes: int,
    topic: str | None = None,
    actual_minutes: int | None = None,
    planned_at: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    status: str = "planned",
    source: str = "SYSTEM_OBSERVED",
    notes: str | None = None,
) -> int:
    ...
```
(Normalizar todas as datas/horas passadas via `_normalize_iso_utc`).

3. `update_study_session`:
```python
def update_study_session(
    conn: sqlite3.Connection,
    session_id: int,
    *,
    status: str | None = None,
    actual_minutes: int | None = None,
    finished_at: str | None = None,
    notes: str | None = None,
) -> None:
    ...
```

4. `list_study_sessions`:
```python
def list_study_sessions(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    status: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    ...
```

**Verify**: `.venv/bin/pytest tests/test_persistence.py` continua passando.

### Step 3: Implementar funções de persistência para `memories` e `memory_evidence`

Em `src/quercus/persistence.py`, adicionar:

1. Constantes de validação:
```python
VALID_MEMORY_TYPES: frozenset[str] = frozenset({
    "episodic", "semantic", "inferential", "procedural"
})

VALID_MEMORY_STATUSES: frozenset[str] = frozenset({
    "candidate", "active", "superseded", "archived", "rejected", "revoked", "expired"
})

VALID_EVIDENCE_RELATIONSHIPS: frozenset[str] = frozenset({
    "supports", "contradicts", "illustrates"
})
```

2. `record_memory`:
```python
def record_memory(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    memory_type: str,
    statement: str,
    status: str = "candidate",
    confidence: float | None = None,
    importance: int = 1,
    source_origin: str = "SYSTEM_OBSERVED",
    supersedes_id: int | None = None,
) -> int:
    ...
```

3. `link_memory_evidence`:
```python
def link_memory_evidence(
    conn: sqlite3.Connection,
    *,
    memory_id: int,
    event_id: int,
    weight: float = 1.0,
    relationship: str = "supports",
) -> int:
    ...
```

4. `supersede_memory`:
Marca uma memória existente como `superseded`, cria a nova memória com status `active` apontando `supersedes_id = old_id` de forma transacional:
```python
def supersede_memory(
    conn: sqlite3.Connection,
    *,
    old_memory_id: int,
    statement: str,
    confidence: float | None = None,
    source_origin: str = "USER_EXPLICIT",
) -> int:
    ...
```

5. `list_memories`:
Lê memórias por usuário, podendo filtrar por `status` (ex.: `active` para o system prompt, ou `candidate` para o REM dreaming) e por `memory_type`.

6. `get_memory_with_evidence`:
Retorna a memória e a lista de eventos vinculados (com payload, timestamp e relationship):
```python
def get_memory_with_evidence(
    conn: sqlite3.Connection,
    memory_id: int,
) -> dict[str, Any] | None:
    ...
```
(Resolve a auditabilidade de *"Por que você acha isso sobre mim?"*).

**Verify**: `.venv/bin/pytest tests/test_persistence.py` passa sem regressões.

### Step 4: Adicionar testes de unidade e integração em `tests/test_persistence.py`

Criar novos testes cobrindo:
1. `test_record_and_update_study_session(conn)`: planeja sessão de 45 min de História do Brasil; atualiza para 38 min realizados e status "completed".
2. `test_record_memory_and_link_evidence(conn)`:
   - Cria evento de estudo.
   - Cria memória inferencial "História rende melhor pela manhã" como `candidate`.
   - Vincula a evidência do evento com relationship "supports".
   - Chama `get_memory_with_evidence()` e verifica os dados e a evidência retornada.
3. `test_supersede_memory_lifecycle(conn)`:
   - Registra memória ativa "Estuda 45 min por sessão".
   - Executa `supersede_memory()` com "Usuário agora estuda 30 min".
   - Confirma que a antiga ficou com status `superseded` e a nova ficou `active` com `supersedes_id` apontando para a antiga.
4. `test_filter_memories_by_status(conn)`:
   - Garante que buscar apenas `status="active"` não retorna `candidate` nem `superseded`.
5. `test_invalid_types_and_statuses_raise_error(conn)`:
   - Testa se status inválido levanta `ValueError`.

**Verify**:
- `.venv/bin/pytest -v` → todos os testes passam (antigos e novos).
- `.venv/bin/ruff check .` → exit 0.
- `.venv/bin/mypy src tests` → exit 0.

## Test plan

- Testes de sessões de estudo: criação, transição de status, atualização de tempo real.
- Testes de ciclo de vida de memória: criação como candidato, promoção para ativo, supersessão transacional.
- Testes do grafo de evidências: junção entre memória e eventos, provando auditabilidade.
- Validação de constraints relacionais: Foreign Key enforcement.
- Comando: `.venv/bin/pytest -v`

## Done criteria

- [ ] Tabelas `study_sessions`, `memories` e `memory_evidence` criadas no `SCHEMA`.
- [ ] `PRAGMA foreign_keys = ON;` ativo em `connect()`.
- [ ] Funções de sessão: `record_study_session`, `update_study_session`, `list_study_sessions`.
- [ ] Funções de memória: `record_memory`, `link_memory_evidence`, `supersede_memory`, `list_memories`, `get_memory_with_evidence`.
- [ ] 100% dos testes novos e legados passam em `.venv/bin/pytest -v`.
- [ ] `.venv/bin/ruff check .` sai com código 0.
- [ ] `.venv/bin/mypy src tests` sai com código 0.
- [ ] Linha do plano 003 atualizada para `DONE` em `plans/README.md`.

## STOP conditions

- Se a adição de foreign keys causar incompatibilidade com testes que inserem eventos ou memórias sem entidades pai criadas previamente.
- Se o SQLite rejeitar alterações em conexões existentes sem migração (em ambiente de teste o banco é recriado em `tmp_path`, mas a idempotência de `CREATE TABLE IF NOT EXISTS` deve ser mantida).

## Maintenance notes

- A separação de `events` (histórico bruto append-only) e `memories` (estado de crenças auditáveis com evidências) é a chave arquitetural do Quercus. Nenhum processo futuro deve gravar diretamente em `memories` sem passar pelas funções deste módulo.
