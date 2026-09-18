"""Testes do adaptador desacoplado do Telegram e protocolo MEDIA:."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from telegram import Chat, Message, Update, User

from quercus.channels.telegram import (
    MediaAttachment,
    QuercusMessage,
    QuercusResponse,
    TelegramAdapter,
    parse_media_tags,
    split_text_chunks,
)


class MockDispatcher:
    """Dispatcher simulado para capturar mensagens e emitir respostas de teste."""

    def __init__(self, response: QuercusResponse | None = None) -> None:
        self.received_messages: list[QuercusMessage] = []
        self.response = response or QuercusResponse(text="Resposta do agente")

    async def dispatch(self, message: QuercusMessage) -> QuercusResponse:
        self.received_messages.append(message)
        return self.response


def test_parse_media_tags_and_cleaning() -> None:
    text = (
        "Aqui está o cronograma de estudos.\n"
        "MEDIA:/tmp/cronograma.png\n"
        "Bons estudos!\n"
        "MEDIA:/tmp/audio_revisao.mp3\n"
        "MEDIA:/tmp/edital.pdf"
    )
    cleaned, media = parse_media_tags(text)

    assert "MEDIA:" not in cleaned
    assert "Aqui está o cronograma de estudos." in cleaned
    assert "Bons estudos!" in cleaned
    assert len(media) == 3

    assert media[0] == MediaAttachment(
        file_path="/tmp/cronograma.png", media_type="photo"
    )
    assert media[1] == MediaAttachment(
        file_path="/tmp/audio_revisao.mp3", media_type="audio"
    )
    assert media[2] == MediaAttachment(
        file_path="/tmp/edital.pdf", media_type="document"
    )


def test_split_text_chunks() -> None:
    short_text = "Mensagem curta."
    chunks = split_text_chunks(short_text, max_length=100)
    assert chunks == ["Mensagem curta."]

    long_line = "A" * 150
    chunks_long = split_text_chunks(long_line, max_length=50)
    assert len(chunks_long) == 3
    assert chunks_long == ["A" * 50, "A" * 50, "A" * 50]


def test_allowlist_security_fail_closed() -> None:
    dispatcher = MockDispatcher()
    adapter = TelegramAdapter(
        bot_token="test-token",
        allowed_users=[12345, "67890"],
        dispatcher=dispatcher,
    )

    assert adapter.is_user_allowed(12345)
    assert adapter.is_user_allowed("12345")
    assert adapter.is_user_allowed("67890")
    assert not adapter.is_user_allowed(99999)
    assert not adapter.is_user_allowed(None)
    assert not adapter.is_user_allowed("")


def test_unauthorized_user_is_ignored_silently() -> None:
    async def _run() -> None:
        dispatcher = MockDispatcher()
        adapter = TelegramAdapter(
            bot_token="test-token",
            allowed_users=[12345],
            dispatcher=dispatcher,
        )

        # Cria mock de Update de usuário intruso
        update = MagicMock(spec=Update)
        user = MagicMock(spec=User)
        user.id = 99999
        update.effective_user = user
        update.effective_chat = MagicMock(spec=Chat)
        update.effective_chat.id = 99999
        update.effective_message = MagicMock(spec=Message)
        update.effective_message.text = "Olá Quercus"

        context = MagicMock()

        await adapter.handle_update(update, context)

        # Dispatcher nunca foi acionado
        assert len(dispatcher.received_messages) == 0

    asyncio.run(_run())


def test_authorized_user_message_and_media_dispatch(tmp_path: Path) -> None:
    async def _run() -> None:
        photo_file = tmp_path / "diagrama.png"
        photo_file.write_bytes(b"fake-image-bytes")

        resp_text = f"Análise concluída.\nMEDIA:{photo_file}"
        dispatcher = MockDispatcher(response=QuercusResponse(text=resp_text))

        adapter = TelegramAdapter(
            bot_token="test-token",
            allowed_users=[12345],
            dispatcher=dispatcher,
        )

        update = MagicMock(spec=Update)
        bot = AsyncMock()
        update.get_bot.return_value = bot

        user = MagicMock(spec=User)
        user.id = 12345
        update.effective_user = user

        chat = MagicMock(spec=Chat)
        chat.id = 12345
        update.effective_chat = chat

        message = MagicMock(spec=Message)
        message.text = "Como está minha meta de hoje?"
        message.message_id = 42
        update.effective_message = message

        context = MagicMock()

        await adapter.handle_update(update, context)

        assert len(dispatcher.received_messages) == 1
        msg = dispatcher.received_messages[0]
        assert msg.user_id == "12345"
        assert msg.chat_id == 12345
        assert msg.text == "Como está minha meta de hoje?"
        assert not msg.is_command

        bot.send_message.assert_awaited_once_with(
            chat_id=12345, text="Análise concluída."
        )
        assert bot.send_photo.await_count == 1

    asyncio.run(_run())


def test_command_new_session_dispatch() -> None:
    async def _run() -> None:
        dispatcher = MockDispatcher(
            response=QuercusResponse(
                text="Sessão reiniciada. Nova fronteira de estudo iniciada.",
                clear_session=True,
            )
        )

        adapter = TelegramAdapter(
            bot_token="test-token",
            allowed_users=[12345],
            dispatcher=dispatcher,
        )

        update = MagicMock(spec=Update)
        bot = AsyncMock()
        update.get_bot.return_value = bot

        user = MagicMock(spec=User)
        user.id = 12345
        update.effective_user = user

        chat = MagicMock(spec=Chat)
        chat.id = 12345
        update.effective_chat = chat

        message = MagicMock(spec=Message)
        message.text = "/new"
        message.message_id = 43
        update.effective_message = message

        context = MagicMock()

        await adapter.handle_update(update, context)

        assert len(dispatcher.received_messages) == 1
        msg = dispatcher.received_messages[0]
        assert msg.is_command
        assert msg.command == "new"

        bot.send_message.assert_awaited_once_with(
            chat_id=12345,
            text="Sessão reiniciada. Nova fronteira de estudo iniciada.",
        )

    asyncio.run(_run())
