from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import logging
from typing import Any, Iterable


logger = logging.getLogger("mai_companion.voice_reply")


def _config_value(config: Any, name: str, default: Any) -> Any:
    value = getattr(config, name, default)
    return default if value is None else value


def _whitelist(config: Any) -> set[str]:
    raw = _config_value(config, "voice_private_whitelist", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Iterable):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def _text_component(message: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    raw_message = message.get("raw_message")
    if not isinstance(raw_message, list) or len(raw_message) != 1:
        return None
    component = raw_message[0]
    if not isinstance(component, dict) or str(component.get("type") or "").strip().lower() != "text":
        return None
    text = str(component.get("data") or "").strip()
    if not text:
        return None
    return text, component


def should_transform(message: dict[str, Any], source_kind: str, config: Any) -> bool:
    """Return whether a serialized outbound message is eligible for voice conversion."""

    if not bool(_config_value(config, "voice_reply_enabled", False)):
        return False
    if str(source_kind or "").strip() != "guided_reply":
        return False
    if str(message.get("platform") or "").strip().lower() != "qq":
        return False
    if message.get("is_command"):
        return False

    info = message.get("message_info")
    if not isinstance(info, dict) or info.get("group_info") is not None:
        return False
    additional_config = info.get("additional_config")
    if not isinstance(additional_config, dict):
        return False
    if additional_config.get("mai_voice_transformed"):
        return False
    target_user_id = str(additional_config.get("platform_io_target_user_id") or "").strip()
    if not target_user_id or target_user_id not in _whitelist(config):
        return False

    text_data = _text_component(message)
    if text_data is None:
        return False
    text, _ = text_data
    max_chars = int(_config_value(config, "voice_max_chars", 0) or 0)
    return max_chars <= 0 or len(text) <= max_chars


def replace_with_voice(message: dict[str, Any], audio_base64: str) -> dict[str, Any]:
    """Return a copy of message containing one serialized VoiceComponent."""

    audio_bytes = base64.b64decode(audio_base64, validate=True)
    if not audio_bytes:
        raise ValueError("IndexTTS 返回空音频")

    result = copy.deepcopy(message)
    info = result.setdefault("message_info", {})
    additional_config = info.setdefault("additional_config", {})
    additional_config["mai_voice_transformed"] = True
    result["raw_message"] = [
        {
            "type": "voice",
            "data": "",
            "hash": hashlib.sha256(audio_bytes).hexdigest(),
            "binary_data_base64": audio_base64,
        }
    ]
    result["is_emoji"] = False
    result["is_picture"] = False
    result["is_command"] = False
    return result


class VoiceReplyTransformer:
    def __init__(self, config: Any, tts_client: Any) -> None:
        self.config = config
        self.tts_client = tts_client
        self._tts_lock = asyncio.Lock()

    @staticmethod
    def _audio_base64(result: Any) -> str:
        if isinstance(result, dict):
            return str(result.get("audio_base64") or "").strip()
        return str(getattr(result, "audio_base64", "") or "").strip()

    async def transform_hook(self, **kwargs: Any) -> dict[str, Any]:
        message = kwargs.get("message")
        if not isinstance(message, dict):
            return {"action": "continue", "modified_kwargs": {"message": message}}

        source_kind = str(kwargs.get("maisaka_source_kind") or "")
        if not should_transform(message, source_kind, self.config):
            return {"action": "continue", "modified_kwargs": {"message": message}}

        text_data = _text_component(message)
        if text_data is None:
            return {"action": "continue", "modified_kwargs": {"message": message}}
        text, _ = text_data

        try:
            async with self._tts_lock:
                timeout_seconds = float(_config_value(self.config, "tts_timeout_seconds", 0.0) or 0.0)
                last_error: Exception | None = None
                for attempt in range(2):
                    try:
                        synthesis = self.tts_client.synthesize(text)
                        result = (
                            await asyncio.wait_for(synthesis, timeout=timeout_seconds)
                            if timeout_seconds > 0
                            else await synthesis
                        )
                        audio_base64 = self._audio_base64(result)
                        transformed = replace_with_voice(message, audio_base64)
                        break
                    except Exception as exc:
                        last_error = exc
                        if attempt == 0:
                            reset_cache = getattr(self.tts_client, "reset_reference_cache", None)
                            if callable(reset_cache):
                                reset_cache()
                            await asyncio.sleep(0)
                        else:
                            raise
                else:
                    raise last_error or RuntimeError("IndexTTS 语音生成失败")
        except Exception as exc:
            logger.warning("普通回复语音生成失败，回退文字: %s", exc)
            return {"action": "continue", "modified_kwargs": {"message": message}}

        return {"action": "continue", "modified_kwargs": {"message": transformed}}
