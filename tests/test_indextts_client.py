import base64
import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))
try:
    spec = importlib.util.spec_from_file_location("mai_companion_indextts_client", PLUGIN_DIR / "indextts_client.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    IndexTTSClient = module.IndexTTSClient
except (FileNotFoundError, AttributeError, ImportError):
    IndexTTSClient = None


class IndexTTSClientTests(unittest.TestCase):
    def test_audio_to_base64_reads_binary(self):
        self.assertIsNotNone(IndexTTSClient, "IndexTTSClient is not implemented")
        with self.subTest("binary encoding"):
            from tempfile import TemporaryDirectory

            with TemporaryDirectory() as directory:
                wav = Path(directory) / "out.wav"
                wav.write_bytes(b"RIFF-test")
                client = IndexTTSClient("http://127.0.0.1:7860", str(wav), 5)
                self.assertEqual(client._audio_to_base64(str(wav)), base64.b64encode(b"RIFF-test").decode())

    def test_missing_reference_audio_fails(self):
        self.assertIsNotNone(IndexTTSClient, "IndexTTSClient is not implemented")
        with self.assertRaises(FileNotFoundError):
            IndexTTSClient("http://127.0.0.1:7860", "missing.wav", 5)._validate()

    def test_completed_output_extracts_audio_path(self):
        self.assertIsNotNone(IndexTTSClient, "IndexTTSClient is not implemented")
        payload = {"msg": "process_completed", "success": True, "output": {"data": [{"path": "out.wav"}]}}
        self.assertEqual(IndexTTSClient._completed_output(payload), "out.wav")

    def test_completed_output_accepts_sse_message_list(self):
        self.assertIsNotNone(IndexTTSClient, "IndexTTSClient is not implemented")
        payload = [{"msg": "process_completed", "success": True, "output": {"data": [{"path": "out.wav"}]}}]
        self.assertEqual(IndexTTSClient._completed_output(payload), "out.wav")

    def test_queue_payload_targets_gen_single(self):
        self.assertIsNotNone(IndexTTSClient, "IndexTTSClient is not implemented")
        client = IndexTTSClient("http://127.0.0.1:7860", "ref.wav", 5)
        payload = client._queue_payload(["input"], "session-1")
        self.assertEqual(payload["fn_index"], 20)
        self.assertEqual(payload["session_hash"], "session-1")
        self.assertEqual(payload["data"], ["input"])

    def test_completed_output_unwraps_gradio_update_value(self):
        self.assertIsNotNone(IndexTTSClient, "IndexTTSClient is not implemented")
        payload = {
            "msg": "process_completed",
            "success": True,
            "output": {"data": [{"visible": True, "value": {"path": "out.wav", "url": "http://localhost/out.wav"}}]},
        }
        self.assertEqual(IndexTTSClient._completed_output(payload), "http://localhost/out.wav")


class ClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_accepts_shared_process_manager(self):
        class FakeManager:
            async def ensure_running(self):
                return True, "ready"

            def mark_activity(self):
                return None

        manager = FakeManager()
        client = IndexTTSClient("http://127.0.0.1:7860", "ref.wav", 5, process_manager=manager)
        self.assertIs(client.process_manager, manager)
        self.assertIsNotNone(client._synthesize_lock)

    async def test_check_is_read_only_and_does_not_start_manager(self):
        class FakeManager:
            def __init__(self):
                self.ensure_calls = 0

            async def ensure_running(self):
                self.ensure_calls += 1
                return True, "ready"

        manager = FakeManager()
        client = IndexTTSClient("http://127.0.0.1:7860", "missing.wav", 5, process_manager=manager)
        ok, _detail = await client.check()
        self.assertFalse(ok)
        self.assertEqual(manager.ensure_calls, 0)


