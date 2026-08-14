import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


MAIBOT_ROOT = Path(__file__).resolve().parents[3]
if str(MAIBOT_ROOT) not in sys.path:
    sys.path.insert(0, str(MAIBOT_ROOT))

from src.plugin_runtime.host.hook_spec_registry import HookSpecRegistry
from src.services import send_service


class SendHookContractTests(unittest.TestCase):
    def test_outbound_transform_hook_has_long_tts_timeout(self):
        registry = HookSpecRegistry()
        send_service.register_send_service_hook_specs(registry)

        spec = registry.get_hook_spec("send_service.outbound_transform")

        self.assertIsNotNone(spec)
        self.assertEqual(spec.default_timeout_ms, 120_000)
        self.assertTrue(spec.allow_kwargs_mutation)
        self.assertFalse(spec.allow_abort)


class SendHookSourceKindTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_to_target_passes_maisaka_source_kind_to_transform_hook(self):
        captured = {}

        async def fake_invoke(hook_name, message, **kwargs):
            captured.update(kwargs)
            return send_service.HookDispatchResult(hook_name=hook_name, kwargs={}), message

        with (
            patch.object(send_service, "_build_outbound_session_message", return_value=object()),
            patch.object(send_service, "_invoke_send_hook", new=AsyncMock(side_effect=fake_invoke)),
            patch.object(send_service, "send_session_message_with_message", new=AsyncMock(return_value=None)),
        ):
            await send_service._send_to_target_with_message(
                message_sequence=send_service.MessageSequence(
                    components=[send_service.TextComponent("浣犲ソ")]
                ),
                stream_id="missing-test-stream",
                maisaka_source_kind="guided_reply",
            )

        self.assertEqual(captured.get("maisaka_source_kind"), "guided_reply")


if __name__ == "__main__":
    unittest.main()

