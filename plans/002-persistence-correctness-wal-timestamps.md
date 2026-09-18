# Plan 002: Corrigir normalização UTC de timestamps, concorrência WAL e robustez de serialização

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
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/001-dx-tooling-agents-baseline.md
- **Category**: bug
- **Planned at**: commit `4d86a8c`, 2026-09-18

## Why this matters

No SQLite, colunas `TEXT` são comparadas alfabeticamente. Atualmente, `record_event()` aceita strings de timestamp arbitrárias. Se um timestamp for fornecido com fuso horário local brasileiro (`-03:00`) e outro com UTC (`+00:00`), a ordenação `ORDER BY timestamp DESC` falha alfabeticamente, invertendo a ordem cronológica real dos fatos do aluno. Além disso, a conexão não ativa o modo `WAL` nem `busy_timeout`, o que causará erros de lock quando o Telegram e tarefas em segundo plano (consolidação/cron) acessarem o banco simultaneamente. Por fim, tipos de domínio como `datetime` ou `UUID` passados no payload causam crash silencioso por falta de serializer de fallback, e a proveniência (`source_type`) aceita qualquer string, violando a integridade do modelo de auditoria de dados.

## Current state

- `src/quercus/persistence.py` (linhas 24-34):
```python
def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: str) -> sqlite3.Connection:
    """Abre conexão e garante o schema."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
```
- `src/quercus/persistence.py` (linhas 36-65):
```python
def record_event(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    event_type: str,
    payload: dict,
    source_type: str = "SYSTEM_OBSERVED",
    source_id: str | None = None,
    timestamp: str | None = None,
) -> int:
    """Registra um evento. Retorna o id."""
    cur = conn.execute(
        """
        INSERT INTO events
            (user_id, event_type, timestamp, source_type, source_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            event_type,
            timestamp or _now(),
            source_type,
            source_id,
            json.dumps(payload, ensure_ascii=False),
            _now(),
        ),
    )
    conn.commit()
    return cur.lastrowid
```
- `src/quercus/persistence.py` (linhas 67-84):
```python
def list_events(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """Lê eventos do usuário mais recentes primeiro."""
    return conn.execute(
        """
        SELECT id, user_id, event_type, timestamp, source_type, source_id,
               payload_json, created_at
        FROM events
        WHERE user_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
```

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| Tests     | `.venv/bin/pytest`       | exit 0              |
| Lint      | `.venv/bin/ruff check .` | exit 0              |
| Typecheck | `.venv/bin/mypy src tests` | exit 0            |

## Scope

**In scope** (the only files you should modify):
- `src/quercus/persistence.py`
- `tests/test_persistence.py`

**Out of scope** (do NOT touch):
- `pyproject.toml`, `AGENTS.md`, `.gitignore`
- Criação de novas tabelas (`memories`, `study_sessions`) — reservado para o plano 003.

## Git workflow

- Branch: `advisor/002-persistence-correctness-wal-timestamps`
- Commit message style: `fix(persistence): normalize UTC timestamps, enable WAL, and validate provenance`
- Do NOT push or open a PR unless instructed by the operator.

## Steps

### Step 1: Adicionar normalizador canônico de data/hora UTC e validação de proveniência em `src/quercus/persistence.py`

1. Definir o conjunto de origens de proveniência válidas (conforme `TODO.md §2.4`):
```python
VALID_SOURCE_TYPES: frozenset[str] = frozenset({
    "USER_EXPLICIT",
    "USER_OBSERVED",
    "SYSTEM_OBSERVED",
    "AGENT_DERIVED",
    "DOCUMENT_TRUSTED",
    "DOCUMENT_UNTRUSTED",
    "TOOL_RESULT",
})
```
2. Implementar a função de normalização:
```python
def _normalize_iso_utc(ts: str | datetime | None = None) -> str:
    """Retorna timestamp ISO-8601 em UTC rigoroso com microssegundos.
    
    Exemplo de saída: '2026-09-18T20:30:00.000000+00:00'.
    Garante ordenação léxica idêntica à ordem cronológica no SQLite TEXT.
    """
    if ts is None:
        dt = datetime.now(UTC)
    elif isinstance(ts, datetime):
        dt = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
    elif isinstance(ts, str):
        # Trata formato ISO ou Z
        clean = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    else:
        raise TypeError(f"Timestamp inválido: {type(ts)}")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
```
3. Substituir `_now()` para reutilizar `_normalize_iso_utc()`.

**Verify**: `.venv/bin/pytest tests/test_persistence.py` continua passando nos testes existentes.

