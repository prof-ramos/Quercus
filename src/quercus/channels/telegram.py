"""Adaptador do Telegram totalmente desacoplado da lógica de negócio.

Implementa:
- Contratos tipados: QuercusMessage, QuercusResponse, MediaAttachment.
- Verificação fail-closed com allowlist (TELEGRAM_ALLOWED_USERS).
- Protocolo MEDIA:<caminho> para upload nativo de mídia.
- Comandos administrativos: /start, /new, /status, /today, /memory.
- Redefinição limpa de sessão conversacional com /new.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from quercus import persistence

MEDIA_TAG_PATTERN = re.compile(r"MEDIA:([^\s]+)")
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


@dataclass(frozen=True)
class MediaAttachment:
    """Anexo de mídia para envio nativo no Telegram."""

    file_path: str
    media_type: str  # photo, document, audio, voice
    caption: str | None = None


@dataclass(frozen=True)
class QuercusMessage:
    """Contrato canônico de entrada desacoplado do transporte."""

    user_id: str
    chat_id: int
    text: str
    timestamp: str
    message_id: int | None = None
    is_command: bool = False
    command: str | None = None
    command_args: str | None = None


@dataclass(frozen=True)
class QuercusResponse:
    """Contrato canônico de saída emitido pela aplicação/agente."""

    text: str
    media: list[MediaAttachment] = field(default_factory=list)
    clear_session: bool = False


class AgentDispatcher(Protocol):
    """Protocolo do serviço de aplicação que processa mensagens."""

    async def dispatch(self, message: QuercusMessage) -> QuercusResponse:
        """Processa a mensagem e retorna a resposta."""
        ...


def parse_media_tags(text: str) -> tuple[str, list[MediaAttachment]]:
    """Detecta tags MEDIA:<path> no texto e extrai os anexos correspondentes.

    Retorna o texto sanitizado (sem as tags) e a lista de MediaAttachment.
    """
    matches = MEDIA_TAG_PATTERN.findall(text)
    attachments: list[MediaAttachment] = []

    for match_path in matches:
        ext = Path(match_path).suffix.lower()
        if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            media_type = "photo"
        elif ext in {".mp3", ".m4a", ".ogg", ".wav"}:
            media_type = "audio"
        else:
            media_type = "document"

        attachments.append(MediaAttachment(file_path=match_path, media_type=media_type))

    cleaned_text = MEDIA_TAG_PATTERN.sub("", text).strip()
    return cleaned_text, attachments


def split_text_chunks(
    text: str, max_length: int = TELEGRAM_MAX_MESSAGE_LENGTH
) -> list[str]:
    """Divide textos longos no limite permitido pela API do Telegram."""
    if len(text) <= max_length:
        return [text] if text else []

    chunks: list[str] = []
    lines = text.split("\n")
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            while len(line) > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
            current_chunk = line
        else:
            current_chunk = f"{current_chunk}\n{line}" if current_chunk else line

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


class TelegramAdapter:
    """Gateway do bot do Telegram responsável exclusivamente por I/O e segurança."""

    def __init__(
        self,
        *,
        bot_token: str,
        allowed_users: Sequence[int | str] | set[int | str],
        dispatcher: AgentDispatcher,
    ) -> None:
        self.bot_token = bot_token
        self.allowed_users: set[str] = {
            str(u).strip() for u in allowed_users if str(u).strip()
        }
        self.dispatcher = dispatcher

    def is_user_allowed(self, user_id: int | str | None) -> bool:
        """Verificação estrita fail-closed."""
        if user_id is None:
            return False
        return str(user_id) in self.allowed_users

    async def handle_update(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Ponto único de recepção de updates (mensagens e comandos)."""
        if update.effective_user is None or update.effective_chat is None:
            return

        user_id = str(update.effective_user.id)
        if not self.is_user_allowed(user_id):
            # Fail-closed: ignora silenciosamente requisições não autorizadas
            return

        message = update.effective_message
        if message is None or not message.text:
            return

        raw_text = message.text.strip()
        is_command = raw_text.startswith("/")
        command: str | None = None
        command_args: str | None = None

        if is_command:
            parts = raw_text.split(maxsplit=1)
            command = parts[0][1:].split("@")[0]  # remove / e sufixo de bot
            command_args = parts[1] if len(parts) > 1 else None

        quercus_msg = QuercusMessage(
            user_id=user_id,
            chat_id=update.effective_chat.id,
            text=raw_text,
            timestamp=persistence._normalize_iso_utc(),
            message_id=message.message_id,
            is_command=is_command,
            command=command,
            command_args=command_args,
        )

        response = await self.dispatcher.dispatch(quercus_msg)
        await self.send_response(update, response)

    async def send_response(self, update: Update, response: QuercusResponse) -> None:
        """Envia a resposta do agente com suporte a chunking e mídias nativas."""
        if update.effective_chat is None:
            return

        chat_id = update.effective_chat.id
        bot = update.get_bot()

        # 1. Trata tags MEDIA: incorporadas no texto da resposta
        cleaned_text, extracted_media = parse_media_tags(response.text)
        all_media = list(response.media) + extracted_media

        # 2. Envia mensagens de texto em blocos se necessário
        if cleaned_text:
            chunks = split_text_chunks(cleaned_text)
            for chunk in chunks:
                await bot.send_message(chat_id=chat_id, text=chunk)

        # 3. Envia anexos de mídia nativos
        for attachment in all_media:
            path = Path(attachment.file_path)
            if not path.exists():
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"[Aviso: Arquivo de mídia '{path.name}' "
                        f"não encontrado no servidor.]"
                    ),
                )
                continue

            with open(path, "rb") as f:
                if attachment.media_type == "photo":
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=attachment.caption,
                    )
                elif attachment.media_type == "audio":
                    await bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        caption=attachment.caption,
                    )
                else:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        caption=attachment.caption,
                    )

    def build_application(self) -> Application[Any, Any, Any, Any, Any, Any]:
        """Configura a aplicação python-telegram-bot com handlers desacoplados."""
        app = ApplicationBuilder().token(self.bot_token).build()

        commands = [
            "start",
            "new",
            "status",
            "today",
            "week",
            "memory",
            "consolidate",
        ]
        for cmd in commands:
            app.add_handler(CommandHandler(cmd, self.handle_update))

        text_filter = filters.TEXT & ~filters.COMMAND
        app.add_handler(MessageHandler(text_filter, self.handle_update))
        return app
