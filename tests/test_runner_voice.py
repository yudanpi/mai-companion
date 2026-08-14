import importlib.util
import asyncio
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from unittest.mock import patch


PLUGIN_DIR = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "mai_companion_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PLUGIN_DIR)]
sys.modules[PACKAGE_NAME] = package
spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.runner", PLUGIN_DIR / "runner.py")
runner_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner_module
spec.loader.exec_module(runner_module)
CompanionRunner = runner_module.CompanionRunner


class RunnerVoiceTests(unittest.IsolatedAsyncioTestCase):
    def make_runner(self):
        runner = CompanionRunner.__new__(CompanionRunner)
        runner.config = SimpleNamespace(
            voice_enabled=True,
            send_text_on_voice_failure=True,
            voice_max_chars=240,
        )
        runner.ctx = SimpleNamespace(
            send=SimpleNamespace(text=AsyncMock(), hybrid=AsyncMock()),
            logger=SimpleNamespace(info=Mock(), warning=Mock(), error=Mock()),
        )
        runner.tts = SimpleNamespace(synthesize=AsyncMock())
        runner._tts_lock = asyncio.Lock()
        runner._manual_tasks = set()
        return runner

    async def test_voice_success_sends_only_hybrid(self):
        runner = self.make_runner()
        runner.tts.synthesize.return_value = SimpleNamespace(audio_base64="AQI=", elapsed_seconds=2.0)

        result = await runner._send_generated("姐姐提醒你早点休息", "stream-1")

        self.assertEqual(result, "voice")
        runner.ctx.send.hybrid.assert_awaited_once()
        runner.ctx.send.text.assert_not_awaited()

    async def test_voice_failure_falls_back_to_text(self):
        runner = self.make_runner()
        runner.tts.synthesize.side_effect = RuntimeError("IndexTTS offline")

        result = await runner._send_generated("鍏堝枬鐐规按", "stream-1")

        self.assertEqual(result, "text")
        runner.ctx.send.text.assert_awaited_once_with("鍏堝枬鐐规按", "stream-1")
        runner.ctx.send.hybrid.assert_not_awaited()

    async def test_diagnostic_reports_tts_without_sending(self):
        runner = self.make_runner()
        runner.config.news_feeds = []
        runner.config.weather_location = ""
        runner.config.request_timeout_seconds = 1.0
        runner.config.target_qq = "1234567890"
        runner.config.feed_count = 1
        runner.config.text_model = "replyer"
        runner.ctx.api = SimpleNamespace(call=AsyncMock(return_value={"result": True, "data": [{}]}))
        runner.ctx.llm = SimpleNamespace(
            get_available_models=AsyncMock(return_value=[]),
            generate=AsyncMock(return_value={"response": "OK"}),
        )
        runner._target_stream = AsyncMock(return_value="stream-1")
        runner.tts.check = AsyncMock(return_value=(True, "IndexTTS online"))

        with patch.object(runner_module, "get_online_topic", AsyncMock(return_value=None)):
            status = await runner.diagnostic()

        self.assertTrue(status["tts"])
        runner.ctx.send.text.assert_not_called()
        runner.ctx.send.hybrid.assert_not_called()

    async def test_run_now_forces_an_immediate_companion_message(self):
        runner = self.make_runner()
        runner.run_once = AsyncMock(return_value=True)

        result = await runner.run_now()

        self.assertTrue(result)
        runner.run_once.assert_awaited_once_with(force=True)

    async def test_trigger_now_schedules_without_waiting_for_tts(self):
        runner = self.make_runner()
        runner.run_now = AsyncMock(return_value=True)

        self.assertTrue(runner.trigger_now())
        await asyncio.sleep(0)

        runner.run_now.assert_awaited_once()
        for task in tuple(runner._manual_tasks):
            task.cancel()


class RunnerProcessLaunchTests(unittest.TestCase):
    def test_start_tts_process_uses_configured_python_path(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        with TemporaryDirectory() as directory:
            root = Path(directory)
            python_path = root / "python.exe"
            script = root / "webui.py"
            python_path.write_bytes(b"")
            script.write_text("print('test')", encoding="utf-8")
            runner = CompanionRunner.__new__(CompanionRunner)
            runner.config = SimpleNamespace(
                tts_process_dir=str(root),
                tts_python_path=str(python_path),
                tts_webui_script="webui.py",
            )
            runner.ctx = SimpleNamespace(logger=SimpleNamespace(info=Mock()))
            fake_process = object()
            with patch.object(runner_module.subprocess, "Popen", return_value=fake_process) as popen:
                result = runner._start_tts_process()
            self.assertIs(result, fake_process)
            args = popen.call_args.args[0]
            self.assertEqual(Path(args[0]), python_path)
            self.assertEqual(Path(args[2]), script)



class RunnerCustomProcessLaunchTests(unittest.TestCase):
    def test_start_tts_process_honors_custom_python_path(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        with TemporaryDirectory() as directory:
            root = Path(directory)
            python_path = root / "custom-python.exe"
            script = root / "custom-webui.py"
            python_path.write_bytes(b"")
            script.write_text("print('test')", encoding="utf-8")
            runner = CompanionRunner.__new__(CompanionRunner)
            runner.config = SimpleNamespace(
                tts_process_dir=str(root),
                tts_python_path=str(python_path),
                tts_webui_script=str(script),
            )
            runner.ctx = SimpleNamespace(logger=SimpleNamespace(info=Mock()))
            with patch.object(runner_module.subprocess, "Popen", return_value=object()) as popen:
                runner._start_tts_process()
            self.assertEqual(Path(popen.call_args.args[0][0]), python_path)


