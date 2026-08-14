import unittest

from plugins.mai_companion.tts_process_manager import IndexTTSProcessManager


class FakeProcess:
    def __init__(self, pid=1234):
        self.pid = pid
        self.terminated = 0
        self.killed = 0
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = 0

    def kill(self):
        self.killed += 1
        self.returncode = 1


class ProcessManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_existing_service_is_reused_and_never_terminated(self):
        starts = []

        async def health():
            return True, "online"

        async def start():
            starts.append(True)
            return FakeProcess()

        manager = IndexTTSProcessManager(health_check=health, start_process=start, auto_manage=True, start_timeout_seconds=1, idle_seconds=0)
        ok, detail = await manager.ensure_running()
        await manager.close_if_idle(now=10**9)
        await manager.close()
        self.assertTrue(ok)
        self.assertEqual(detail, "online")
        self.assertEqual(starts, [])

    async def test_unhealthy_service_starts_once_and_waits_until_healthy(self):
        states = iter([(False, "offline"), (False, "starting"), (True, "ready")])
        starts = []

        async def health():
            return next(states)

        async def start():
            process = FakeProcess()
            starts.append(process)
            return process

        manager = IndexTTSProcessManager(health_check=health, start_process=start, auto_manage=True, start_timeout_seconds=1, poll_interval_seconds=0)
        ok, detail = await manager.ensure_running()
        await manager.close()
        self.assertTrue(ok)
        self.assertEqual(detail, "ready")
        self.assertEqual(len(starts), 1)

    async def test_auto_manage_false_never_starts(self):
        starts = []

        async def health():
            return False, "offline"

        async def start():
            starts.append(True)
            return FakeProcess()

        manager = IndexTTSProcessManager(health_check=health, start_process=start, auto_manage=False, start_timeout_seconds=0.01)
        ok, detail = await manager.ensure_running()
        await manager.close()
        self.assertFalse(ok)
        self.assertEqual(detail, "offline")
        self.assertEqual(starts, [])

    async def test_owned_process_is_closed_after_idle_deadline(self):
        process = FakeProcess()

        async def health():
            return False, "offline"

        async def start():
            return process

        manager = IndexTTSProcessManager(health_check=health, start_process=start, auto_manage=True, start_timeout_seconds=0.01, idle_seconds=300)
        manager._process = process
        manager._owned = True
        manager._last_activity = 100
        await manager.close_if_idle(now=401)
        self.assertEqual(process.terminated, 1)
        await manager.close()


if __name__ == "__main__":
    unittest.main()


