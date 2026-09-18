# Plan 001: Estabelecer baseline de DX, linters (ruff, mypy), AGENTS.md e gitignore

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 4d86a8c..HEAD -- pyproject.toml .gitignore AGENTS.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `4d86a8c`, 2026-09-18

## Why this matters

Subagentes executores precisam de comandos determinísticos de verificação (build, lint, typecheck, teste) e de um documento canônico `AGENTS.md` que estabeleça as regras do repositório, convenções de código e princípios de arquitetura. Atualmente, o repositório possui dependência apenas de `pytest>=8`, sem linter nem checador de tipos configurados no `pyproject.toml`, e os caches locais `.ruff_cache` não estão no `.gitignore`. Estabelecer esse baseline blinda todos os planos subsequentes contra regressões de sintaxe e estilo.

## Current state

- `pyproject.toml` (linhas 11-18):
```toml
[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```
- `.gitignore`: possui ignores para `.pytest_cache/`, mas não contém `.ruff_cache/` nem `.mypy_cache/`.
- `AGENTS.md`: inexistente na raiz do repositório.
- Python runtime: Python >= 3.13 (o ambiente local possui Python 3.14.7).

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| Install dev deps | `.venv/bin/pip install -e ".[dev]"` | exit 0 |
| Tests     | `.venv/bin/pytest`       | exit 0 (4 passed)   |
| Lint      | `.venv/bin/ruff check .` | exit 0              |
| Format    | `.venv/bin/ruff format --check .` | exit 0     |
| Typecheck | `.venv/bin/mypy src tests` | exit 0            |

## Scope

**In scope** (the only files you should modify or create):
- `AGENTS.md` (criar)
- `pyproject.toml` (modificar)
- `.gitignore` (modificar)

**Out of scope** (do NOT touch):
- `src/quercus/persistence.py`
- `tests/test_persistence.py`
- `README.md`, `TODO.md`, `docs/*`

## Git workflow

- Branch: `advisor/001-dx-tooling-agents-baseline`
- Commit message style: `dx: add AGENTS.md, ruff and mypy configurations`
- Do NOT push or open a PR unless instructed by the operator.

## Steps

### Step 1: Atualizar .gitignore

Adicionar `.ruff_cache/` e `.mypy_cache/` na seção `# Test / build` do `.gitignore`.

**Verify**: `git check-ignore -v .ruff_cache` → output indica linha correspondente no `.gitignore` e exit 0.

### Step 2: Adicionar dependências dev e configurações no pyproject.toml

1. Em `[project.optional-dependencies]`, atualizar `dev`:
```toml
dev = [
    "pytest>=8",
    "ruff>=0.9",
    "mypy>=1.14",
]
```
2. Adicionar as tabelas de configuração do Ruff e Mypy ao final de `pyproject.toml`:
```toml
[tool.ruff]
target-version = "py313"
line-length = 88
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.13"
strict = true
warn_return_any = true
warn_unused_configs = true
files = ["src", "tests"]
```
3. Instalar as novas dependências dev no virtualenv:
`.venv/bin/pip install -e ".[dev]"`

**Verify**:
- `.venv/bin/ruff --version` → exibe versão do ruff e exit 0.
- `.venv/bin/mypy --version` → exibe versão do mypy e exit 0.

### Step 3: Criar AGENTS.md na raiz do repositório

Criar `AGENTS.md` contendo:
- Visão geral do projeto (Quercus: agente pessoal para preparação do CACD).
- Filosofia de código: stdlib-first, sem ORM pesado, SQLite local, tipagem estrita (`mypy --strict`).
- Comandos obrigatórios de verificação:
  - Testes: `.venv/bin/pytest`
  - Lint: `.venv/bin/ruff check .`
  - Formatação: `.venv/bin/ruff format --check .`
  - Tipagem: `.venv/bin/mypy src tests`
- Regras de ouro:
  - Nunca commitar chaves ou segredos.
  - Toda data/hora registrada deve ser normalizada em UTC ISO-8601.
  - SQLite deve operar sempre com WAL e `busy_timeout`.

**Verify**: Arquivo `AGENTS.md` existe e `test -f AGENTS.md` retorna exit 0.

### Step 4: Executar suíte de verificação

Executar:
1. `.venv/bin/ruff check .`
2. `.venv/bin/ruff format --check .`
3. `.venv/bin/mypy src`
4. `.venv/bin/pytest`

*(Se houver avisos de tipagem estrita ou imports em arquivos existentes que não violem a lógica, ajuste apenas configurações do mypy no `pyproject.toml` ou anotações mínimas necessárias).*

**Verify**: Todos os 4 comandos saem com código 0.

## Test plan

- Teste de configuração:
  - `git check-ignore -v .ruff_cache`
  - `.venv/bin/ruff check .`
  - `.venv/bin/mypy src`
  - `.venv/bin/pytest`
- Todos devem sair com exit code 0.

## Done criteria

- [ ] `.gitignore` contém `.ruff_cache/` e `.mypy_cache/`.
- [ ] `pyproject.toml` inclui `ruff` e `mypy` em `[project.optional-dependencies].dev`.
- [ ] `AGENTS.md` criado e detalhando instruções para agentes.
- [ ] `.venv/bin/ruff check .` sai com código 0.
- [ ] `.venv/bin/mypy src` sai com código 0.
- [ ] `.venv/bin/pytest` executa e passa 100% dos testes existentes.
- [ ] Nenhum arquivo fora do escopo foi alterado (`git status`).
- [ ] Linha do plano 001 atualizada para `DONE` em `plans/README.md`.

## STOP conditions

- Se a instalação de `ruff` ou `mypy` falhar devido a incompatibilidade com o Python 3.14 local.
- Se `pyproject.toml` tiver alterações fora de `[project.optional-dependencies]` e configurações de ferramentas.

## Maintenance notes

- Versão alvo configurada para `py313` para paridade com o `requires-python = ">=3.13"` do pacote.
