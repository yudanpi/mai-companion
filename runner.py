import asyncio
import hashlib
import os
import random
import subprocess
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any

from .context_sources import get_online_topic, get_qzone_context
from .indextts_client import IndexTTSClient
from .prompting import build_prompt
from .scheduler import generate_daily_schedule, is_quiet_time
from .storage import StateStore
from .tts_process_manager import IndexTTSProcessManager


def is_model_available(models: Any, task_name: str) -> bool:
    """Return whether a task name is available in model data."""
    if isinstance(models, dict):
        models = models.get("models", [])
    return task_name in models if isinstance(models, (list, tuple, set)) else False


async def get_recent_messages(message_capability: Any, stream_id: str, limit: int = 20) -> Any:
    """Read recent messages using the current MaiBot SDK signature."""
    return await message_capability.get_recent(chat_id=stream_id, limit=limit)


class CompanionRunner:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.ctx = plugin.ctx
        self.config = plugin.config
        self.store = StateStore(self.ctx.paths.data_dir, self.config.memory_retention_days)
        self.task: asyncio.Task[None] | None = None
        self.running = False
        self.tts = self._build_tts_client() if self.config.voice_enabled else None
        self._tts_lock = asyncio.Lock()
        self._manual_tasks: set[asyncio.Task[Any]] = set()

    def _build_tts_client(self) -> IndexTTSClient:
        client = IndexTTSClient(
            self.config.tts_url,
            self.config.reference_audio_path,
            self.config.tts_timeout_seconds,
            self.config.tts_duration_factor,
        )
        if not getattr(self.config, "tts_auto_manage_process", True):
            return client
        manager = IndexTTSProcessManager(
            health_check=client.check,
            start_process=self._start_tts_process,
            auto_manage=True,
            start_timeout_seconds=getattr(self.config, "tts_start_timeout_seconds", 90.0),
            idle_seconds=max(0.0, float(getattr(self.config, "tts_idle_shutdown_minutes", 5)) * 60.0),
            logger=lambda message: self.ctx.logger.info("%s", message),
        )
        client.process_manager = manager
        return client

    def _start_tts_process(self) -> subprocess.Popen[Any]:
        process_dir_value = str(getattr(self.config, "tts_process_dir", "")).strip()
        python_value = str(getattr(self.config, "tts_python_path", "")).strip()
        if not process_dir_value or not python_value:
            raise FileNotFoundError("请先配置 IndexTTS 项目目录和 Python 路径")
        process_dir = Path(process_dir_value).expanduser()
        python_path = Path(python_value)
        if not python_path.is_absolute():
            python_path = process_dir / python_path
        script = Path(getattr(self.config, "tts_webui_script", "webui.py"))
        if not script.is_absolute():
            script = process_dir / script
        if not process_dir.is_dir():
            raise FileNotFoundError(f"IndexTTS project directory does not exist: {process_dir}")
        if not python_path.is_file():
            raise FileNotFoundError(f"IndexTTS Python does not exist: {python_path}")
        if not script.is_file():
            raise FileNotFoundError(f"IndexTTS WebUI script does not exist: {script}")
        stdout_path = process_dir / "webui-start.log"
        stderr_path = process_dir / "webui-start.err.log"
        stdout = stdout_path.open("a", encoding="utf-8")
        stderr = stderr_path.open("a", encoding="utf-8")
        try:
            # IndexTTS is a local Gradio service. MaiBot may inherit a proxy
            # environment used for external requests; Gradio's localhost
            # startup check must bypass it or it can fail with HTTP 502.
            env = os.environ.copy()
            for key in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                env.pop(key, None)
            env["NO_PROXY"] = "127.0.0.1,localhost"
            env["no_proxy"] = "127.0.0.1,localhost"
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                [str(python_path), "-u", str(script), "--host", "127.0.0.1"],
                cwd=str(process_dir),
                stdout=stdout,
                stderr=stderr,
                env=env,
                creationflags=flags,
            )
            stdout.close()
            stderr.close()
            return process
        except Exception:
            stdout.close()
            stderr.close()
            raise
    async def diagnostic(self) -> dict[str, Any]:
        """Run read-only diagnostics without sending a message."""
        result: dict[str, Any] = {
            "internet": False,
            "maizone": False,
            "model": False,
            "private_chat": False,
            "tts": False,
            "sent_message": False,
        }
        if self.config.voice_enabled and self.tts is not None:
            try:
                tts_ok, tts_detail = await self.tts.check()
                result["tts"] = bool(tts_ok)
                if not tts_ok:
                    result["tts_error"] = str(tts_detail)[:160]
            except Exception as exc:
                result["tts_error"] = str(exc)[:160]
        else:
            result["tts_error"] = "Voice is disabled"
        try:
            topic = await get_online_topic(
                self.config.news_feeds,
                self.config.weather_location,
                self.config.request_timeout_seconds,
            )
            result["internet"] = topic is not None
            if topic:
                result["internet_title"] = str(topic.get("title", ""))[:80]
        except Exception as exc:
            result["internet_error"] = str(exc)[:160]
        try:
            qzone = await self.ctx.api.call(
                "internetsb.maizone.get_feeds_list_api",
                target_qq=self.config.target_qq,
                num=1,
                filter=False,
            )
            result["maizone"] = isinstance(qzone, dict) and bool(qzone.get("result"))
            result["maizone_api"] = isinstance(qzone, dict) and "result" in qzone
            result["qzone_count"] = len(qzone.get("data", [])) if isinstance(qzone, dict) and isinstance(qzone.get("data"), list) else 0
            if not result["maizone"] and result["maizone_api"]:
                result["maizone_no_data"] = True
        except Exception as exc:
            result["maizone_error"] = str(exc)[:160]
        try:
            models = await self.ctx.llm.get_available_models()
            result["model_name"] = self.config.text_model
            if isinstance(models, dict):
                result["model_candidates"] = models.get("models", [])
            elif isinstance(models, (list, tuple, set)):
                result["model_candidates"] = list(models)
            # `text_model` is normally a MaiBot task name (for example
            # `replyer`), not one of the concrete model identifiers shown by
            # get_available_models().  Probe the task through the same path
            # used by run_once so the diagnostic reflects real capability.
            # Model calls can legitimately take longer than the short network
            # feed timeout (the configured replyer models average ~20s).
            # Keep this probe long enough to distinguish a slow model from a
            # real failure without changing the production request timeout.
            probe = await asyncio.wait_for(
                self.ctx.llm.generate(
                    "Connection test: reply only OK, no explanation.",
                    model=self.config.text_model,
                ),
                timeout=max(60.0, self.config.request_timeout_seconds),
            )
            probe_text = str(probe.get("response", "")) if isinstance(probe, dict) else str(probe or "")
            result["model"] = bool(probe_text.strip())
            result["model_probe"] = probe_text.strip()[:80]
        except Exception as exc:
            result["model_error"] = str(exc)[:160]
        try:
            result["private_chat"] = await self._target_stream() is not None
        except Exception as exc:
            result["private_chat_error"] = str(exc)[:160]
        return result

    async def start(self) -> None:
        if self.running or not self.config.plugin.enabled:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        self.ctx.logger.info("Companion runner started")

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        manual_tasks = tuple(self._manual_tasks)
        for task in manual_tasks:
            task.cancel()
        if manual_tasks:
            await asyncio.gather(*manual_tasks, return_exceptions=True)
        self._manual_tasks.clear()
        if self.tts is not None:
            await self.tts.close()

    async def run_now(self) -> bool:
        """Generate and send one companion message immediately."""
        return await self.run_once(force=True)

    async def _run_now_background(self) -> None:
        try:
            ok = await self.run_now()
            self.ctx.logger.info("鎵嬪姩闄即娑堟伅鍚庡彴浠诲姟瀹屾垚锛歴uccess=%s", ok)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.ctx.logger.error("鎵嬪姩闄即娑堟伅鍚庡彴浠诲姟澶辫触锛?s", str(exc)[:160], exc_info=True)

    def trigger_now(self) -> bool:
        """Schedule one immediate companion message without blocking the command."""
        if any(not task.done() for task in self._manual_tasks):
            return False
        task = asyncio.create_task(self._run_now_background())
        self._manual_tasks.add(task)
        task.add_done_callback(self._manual_tasks.discard)
        return True

    def _state_for_today(self, now: datetime) -> dict[str, Any]:
        state = self.store.load()
        if state.get("date") != now.date().isoformat():
            times = generate_daily_schedule(
                now.date(), self.config.daily_max_messages, min_gap_minutes=self.config.min_gap_minutes, rng=random.SystemRandom()
            )
            state = {"date": now.date().isoformat(), "schedule": [item.isoformat() for item in times], "sent": [], "topics": state.get("topics", []), "memory": state.get("memory", [])}
            self.store.prune(state, now)
            self.store.save(state)
        return state

    async def _loop(self) -> None:
        while self.running:
            try:
                now = datetime.now()
                state = self._state_for_today(now)
                due = [datetime.fromisoformat(value) for value in state.get("schedule", []) if value not in state.get("sent", []) and datetime.fromisoformat(value) <= now]
                if due and not is_quiet_time(now, self.config.quiet_hours) and len(state.get("sent", [])) < self.config.daily_max_messages:
                    await self.run_once(now, state, due[0].isoformat())
                await asyncio.sleep(max(15, self.config.poll_interval_seconds))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.ctx.logger.error("涓诲姩闄即浠诲姟寮傚父: %s", exc, exc_info=True)
                await asyncio.sleep(60)

    async def _target_stream(self) -> str | None:
        result = await self.ctx.chat.open_session(platform="qq", chat_type="private", user_id=self.config.target_qq)
        if not isinstance(result, dict) or not result.get("success"):
            self.ctx.logger.error("鏃犳硶鎵撳紑鐩爣 QQ 绉佽亰娴? %s", result)
            return None
        stream = result.get("stream") or result
        stream_id = stream.get("stream_id") or stream.get("session_id") if isinstance(stream, dict) else None
        return str(stream_id) if stream_id else None

    async def _send_generated(self, message: str, stream_id: str) -> str:
        """Prefer voice; fall back to one text message on TTS failure."""
        if self.config.voice_enabled and self.tts is not None:
            try:
                voice_text = " ".join(str(message).split())[: max(1, int(self.config.voice_max_chars))]
                async with self._tts_lock:
                    result = await self.tts.synthesize(voice_text)
                if not result.audio_base64:
                    raise RuntimeError("IndexTTS returned empty audio")
                await self.ctx.send.hybrid(
                    [{"type": "voice", "content": result.audio_base64}],
                    stream_id,
                )
                self.ctx.logger.info("IndexTTS voice sent successfully, elapsed=%.2fs", result.elapsed_seconds)
                return "voice"
            except Exception as exc:
                self.ctx.logger.warning("IndexTTS 鐢熸垚澶辫触锛屽洖閫€鏂囧瓧鍙戦€? %s", str(exc)[:160])

        if self.config.send_text_on_voice_failure:
            await self.ctx.send.text(message, stream_id)
            return "text"
        return "none"

    async def run_once(
        self,
        now: datetime | None = None,
        state: dict[str, Any] | None = None,
        slot: str | None = None,
        force: bool = False,
    ) -> bool:
        now = now or datetime.now()
        if not force and is_quiet_time(now, self.config.quiet_hours):
            return False
        state = state or self._state_for_today(now)
        if not force and len(state.get("sent", [])) >= self.config.daily_max_messages:
            return False
        stream_id = await self._target_stream()
        if not stream_id:
            return False
        qzone_items = await get_qzone_context(self.ctx.api, self.config.target_qq, self.config.feed_count)
        online_topic = await get_online_topic(self.config.news_feeds, self.config.weather_location, self.config.request_timeout_seconds)
        recent_result = await get_recent_messages(self.ctx.message, stream_id, limit=20)
        recent_messages = recent_result.get("messages", []) if isinstance(recent_result, dict) else []
        if self.config.save_recent_memory:
            for item in recent_messages[-3:]:
                if isinstance(item, dict):
                    self.store.add_memory(state, str(item.get("content", item.get("message", ""))), now)
        prompt = build_prompt(self.plugin.personality, self.plugin.reply_style, self.config.persona_prompt, qzone_items, online_topic, state.get("memory", [])[-10:], recent_messages[-10:], self.config.max_context_chars)
        generated = await self.ctx.llm.generate(prompt, model=self.config.text_model)
        message = str(generated.get("response", "")).strip() if isinstance(generated, dict) else ""
        if not message:
            self.ctx.logger.error("Companion model returned no usable message")
            return False
        send_mode = await self._send_generated(message, stream_id)
        if send_mode == "none":
            return False
        if not force:
            state.setdefault("sent", []).append(slot or now.isoformat())
        digest = hashlib.sha256((message + str(online_topic)).encode("utf-8")).hexdigest()[:16]
        self.store.remember_topic(state, digest, now)
        self.store.save(state)
        self.ctx.logger.info("Sent companion message to QQ %s", self.config.target_qq)
        return True


