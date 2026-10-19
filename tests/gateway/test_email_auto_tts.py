"""Email must not inherit a global speak default it cannot deliver (#141792)."""

import asyncio
import json
from unittest.mock import Mock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.event import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from plugins.platforms.email.adapter import EmailAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize("message_type", [MessageType.TEXT, MessageType.VOICE])
async def test_email_global_auto_tts_sends_only_text(monkeypatch, tmp_path, message_type):
    adapter = EmailAdapter(PlatformConfig(enabled=True))
    sent = []
    monkeypatch.setattr(adapter, "_smtp_send", sent.append)
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"voice": {"auto_tts": True}})
    runner = GatewayRunner.__new__(GatewayRunner)
    runner._voice_mode = {}
    runner.adapters = {Platform.EMAIL: adapter}
    runner._sync_voice_mode_state_to_adapter(adapter)
    event = MessageEvent(
        text="hello", message_type=message_type,
        source=SessionSource(platform=Platform.EMAIL, chat_id="reader@example.test", user_id="reader"),
    )
    audio = tmp_path / "reply.mp3"

    def synthesize(**kwargs):
        audio.write_bytes(b"synthetic audio")
        return json.dumps({"success": True, "file_path": str(audio)})

    tts = Mock(side_effect=synthesize)
    monkeypatch.setattr("tools.tts_tool.text_to_speech_tool", tts)
    # Exercise both production automatic-speech gates, including the streamed-reply path.
    if adapter._wants_auto_tts(event, "email:reader", asyncio.Event(), "hello back", []):
        await adapter._synthesize_auto_tts("hello back")
    if runner._should_send_voice_reply(event, "hello back", [], already_sent=True):
        await runner._send_voice_reply(event, "hello back")
    result = await adapter.send(event.source.chat_id, "hello back")

    assert result.success
    assert [part.get_payload(decode=True).decode("utf-8") for msg in sent
            for part in msg.walk() if part.get_content_type() == "text/plain"] == ["hello back"]
    tts.assert_not_called()


def test_email_preserves_explicit_voice_opt_in():
    adapter = EmailAdapter(PlatformConfig(enabled=True))
    adapter._auto_tts_default = True
    adapter._auto_tts_enabled_chats.add("explicit")
    adapter._auto_tts_disabled_chats.add("off")
    assert adapter._should_auto_tts_for_chat("explicit") is True
    assert adapter._should_auto_tts_for_chat("off") is False
    assert adapter._should_auto_tts_for_chat("default") is False
