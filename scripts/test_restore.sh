#!/usr/bin/env bash
# Teste automatizado de restauração e integridade de backup do Quercus
# Acceptance Criteria Issue #11: PRAGMA integrity_check + contagem de registros

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH:-}"

PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="python3"
fi

TEMP_DIR=$(mktemp -d "/tmp/quercus_restore_test_XXXXXX")
trap 'rm -rf "${TEMP_DIR}"' EXIT

DB_PATH="${TEMP_DIR}/quercus_origin.db"
BACKUP_DIR="${TEMP_DIR}/backups"
RESTORED_DB="${TEMP_DIR}/quercus_restored.db"

echo "=========================================================="
echo " [QUERCUS] Teste Automatizado de Backup e Restauração"
echo "=========================================================="
echo "[1/4] Inicializando banco de teste e inserindo registros..."

"${PYTHON_BIN}" - <<EOF
from quercus import persistence, memory

conn = persistence.connect("${DB_PATH}")

# 1. Registra eventos
eid1 = persistence.record_event(conn, user_id="gabriel", event_type="SESSION_START", source_type="USER_OBSERVED", source_id="s-1", payload={"test": True})
eid2 = persistence.record_event(conn, user_id="gabriel", event_type="STUDY_COMPLETED", source_type="USER_OBSERVED", source_id="s-1", payload={"minutes": 50})

# 2. Registra memória com evidência
mid = memory.record_explicit_preference(conn, user_id="gabriel", statement="Prefere estudar sem notificações")

# 3. Registra sessão de estudo
sid = persistence.record_study_session(conn, user_id="gabriel", subject="História", planned_minutes=50, actual_minutes=50, status="completed")

# 4. Registra plano de estudos
pid = persistence.record_study_plan(conn, user_id="gabriel", plan_date="2026-09-19", title="Plano de Teste")
persistence.add_study_plan_item(conn, plan_id=pid, subject="História", duration_minutes=50)

conn.close()
print(" -> Banco de teste populado com sucesso.")
EOF

echo "[2/4] Executando backup online compactado..."
"${PYTHON_BIN}" "${SCRIPT_DIR}/backup_db.py" --db-path "${DB_PATH}" --backup-dir "${BACKUP_DIR}" --retention-days 7

LATEST_BACKUP=$(ls -t "${BACKUP_DIR}"/quercus_backup_*.db.gz | head -n 1)
echo " -> Arquivo gerado: ${LATEST_BACKUP}"

echo "[3/4] Testando validação de integridade em modo verify-only..."
"${PYTHON_BIN}" "${SCRIPT_DIR}/restore_db.py" --backup-file "${LATEST_BACKUP}" --verify-only

echo "[4/4] Restaurando fisicamente para novo arquivo e conferindo dados..."
"${PYTHON_BIN}" "${SCRIPT_DIR}/restore_db.py" --backup-file "${LATEST_BACKUP}" --target-db "${RESTORED_DB}"

"${PYTHON_BIN}" - <<EOF
import sqlite3

conn = sqlite3.connect("${RESTORED_DB}")
integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
assert integrity == "ok", f"Integridade inválida: {integrity}"

events_count = conn.execute("SELECT COUNT(*) FROM events;").fetchone()[0]
assert events_count >= 2, f"Esperava >= 2 eventos, obteve {events_count}"

memories_count = conn.execute("SELECT COUNT(*) FROM memories;").fetchone()[0]
assert memories_count >= 1, f"Esperava >= 1 memória, obteve {memories_count}"

plans_count = conn.execute("SELECT COUNT(*) FROM study_plans;").fetchone()[0]
assert plans_count >= 1, f"Esperava >= 1 plano, obteve {plans_count}"

conn.close()
print(" -> Validação rigorosa dos dados restaurados: 100% OK!")
EOF

echo "=========================================================="
echo " [OK] TESTE DE RESTAURAÇÃO APROVADO COM SUCESSO!"
echo "=========================================================="
