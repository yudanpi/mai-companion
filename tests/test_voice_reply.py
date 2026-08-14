import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PLUGIN_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mai_companion_voice_reply", PLUGIN_DIR / "voice_reply.py")
voice_reply = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = voice_reply
spec.loader.exec_module(voice_reply)


class FakeTTS:
    def __init__(self, audio_base64="UklGRg=="):
        self.audio_base64 = audio_base64
        self.calls = []

    async def synthesize(self, text):
        self.calls.append(text)
        return SimpleNamespace(audio_base64=self.audio_base64, elapsed_seconds=0.1)


class FailingTTS:
    async def synthesize(self, text):
        raise RuntimeError("IndexTTS offline")


class FlakyTTS:
    def __init__(self):
        self.calls = 0

    async def synthesize(self, text):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("stale IndexTTS upload")
        return SimpleNamespace(audio_base64="UklGRg==", elapsed_seconds=0.1)


class HangingTTS:
    async def synthesize(self, text):
        await asyncio.sleep(0.05)


def config(**overrides):
    values = {
        "voice_reply_enabled": True,
        "voice_private_whitelist": ["1234567890"],
        "voice_max_chars": 240,
        "tts_timeout_seconds": 120.0,
        "send_text_on_voice_failure": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_message(
    *,
    platform="qq",
    target_user_id="1234567890",
    group_id=None,
    components=None,
    transformed=False,
    is_command=False,
):
    additional_config = {"platform_io_target_user_id": target_user_id}
    if transformed:
        additional_config["mai_voice_transformed"] = True
    return {
        "platform": platform,
        "message_info": {
            "group_info": {"group_id": group_id} if group_id else None,
            "additional_config": additional_config,
        },
        "raw_message": components or [{"type": "text", "data": "濮愬鍦ㄥ悧"}],
        "processed_plain_text": "濮愬鍦ㄥ悧",
        "is_command": is_command,
        "is_emoji": False,
        "is_picture": False,
    }


class VoiceReplyPredicateTests(unittest.TestCase):
    def test_should_transform_only_guided_reply_private_whitelist(self):
        message = make_message()
        self.assertTrue(voice_reply.should_transform(message, "guided_reply", config()))
        self.assertFalse(voice_reply.should_transform(message, "plugin_send", config()))
        self.assertFalse(voice_reply.should_transform(make_message(group_id="group-1"), "guided_reply", config()))
        self.assertFalse(voice_reply.should_transform(make_message(target_user_id="10001"), "guided_reply", config()))
        self.assertFalse(voice_reply.should_transform(make_message(is_command=True), "guided_reply", config()))
        self.assertFalse(voice_reply.should_transform(make_message(transformed=True), "guided_reply", config()))

    def test_should_transform_configured_weather_plugin_source(self):
        message = make_message()
        config_value = config()
        config_value.voice_plugin_source_kinds = [
            "plugin_proactive:maibot-team.current-weather"
        ]
        self.assertTrue(
            voice_reply.should_transform(
                message,
                "plugin_proactive:maibot-team.current-weather",
                config_value,
            )
        )

    def test_should_skip_non_text_and_oversized_messages(self):
        image = make_message(components=[{"type": "image", "data": "hash"}])
        oversized = make_message()
        oversized["processed_plain_text"] = "x" * 241
        oversized["raw_message"] = [{"type": "text", "data": "x" * 241}]
        self.assertFalse(voice_reply.should_transform(image, "guided_reply", config()))
        self.assertFalse(voice_reply.should_transform(oversized, "guided_reply", config()))


class VoiceReplyTransformerTests(unittest.IsolatedAsyncioTestCase):
    async def test_transform_success_returns_voice_and_preserves_text(self):
        tts = FakeTTS()
        transformer = voice_reply.VoiceReplyTransformer(config(), tts)

        result = await transformer.transform_hook(
            message=make_message(),
            stream_id="stream-1",
            maisaka_source_kind="guided_reply",
        )

        message = result["modified_kwargs"]["message"]
        self.assertEqual(message["raw_message"][0]["type"], "voice")
        self.assertEqual(message["raw_message"][0]["binary_data_base64"], "UklGRg==")
        self.assertEqual(message["processed_plain_text"], "濮愬鍦ㄥ悧")
        self.assertTrue(message["message_info"]["additional_config"]["mai_voice_transformed"])
        self.assertEqual(tts.calls, ["濮愬鍦ㄥ悧"])

    async def test_transform_failure_returns_original_message(self):
        original = make_message()
        transformer = voice_reply.VoiceReplyTransformer(config(), FailingTTS())

        result = await transformer.transform_hook(
            message=original,
            stream_id="stream-1",
            maisaka_source_kind="guided_reply",
        )

        self.assertIs(result["modified_kwargs"]["message"], original)

    async def test_transform_timeout_returns_original_message(self):
        original = make_message()
        transformer = voice_reply.VoiceReplyTransformer(
            config(tts_timeout_seconds=0.001),
            HangingTTS(),
        )

        result = await transformer.transform_hook(
            message=original,
            stream_id="stream-1",
            maisaka_source_kind="guided_reply",
        )

        self.assertIs(result["modified_kwargs"]["message"], original)

    async def test_transform_retries_once_after_transient_tts_failure(self):
        tts = FlakyTTS()
        transformer = voice_reply.VoiceReplyTransformer(config(), tts)

        result = await transformer.transform_hook(
            message=make_message(),
            stream_id="stream-1",
            maisaka_source_kind="guided_reply",
        )

        message = result["modified_kwargs"]["message"]
        self.assertEqual(message["raw_message"][0]["type"], "voice")
        self.assertEqual(tts.calls, 2)


if __name__ == "__main__":
    unittest.main()

