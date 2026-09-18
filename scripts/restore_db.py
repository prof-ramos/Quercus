#!/usr/bin/env python3
"""Script CLI para restauração e teste de integridade de backups do Quercus.

Uso:
  python scripts/restore_db.py --backup-file backups/b.db.gz --verify-only
"""

import argparse
import sys
from pathlib import Path

# Adiciona src ao path para execução direta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from quercus import backup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restaura e valida integridade de backup do SQLite do Quercus."
    )
    parser.add_argument(
        "--backup-file",
        required=True,
        help="Caminho do arquivo de backup (.db.gz ou .db)",
    )
    parser.add_argument(
        "--target-db",
        default=None,
        help="Caminho de destino para restauração física do banco",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Apenas valida integridade sem sobrescrever",
    )

    args = parser.parse_args()
    backup_path = Path(args.backup_file)
    if not backup_path.exists():
        print(
            f"[ERRO] Arquivo de backup não encontrado: {backup_path}",
            file=sys.stderr,
        )
        return 1

    if not args.verify_only and not args.target_db:
        print(
            "[ERRO] Você deve informar --target-db ou usar a flag --verify-only.",
            file=sys.stderr,
        )
        return 1

    print(f"[*] Validando backup: {backup_path}")
    try:
        res = backup.restore_backup(
            backup_path=backup_path,
            target_db_path=args.target_db,
            verify_only=args.verify_only,
        )

        print("[OK] Verificação de integridade aprovada (PRAGMA integrity_check = ok)")
        print("[*] Contagem de registros por tabela restaurada:")
        for table, count in res["table_counts"].items():
            print(f"    - {table}: {count} registros")

        if args.verify_only:
            print("[OK] Teste concluído com sucesso em modo verify-only.")
        else:
            print(f"[OK] Banco restaurado fisicamente com sucesso em: {args.target_db}")

        return 0
    except Exception as exc:
        print(f"[FALHA] Falha na restauração do backup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
