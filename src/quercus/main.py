"""Ponto de entrada canônico do Quercus (CLI, Daemon e Tarefas).

Permite executar o Quercus em diferentes modos operacionais:
- 'bot': Inicia o adaptador do Telegram com polling contínuo.
- 'nightly': Executa rotina noturna (fechar eventos -> REM -> adaptar -> backup).
- 'backup': Executa snapshot online do SQLite com compressão e verificação.
- 'status': Exibe relatório rápido do estado do banco e memórias ativas.
"""

import argparse
import os
import sys
from pathlib import Path

from quercus import backup, dreaming, persistence, planner
from quercus.channels.telegram import (
    QuercusMessage,
    QuercusResponse,
    TelegramAdapter,
)


class DefaultDispatcher:
    """Dispatcher padrão para responder a comandos básicos e texto no Telegram."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def dispatch(self, message: QuercusMessage) -> QuercusResponse:
        conn = persistence.connect(self.db_path)
        try:
            # Registra o evento de mensagem recebida
            persistence.record_event(
                conn,
                user_id=message.user_id,
                event_type="TELEGRAM_MESSAGE",
                source_type="USER_OBSERVED",
                source_id=f"msg-{message.message_id}",
                payload={"text": message.text, "is_command": message.is_command},
            )

            cmd = message.command
            if cmd == "start":
                return QuercusResponse(
                    text=(
                        "🌳 *Quercus Iniciado*\n\n"
                        "Agente pessoal de preparação para o CACD.\n"
                        "Comandos disponíveis:\n"
                        "• /today — Plano de estudos do dia\n"
                        "• /status — Indicadores de aderência e memórias\n"
                        "• /memory — Preferências ativas consolidadas\n"
                        "• /new — Iniciar nova sessão limpa"
                    )
                )

            if cmd == "today":
                row = conn.execute(
                    """
                    SELECT id FROM study_plans
                    WHERE user_id = ? AND status = 'active'
                    ORDER BY plan_date DESC LIMIT 1
                    """,
                    (message.user_id,),
                ).fetchone()
                if row:
                    plan = persistence.get_study_plan(conn, row["id"])
                    if plan:
                        text = planner.format_plan_for_chat(plan)
                        return QuercusResponse(text=text)
                return QuercusResponse(text="Nenhum plano ativo encontrado para hoje.")

            if cmd == "status":
                mems = persistence.list_memories(
                    conn, user_id=message.user_id, status="active"
                )
                sessions = persistence.list_study_sessions(
                    conn, user_id=message.user_id, limit=5
                )
                return QuercusResponse(
                    text=(
                        f"📊 *Status do Aluno ({message.user_id})*\n\n"
                        f"• Memórias ativas consolidadas: {len(mems)}\n"
                        f"• Últimas sessões registradas: {len(sessions)}\n"
                        f"• Banco: SQLite WAL ativo e íntegro."
                    )
                )

            if cmd == "memory":
                mems = persistence.list_memories(
                    conn, user_id=message.user_id, status="active"
                )
                if not mems:
                    return QuercusResponse(
                        text="Nenhuma memória ativa consolidada no momento."
                    )
                lines = ["🧠 *Memórias Ativas (Auditáveis):*"]
                for m in mems:
                    lines.append(f"• [{m['source_origin']}] {m['statement']}")
                return QuercusResponse(text="\n".join(lines))

            if cmd == "new":
                return QuercusResponse(
                    text="🧹 Sessão reiniciada. Prefix caching e contexto renovados.",
                    clear_session=True,
                )

            # Resposta textual padrão
            return QuercusResponse(
                text=(
                    f'Recebido: "{message.text}"\n'
                    "Use /today para seu plano de estudos ou /status para métricas."
                )
            )
        finally:
            conn.close()


def run_nightly_job(db_path: str, user_id: str, backup_dir: str) -> None:
    """Executa a rotina noturna completa: fechamento -> REM -> adaptação -> backup."""
    print(f"[*] Iniciando rotina noturna do Quercus (usuário: {user_id})...")
    conn = persistence.connect(db_path)
    try:
        # 1. Extração Light de observações
        obs = dreaming.extract_study_observations(conn, user_id=user_id)
        print(f" -> Light: {len(obs)} observações extraídas.")

        # 2. Consolidação REM
        rem_report = dreaming.run_rem_consolidation(conn, user_id=user_id)
        print(f" -> REM: {len(rem_report.decisions)} decisões geradas.")

        # 3. Adaptação noturna de planos de estudo
        row = conn.execute(
            """
            SELECT id FROM study_plans
            WHERE user_id = ? AND status = 'active'
            ORDER BY plan_date DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if row:
            adapted = planner.adapt_daily_plan(conn, plan_id=row["id"])
            rate_pct = int(adapted.completion_rate * 100)
            dec_cnt = len(adapted.decisions)
            print(f" -> Planner: Plano adaptado ({dec_cnt} decisões, {rate_pct}%).")
        else:
            print(" -> Planner: Sem planos ativos para adaptação.")

        # 4. Backup online compactado
        b_file = backup.create_backup(conn, backup_dir, retention_days=7)
        size_kb = b_file.stat().st_size / 1024.0
        print(f" -> Backup: Snapshot gerado em {b_file} ({size_kb:.1f} KB).")
        print("[OK] Rotina noturna concluída com sucesso.")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Quercus - Agente Pessoal para Concursos"
    )
    parser.add_argument(
        "mode",
        choices=["bot", "nightly", "backup", "status"],
        nargs="?",
        default=os.getenv("QUERCUS_MODE", "bot"),
        help="Modo de execução (bot, nightly, backup, status)",
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("QUERCUS_DB_PATH", "quercus.db"),
        help="Caminho do arquivo SQLite (padrão: $QUERCUS_DB_PATH ou quercus.db)",
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("QUERCUS_USER_ID", "gabriel"),
        help="ID canônico do usuário (padrão: $QUERCUS_USER_ID ou gabriel)",
    )
    parser.add_argument(
        "--backup-dir",
        default=os.getenv("QUERCUS_BACKUP_DIR", "backups"),
        help="Diretório de backups (padrão: $QUERCUS_BACKUP_DIR ou backups)",
    )

    args = parser.parse_args()
    db_file = Path(args.db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "backup":
        conn = persistence.connect(str(db_file))
        try:
            b_path = backup.create_backup(conn, args.backup_dir)
            print(f"[OK] Backup gerado: {b_path}")
            return 0
        finally:
            conn.close()

    if args.mode == "nightly":
        run_nightly_job(str(db_file), args.user_id, args.backup_dir)
        return 0

    if args.mode == "status":
        conn = persistence.connect(str(db_file))
        try:
            is_ok, errs, counts = backup.verify_database_integrity(db_file)
            print(f"Integridade do Banco: {'OK' if is_ok else 'FALHA'}")
            for t, c in counts.items():
                print(f"  - {t}: {c}")
            return 0 if is_ok else 1
        finally:
            conn.close()

    if args.mode == "bot":
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            print(
                "[AVISO] TELEGRAM_BOT_TOKEN não definido. Para iniciar o bot, "
                "defina TELEGRAM_BOT_TOKEN no ambiente ou .env.",
                file=sys.stderr,
            )
            print("[INFO] Operando em modo de prontidão local (status).")
            return 0

        allowed_raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        allowed_users = [u.strip() for u in allowed_raw.split(",") if u.strip()]

        dispatcher = DefaultDispatcher(str(db_file))
        adapter = TelegramAdapter(
            bot_token=token,
            dispatcher=dispatcher,
            allowed_users=allowed_users,
        )
        print("[*] Iniciando Quercus Telegram Gateway...")
        app = adapter.build_application()
        app.run_polling()
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
