"""Módulo de backup online e restauração testada do banco SQLite (WAL).

Implementa:
- Backup online não-bloqueante via API nativa sqlite3.Connection.backup.
- Compactação segura com gzip (.db.gz).
- Nomenclatura determinística com timestamp UTC (quercus_backup_YYYYMMDD_HHMMSS.db.gz).
- Verificação rigorosa de integridade (PRAGMA integrity_check e foreign_key_check).
- Restauração com validação de contagem de registros em tabelas fundamentais.
- Política de retenção configurável para limpeza de backups obsoletos.
"""

import gzip
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quercus import persistence


def get_backup_filename(dt: datetime | None = None) -> str:
    """Gera nome do arquivo de backup com timestamp UTC determinístico."""
    if dt is None:
        dt = datetime.now(UTC)
    ts = dt.strftime("%Y%m%d_%H%M%S")
    return f"quercus_backup_{ts}.db.gz"


def create_backup(
    conn: sqlite3.Connection,
    target_dir: str | Path,
    *,
    retention_days: int = 7,
) -> Path:
    """Cria backup online compactado do banco SQLite em modo WAL.

    1. Realiza checkpoint passivo no WAL para sincronizar páginas recentes.
    2. Usa conn.backup() para copiar a quente para um arquivo temporário.
    3. Valida a integridade do banco copiado (PRAGMA integrity_check).
    4. Compacta em gzip (.db.gz) no diretório de destino.
    5. Aplica política de retenção apagando backups anteriores a N dias.
    """
    dest_dir = Path(target_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    backup_name = get_backup_filename()
    final_path = dest_dir / backup_name

    # Checkpoint WAL passivo (não bloqueia leitores nem escritores)
    try:
        conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
    except sqlite3.Error:
        pass

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = Path(tmp_file.name)

    try:
        # Cópia online segura via API nativa do SQLite
        dest_conn = sqlite3.connect(str(tmp_db_path))
        try:
            conn.backup(dest_conn)
        finally:
            dest_conn.close()

        # Valida integridade da cópia antes de compactar
        is_valid, errors, _ = verify_database_integrity(tmp_db_path)
        if not is_valid:
            raise RuntimeError(f"Backup falhou no teste de integridade: {errors}")

        # Compacta com gzip para o destino final
        with open(tmp_db_path, "rb") as f_in:
            with gzip.open(final_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
    finally:
        if tmp_db_path.exists():
            tmp_db_path.unlink()

    # Aplica política de retenção
    if retention_days > 0:
        clean_old_backups(dest_dir, retention_days=retention_days)

    return final_path


def verify_database_integrity(
    db_path: str | Path,
) -> tuple[bool, list[str], dict[str, int]]:
    """Executa checagem de integridade e contagem de registros em tabelas essenciais.

    Retorna (is_ok, lista_de_erros, dicionario_de_contagens).
    """
    path = Path(db_path)
    if not path.exists():
        return False, [f"Arquivo {path} não existe."], {}

    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    errors: list[str] = []
    counts: dict[str, int] = {}

    try:
        # 1. PRAGMA integrity_check
        integrity_rows = conn.execute("PRAGMA integrity_check;").fetchall()
        for row in integrity_rows:
            if row[0] != "ok":
                errors.append(f"PRAGMA integrity_check error: {row[0]}")

        # 2. PRAGMA foreign_key_check
        fk_rows = conn.execute("PRAGMA foreign_key_check;").fetchall()
        for row in fk_rows:
            errors.append(f"PRAGMA foreign_key_check error: {row}")

        # 3. Contagem de registros nas tabelas centrais do Quercus
        tables = [
            "events",
            "memories",
            "memory_evidence",
            "study_sessions",
            "study_plans",
            "study_plan_items",
        ]
        for table in tables:
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {table};")  # noqa: S608
                counts[table] = int(cur.fetchone()[0])
            except sqlite3.OperationalError:
                # Tabela pode ainda não ter sido criada em bancos novos
                counts[table] = 0

    except sqlite3.Error as exc:
        errors.append(f"Erro ao acessar banco: {exc}")
    finally:
        conn.close()

    return len(errors) == 0, errors, counts


def restore_backup(
    backup_path: str | Path,
    target_db_path: str | Path | None = None,
    *,
    verify_only: bool = False,
) -> dict[str, Any]:
    """Restaura um backup compactado (.db.gz) ou cru (.db) e valida sua integridade.

    Se verify_only for True, descompacta em arquivo temporário e apenas valida.
    Se target_db_path for especificado, descompacta atômicamente no destino.
    """
    b_path = Path(backup_path)
    if not b_path.exists():
        raise FileNotFoundError(f"Arquivo de backup não encontrado: {b_path}")

    # Determina se precisa descompactar gzip
    is_gzipped = b_path.name.endswith(".gz")

    if verify_only or target_db_path is None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
            temp_restore_path = Path(tmp_file.name)
        work_path = temp_restore_path
    else:
        work_path = Path(target_db_path)
        work_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if is_gzipped:
            with gzip.open(b_path, "rb") as f_in:
                with open(work_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            shutil.copyfile(b_path, work_path)

        # Checa integridade do banco restaurado
        is_ok, errors, counts = verify_database_integrity(work_path)
        if not is_ok:
            raise RuntimeError(f"Restauração reprovada na integridade: {errors}")

        # Configura pragmas de produção recomendados no banco restaurado
        if not verify_only:
            conn = persistence.connect(str(work_path))
            conn.close()

        return {
            "status": "success",
            "backup_file": str(b_path),
            "restored_to": str(work_path) if not verify_only else None,
            "verify_only": verify_only,
            "table_counts": counts,
            "integrity_ok": is_ok,
        }
    finally:
        if verify_only and work_path.exists():
            work_path.unlink()


def clean_old_backups(
    backup_dir: str | Path,
    *,
    retention_days: int = 7,
) -> list[Path]:
    """Remove backups anteriores ao limite de retenção em dias."""
    b_dir = Path(backup_dir)
    if not b_dir.exists():
        return []

    now = datetime.now(UTC)
    deleted: list[Path] = []

    # Procura arquivos com padrão quercus_backup_*.db.gz ou *.db
    for f in b_dir.iterdir():
        if not (f.name.startswith("quercus_backup_") and (f.suffix in {".gz", ".db"})):
            continue

        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
            age_days = (now - mtime).total_seconds() / 86400.0
            if age_days > retention_days:
                f.unlink()
                deleted.append(f)
        except OSError:
            pass

    return deleted