### Step 2: Habilitar modo WAL e `busy_timeout` em `connect()`

Em `connect(path: str) -> sqlite3.Connection`:
Executar os pragmas logo após abrir a conexão:
```python
def connect(path: str) -> sqlite3.Connection:
    """Abre conexão, ativa WAL/busy_timeout e garante o schema."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.executescript(SCHEMA)
    return conn
```

**Verify**: Inspecionar que `conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000`.

### Step 3: Blindar `record_event()` com validações e serialização resiliente

1. Validar `source_type`:
```python
if source_type not in VALID_SOURCE_TYPES:
    raise ValueError(
        f"source_type '{source_type}' inválido. Origens permitidas: {sorted(VALID_SOURCE_TYPES)}"
    )
```
2. Normalizar o timestamp:
```python
norm_timestamp = _normalize_iso_utc(timestamp)
created_at = _normalize_iso_utc()
```
3. Serializar `payload` com fallback `default=str` para evitar falhas com `UUID`, `date`, etc.:
```python
payload_str = json.dumps(payload, ensure_ascii=False, default=str)
```
4. Garantir tipagem de retorno e assert de `cur.lastrowid`:
```python
assert cur.lastrowid is not None
return cur.lastrowid
```

**Verify**: `.venv/bin/pytest tests/test_persistence.py` executa e passa.

### Step 4: Expandir suíte de testes em `tests/test_persistence.py`

Adicionar testes para:
1. `test_wal_mode_and_busy_timeout(conn)`: verifica se `PRAGMA busy_timeout` está em 5000 e `journal_mode` está configurado.
2. `test_invalid_source_type_raises_value_error(conn)`: testa `source_type="INVALID"` levantando `ValueError`.
3. `test_timestamp_lexical_order_across_different_offsets(conn)`:
   - Inserir evento A às `18:00:00-03:00` (21:00 UTC).
   - Inserir evento B às `20:00:00+00:00` (20:00 UTC).
   - Inserir evento C com `"Z"` às `22:00:00Z` (22:00 UTC).
   - Verificar que `list_events` retorna na ordem correta: C (22:00 UTC), A (21:00 UTC), B (20:00 UTC).
4. `test_payload_with_datetime_uuid_and_unicode(conn)`:
   - Inserir payload com caracteres em português ("Atenção, Segundo Reinado"), objeto `datetime` e `UUID`.
   - Garantir que salva sem erro e deserializa com sucesso.
5. `test_list_events_limit_and_empty_user(conn)`:
   - Testar que usuário sem eventos retorna lista vazia `[]`.
   - Testar que `limit=2` retorna exatamente 2 eventos mais recentes.

**Verify**:
- `.venv/bin/pytest -v` → todos os novos testes passam.
- `.venv/bin/ruff check .` → exit 0.
- `.venv/bin/mypy src tests` → exit 0.

## Test plan

- Testes de regressão:
  - 4 testes originais continuam passando.
- Novos testes:
  - Ordenação inter-fusos horários (evita bug de string sort no SQLite).
  - Robustez de serialização (`datetime`, `UUID`, Unicode PT-BR).
  - Validação estrita de `source_type`.
  - Configuração de WAL e timeout.
- Comando de verificação: `.venv/bin/pytest -v`

## Done criteria

- [ ] `_normalize_iso_utc` implementada e cobrindo strings com timezone, `Z`, datetimes nativos e None.
- [ ] `connect()` configura `PRAGMA journal_mode = WAL;` e `PRAGMA busy_timeout = 5000;`.
- [ ] `source_type` é validado contra `VALID_SOURCE_TYPES` com erro explicativo em caso de valor inválido.
- [ ] `record_event` serializa tipos especiais de dados sem crashar.
- [ ] Todos os novos testes adicionados em `tests/test_persistence.py` passam.
- [ ] `.venv/bin/ruff check .` sai com código 0.
- [ ] `.venv/bin/mypy src tests` sai com código 0.
- [ ] Linha do plano 002 atualizada para `DONE` em `plans/README.md`.

## STOP conditions

- Se a alteração exigir mudança na tabela `events` incompatível com o schema existente (a coluna `timestamp` continua sendo `TEXT NOT NULL`).
- Se houver falha de compatibilidade com SQLite em memória nos testes (nota: SQLite in-memory com `:memory:` pode responder `memory` ao PRAGMA journal_mode, trate isso na asserção do teste usando `conn` em arquivo ou conferindo `WAL` se em disco).

## Maintenance notes

- A normalização UTC canônica padroniza microssegundos (`%f`), o que garante ordenação de alta fidelidade para eventos disparados no mesmo segundo.
