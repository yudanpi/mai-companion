from __future__ import annotations

import asyncio
import base64
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx


@dataclass(frozen=True)
class VoiceResult:
    audio_base64: str
    elapsed_seconds: float


class IndexTTSClient:
    """Small async client for the local IndexTTS Gradio API."""

    def __init__(
        self,
        base_url: str,
        reference_audio_path: str,
        timeout_seconds: float,
        duration_factor: float = 1.0,
        process_manager: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.reference_audio_path = str(reference_audio_path).strip()
        self.timeout_seconds = max(5.0, float(timeout_seconds))
        self.duration_factor = min(2.0, max(0.5, float(duration_factor)))
        self.process_manager = process_manager
        self._synthesize_lock = asyncio.Lock()
        self._uploaded_reference: tuple[str, int, int] | None = None
        self._uploaded_reference_file: dict[str, Any] | None = None

    def reset_reference_cache(self) -> None:
        """Discard the cached Gradio upload after a transient file failure."""
        self._uploaded_reference = None
        self._uploaded_reference_file = None

    def _validate(self) -> Path:
        if not self.reference_audio_path:
            raise FileNotFoundError("IndexTTS reference audio is not configured")
        path = Path(self.reference_audio_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"IndexTTS reference audio does not exist: {path}")
        if path.stat().st_size <= 0:
            raise ValueError("IndexTTS reference audio is empty")
        return path

    @staticmethod
    def _audio_to_base64(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode("ascii")

    @staticmethod
    def _completed_output(payload: dict[str, Any] | list[dict[str, Any]]) -> str:
        if isinstance(payload, list):
            completed = next(
                (
                    item
                    for item in reversed(payload)
                    if isinstance(item, dict) and item.get("msg") == "process_completed"
                ),
                None,
            )
            if completed is None:
                raise ValueError("IndexTTS has not completed")
            payload = completed
        if payload.get("msg") != "process_completed":
            raise ValueError("IndexTTS has not completed")
        if not payload.get("success", True):
            output = payload.get("output")
            raise RuntimeError(str(output or "IndexTTS generation failed"))
        data = (payload.get("output") or {}).get("data", [])
        first = data[0] if isinstance(data, list) and data else data
        if isinstance(first, dict):
            value = first.get("url") or first.get("path")
            if value is None and isinstance(first.get("value"), dict):
                value = first["value"].get("url") or first["value"].get("path")
        else:
            value = first
        if not value:
            raise RuntimeError("IndexTTS returned empty audio")
        return str(value)

    async def _upload_reference(self, client: httpx.AsyncClient, path: Path) -> dict[str, Any]:
        stat = path.stat()
        signature = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        if self._uploaded_reference == signature and self._uploaded_reference_file:
            return self._uploaded_reference_file

        with path.open("rb") as handle:
            response = await client.post(
                urljoin(self.base_url, "gradio_api/upload"),
                files={"files": (path.name, handle, "audio/wav")},
            )
        response.raise_for_status()
        uploaded = response.json()
        if not isinstance(uploaded, list) or not uploaded:
            raise RuntimeError("IndexTTS reference upload failed")
        result = {
            "path": str(uploaded[0]),
            "orig_name": path.name,
            "meta": {"_type": "gradio.FileData"},
        }
        self._uploaded_reference = signature
        self._uploaded_reference_file = result
        return result

    @staticmethod
    def _queue_payload(data: list[Any], session_hash: str) -> dict[str, Any]:
        return {"data": data, "fn_index": 20, "session_hash": session_hash}

    async def _wait_for_result(self, client: httpx.AsyncClient, event_id: str, session_hash: str) -> str:
        endpoint = urljoin(self.base_url, "gradio_api/queue/data")
        async with client.stream("GET", endpoint, params={"session_hash": session_hash}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                payload = json.loads(raw)
                messages = payload if isinstance(payload, list) else [payload]
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    if message.get("event_id") and message.get("event_id") != event_id:
                        continue
                    if message.get("msg") == "process_completed":
                        return self._completed_output(message)
                    if message.get("msg") in {"close_stream", "process_failed"}:
                        raise RuntimeError(str(message.get("output") or "IndexTTS generation failed"))
        raise RuntimeError("IndexTTS event stream ended early")

    async def _read_audio(self, client: httpx.AsyncClient, value: str) -> bytes:
        local_path = Path(value)
        if local_path.is_file():
            return local_path.read_bytes()
        if value.startswith(("http://", "https://", "/")):
            url = value if value.startswith(("http://", "https://")) else urljoin(self.base_url, value.lstrip("/"))
        else:
            url = urljoin(self.base_url, "gradio_api/file=" + quote(value, safe=""))
        response = await client.get(url)
        response.raise_for_status()
        return response.content

    async def synthesize(self, text: str) -> VoiceResult:
        async with self._synthesize_lock:
            if self.process_manager is not None:
                ok, detail = await self.process_manager.ensure_running()
                if not ok:
                    raise RuntimeError(f"IndexTTS is not ready: {detail}")
            result = await self._synthesize_unlocked(text)
            if self.process_manager is not None:
                self.process_manager.mark_activity()
            return result

    async def _synthesize_unlocked(self, text: str) -> VoiceResult:
        path = self._validate()
        text = " ".join(str(text).split()).strip()
        if not text:
            raise ValueError("Cannot synthesize empty text")
        started = time.perf_counter()
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            reference = await self._upload_reference(client, path)
            data = [
                "与音色参考音频相同",
                reference,
                text,
                "ZH",
                reference,
                0.65,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                "",
                False,
                120,
                self.duration_factor,
                True,
                0.8,
                30,
                0.8,
                0.0,
                1,
                10.0,
                600,
            ]
            session_hash = secrets.token_hex(16)
            response = await client.post(
                urljoin(self.base_url, "gradio_api/queue/join"),
                json=self._queue_payload(data, session_hash),
            )
            response.raise_for_status()
            event_id = str(response.json().get("event_id") or "")
            if not event_id:
                raise RuntimeError("IndexTTS returned no event id")
            output_path = await self._wait_for_result(client, event_id, session_hash)
            audio = await self._read_audio(client, output_path)
        if not audio:
            raise RuntimeError("IndexTTS returned empty audio")
        return VoiceResult(base64.b64encode(audio).decode("ascii"), time.perf_counter() - started)

    async def check(self) -> tuple[bool, str]:
        try:
            self._validate()
            timeout = httpx.Timeout(min(self.timeout_seconds, 10.0))
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.get(self.base_url)
                response.raise_for_status()
            return True, "IndexTTS online and reference audio is valid"
        except Exception as exc:
            return False, str(exc)[:160]

    async def close(self) -> None:
        if self.process_manager is not None:
            await self.process_manager.close()

