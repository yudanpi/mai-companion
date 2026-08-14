import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PLUGIN_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mai_companion_voice_reply_integration", PLUGIN_DIR / "voice_reply.py")
voice_reply = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = voice_reply
spec.loader.exec_module(voice_reply)


class FakeTTS:
    async def synthesize(self, text):
        return SimpleNamespace(audio_base64="UklGRg==", elapsed_seconds=0.1)


class FailingTTS:
    async def synthesize(self, text):
        raise RuntimeError("offline")


def config():
    return SimpleNamespace(
        voice_reply_enabled=True,
        voice_private_whitelist=["1234567890"],
        voice_max_chars=240,
        tts_timeout_seconds=1.0,
        send_text_on_voice_failure=True,
    )


def message(*, group=False):
    return {
        "platform": "qq",
        "message_info": {
            "group_info": {"group_id": "group-1"} if group else None,
            "additional_config": {"platform_io_target_user_id": "1234567890"},
        },
        "raw_message": [{"type": "text", "data": "浠婃櫄鏃╃偣浼戞伅"}],
        "processed_plain_text": "浠婃櫄鏃╃偣浼戞伅",
        "is_command": False,
        "is_emoji": False,
        "is_picture": False,
    }


class VoiceReplyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_whitelist_private_reply_produces_one_voice_message(self):
        transformer = voice_reply.VoiceReplyTransformer(config(), FakeTTS())
        result = await transformer.transform_hook(
            message=message(),
            stream_id="private-stream",
            maisaka_source_kind="guided_reply",
        )

        sent_message = result["modified_kwargs"]["message"]
        self.assertEqual(len(sent_message["raw_message"]), 1)
        self.assertEqual(sent_message["raw_message"][0]["type"], "voice")

    async def test_system_confirmation_and_group_reply_remain_text(self):
        transformer = voice_reply.VoiceReplyTransformer(config(), FakeTTS())

        command_result = await transformer.transform_hook(
            message=message(),
            stream_id="private-stream",
            maisaka_source_kind="plugin_send",
        )
        group_result = await transformer.transform_hook(
            message=message(group=True),
            stream_id="group-stream",
            maisaka_source_kind="guided_reply",
        )

        self.assertEqual(command_result["modified_kwargs"]["message"]["raw_message"][0]["type"], "text")
        self.assertEqual(group_result["modified_kwargs"]["message"]["raw_message"][0]["type"], "text")

    async def test_tts_failure_produces_one_original_text_message(self):
        original = message()
        transformer = voice_reply.VoiceReplyTransformer(config(), FailingTTS())
        result = await transformer.transform_hook(
            message=original,
            stream_id="private-stream",
            maisaka_source_kind="guided_reply",
        )

        sent_message = result["modified_kwargs"]["message"]
        self.assertIs(sent_message, original)
        self.assertEqual(len(sent_message["raw_message"]), 1)
        self.assertEqual(sent_message["raw_message"][0]["type"], "text")


if __name__ == "__main__":
    unittest.main()

