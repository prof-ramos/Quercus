# Quercus — Instruções para Agentes

Agente pessoal de preparação para concursos públicos (primeiro cenário: CACD).

## Filosofia e Diretrizes

- **Abordagem**: stdlib-first, sem ORM pesado, persistência local em SQLite (`quercus.db`).
- **Ciclo único**: `observar → registrar → lembrar → consolidar → utilizar`.
- **Integridade**:
  - Toda data/hora registrada deve ser normalizada em formato ISO-8601 UTC com microssegundos.
  - O SQLite deve operar com `PRAGMA journal_mode = WAL;` e `PRAGMA busy_timeout = 5000;`.
  - Nunca commitar chaves, segredos ou tokens de API.

## Comandos do repositório

- **Testes**: `.venv/bin/pytest`
- **Lint**: `.venv/bin/ruff check .`
- **Formatação**: `.venv/bin/ruff format --check .`
- **Tipagem**: `.venv/bin/mypy src tests`

## Agent skills

### Issue tracker

GitHub Issues via `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical five-role labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`CONTEXT.md` + `docs/adr/`). See `docs/agents/domain.md`.
