"""Testes automatizados de backup online, integridade e restauração do SQLite.

Atende aos critérios da Issue #11.
"""

import gzip
import sqlite3
from pathlib import Path

import pytest

from quercus import backup, memory, persistence


@pytest.fixture
def populated_db(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    db_path = tmp_path / "origin.db"
    conn = persistence.connect(str(db_path))

    # Popula dados de teste
    persistence.record_event(
        conn,
        user_id="gabriel",
        event_type="SESSION_START",
        source_type="USER_OBSERVED",
        source_id="sess-1",
        payload={"started": True},
    )
    memory.record_explicit_preference(
        conn,
        user_id="gabriel",
        statement="Prefere sessões matutinas curtas de 45 minutos.",
    )
    persistence.record_study_session(
        conn,
        user_id="gabriel",
        subject="Política Internacional",
        planned_minutes=45,
        actual_minutes=45,
        status="completed",
    )
    plan_id = persistence.record_study_plan(
        conn,
        user_id="gabriel",
        plan_date="2026-09-20",
        title="Plano de Fim de Semana",
    )
    persistence.add_study_plan_item(
        conn,
        plan_id=plan_id,
        subject="Política Internacional",
        duration_minutes=45,
    )
    return db_path, conn


def test_create_backup_online_wal(
    populated_db: tuple[Path, sqlite3.Connection], tmp_path: Path
) -> None:
    _, conn = populated_db
    backup_dir = tmp_path / "backups"

    backup_path = backup.create_backup(conn, backup_dir, retention_days=7)
    assert backup_path.exists()
    assert backup_path.name.endswith(".db.gz")
    assert backup_path.stat().st_size > 0


def test_restore_backup_verify_only(
    populated_db: tuple[Path, sqlite3.Connection], tmp_path: Path
) -> None:
    _, conn = populated_db
    backup_dir = tmp_path / "backups"
    backup_path = backup.create_backup(conn, backup_dir, retention_days=7)

    result = backup.restore_backup(backup_path, verify_only=True)
    assert result["status"] == "success"
    assert result["verify_only"] is True
    assert result["integrity_ok"] is True
    counts = result["table_counts"]
    assert counts["events"] >= 2
    assert counts["memories"] >= 1
    assert counts["study_sessions"] >= 1
    assert counts["study_plans"] >= 1
    assert counts["study_plan_items"] >= 1


def test_restore_backup_physical_target(
    populated_db: tuple[Path, sqlite3.Connection], tmp_path: Path
) -> None:
    _, conn = populated_db
    backup_dir = tmp_path / "backups"
    backup_path = backup.create_backup(conn, backup_dir, retention_days=7)

    target_db = tmp_path / "restored.db"
    result = backup.restore_backup(backup_path, target_db_path=target_db)
    assert result["status"] == "success"
    assert target_db.exists()

    # Valida conexão no banco restaurado
    res_conn = sqlite3.connect(str(target_db))
    rows = res_conn.execute("SELECT statement FROM memories;").fetchall()
    assert len(rows) >= 1
    assert "sessões matutinas" in rows[0][0]
    res_conn.close()


def test_restore_corrupted_backup_fails(tmp_path: Path) -> None:
    corrupted_file = tmp_path / "quercus_backup_corrupted.db.gz"
    # Cria arquivo gzip contendo lixo inválido
    with gzip.open(corrupted_file, "wb") as f:
        f.write(b"NOT_A_SQLITE_DATABASE_DATA_GARBAGE")

    with pytest.raises(RuntimeError, match="integridade|não é um banco"):
        backup.restore_backup(corrupted_file, verify_only=True)


def test_clean_old_backups_retention(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Cria arquivo de backup simulando data antiga
    old_file = backup_dir / "quercus_backup_20200101_000000.db.gz"
    with gzip.open(old_file, "wb") as f:
        f.write(b"data")

    # Modifica mtime para 30 dias atrás
    import os
    import time

    past_time = time.time() - (30 * 86400)
    os.utime(old_file, (past_time, past_time))

    # Cria arquivo recente
    recent_file = backup_dir / "quercus_backup_20260918_120000.db.gz"
    with gzip.open(recent_file, "wb") as f:
        f.write(b"recent_data")

    deleted = backup.clean_old_backups(backup_dir, retention_days=7)
    assert old_file in deleted
    assert not old_file.exists()
    assert recent_file.exists()
