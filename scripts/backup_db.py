#!/usr/bin/env python3
"""Script CLI de backup online do banco SQLite do Quercus.

Uso:
  python scripts/backup_db.py [--db-path /app/data/quercus.db]
"""

import argparse
import os
import sys
from pathlib import Path

# Adiciona src ao path para execução direta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from quercus import backup, persistence


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera backup online compactado do banco SQLite em modo WAL."
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("QUERCUS_DB_PATH", "quercus.db"),
        help="Caminho do arquivo quercus.db (padrão: $QUERCUS_DB_PATH)",
    )
    parser.add_argument(
        "--backup-dir",
        default=os.getenv("QUERCUS_BACKUP_DIR", "backups"),
        help="Diretório de destino (padrão: $QUERCUS_BACKUP_DIR)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=int(os.getenv("QUERCUS_BACKUP_RETENTION_DAYS", "7")),
        help="Dias de retenção de backups (padrão: 7)",
    )

    args = parser.parse_args()
    db_file = Path(args.db_path)
    if not db_file.exists():
        print(f"[ERRO] Banco de dados não encontrado: {db_file}", file=sys.stderr)
        return 1

    print(f"[*] Conectando ao banco em modo WAL: {db_file}")
    conn = persistence.connect(str(db_file))
    try:
        print(f"[*] Iniciando backup online para: {args.backup_dir}")
        backup_file = backup.create_backup(
            conn,
            args.backup_dir,
            retention_days=args.retention_days,
        )
        size_kb = backup_file.stat().st_size / 1024.0
        print(
            f"[OK] Backup gerado com sucesso: {backup_file} ({size_kb:.1f} KB, "
            f"retenção: {args.retention_days} dias)"
        )
        return 0
    except Exception as exc:
        print(f"[FALHA] Erro durante o backup: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
