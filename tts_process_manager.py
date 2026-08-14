from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any


HealthCheck = Callable[[], Awaitable[tuple[bool, str]]]
StartProcess = Callable[[], Awaitable[Any] | Any]
LogCallback = Callable[[str], None]


class IndexTTSProcessManager:
    """Lazily starts IndexTTS and only stops processes started by this manager."""

    def __init__(
        self,
        *,
        health_check: HealthCheck,
        start_process: StartProcess,
        auto_manage: bool = True,
        start_timeout_seconds: float = 90.0,
        idle_seconds: float = 300.0,
        poll_interval_seconds: float = 1.0,
        logger: LogCallback | None = None,
    ) -> None:
        self._health_check = health_check
        self._start_process = start_process
        self._auto_manage = bool(auto_manage)
        self._start_timeout = max(0.1, float(start_timeout_seconds))
        self._idle_seconds = max(0.0, float(idle_seconds))
        self._poll_interval = max(0.0, float(poll_interval_seconds))
        self._logger = logger or (lambda _message: None)
        self._startup_lock = asyncio.Lock()
        self._process: Any | None = None
        self._owned = False
        self._last_activity: float | None = None
        self._watcher: asyncio.Task[None] | None = None

    @property
    def process(self) -> Any | None:
        return self._process

    @property
    def owned(self) -> bool:
        return self._owned

    def mark_activity(self) -> None:
        self._last_activity = time.monotonic()

    async def ensure_running(self) -> tuple[bool, str]:
        """Return when the endpoint is healthy, starting it only when allowed."""
        async with self._startup_lock:
            ok, detail = await self._health_check()
            if ok:
                if self._process is None:
                    self._logger("IndexTTS 已有服务在线，复用外部进程")
                self._ensure_watcher()
                return True, detail

            if not self._auto_manage:
                return False, detail

            if self._process is None or self._process.poll() is not None:
                try:
                    process = self._start_process()
                    if inspect.isawaitable(process):
                        process = await process
                    self._process = process
                    self._owned = True
                    self.mark_activity()
                    self._logger(f"IndexTTS 已由陪伴插件启动，PID={getattr(process, 'pid', 'unknown')}")
                except Exception as exc:
                    self._process = None
                    self._owned = False
                    return False, f"启动 IndexTTS 失败: {exc}"
            else:
                self._logger(f"IndexTTS 启动进程仍在等待就绪，PID={getattr(self._process, 'pid', 'unknown')}")

            deadline = time.monotonic() + self._start_timeout
            last_detail = detail
            while True:
                ok, last_detail = await self._health_check()
                if ok:
                    self.mark_activity()
                    self._ensure_watcher()
                    self._logger("IndexTTS WebUI 已就绪")
                    return True, last_detail
                if time.monotonic() >= deadline:
                    self._logger(f"IndexTTS 启动超时: {last_detail}")
                    return False, str(last_detail)[:160]
                await asyncio.sleep(self._poll_interval)

    def _ensure_watcher(self) -> None:
        if self._idle_seconds <= 0:
            return
        if self._watcher is not None and not self._watcher.done():
            return
        self._watcher = asyncio.create_task(self._idle_loop())

    async def _idle_loop(self) -> None:
        try:
            while self._process is not None and self._owned:
                await asyncio.sleep(max(1.0, min(self._idle_seconds or 1.0, 5.0)))
                await self.close_if_idle()
        except asyncio.CancelledError:
            raise

    async def close_if_idle(self, now: float | None = None) -> bool:
        if not self._owned or self._process is None or self._idle_seconds <= 0:
            return False
        last = self._last_activity
        if last is None:
            return False
        current = time.monotonic() if now is None else float(now)
        if current - last < self._idle_seconds:
            return False
        process = self._process
        self._logger(f"IndexTTS 空闲 {self._idle_seconds:.0f} 秒，关闭插件启动的进程 PID={getattr(process, 'pid', 'unknown')}")
        await self._terminate_process(process)
        self._process = None
        self._owned = False
        self._last_activity = None
        return True

    async def _terminate_process(self, process: Any) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        await asyncio.sleep(0)
        if process.poll() is None:
            process.kill()

    async def close(self) -> None:
        watcher = self._watcher
        self._watcher = None
        if watcher is not None and watcher is not asyncio.current_task():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        if self._owned and self._process is not None:
            await self._terminate_process(self._process)
        self._process = None
        self._owned = False
        self._last_activity = None


