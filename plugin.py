from typing import Any

from maibot_sdk import Command, HookHandler, MaiBotPlugin
from maibot_sdk.types import ErrorPolicy, HookMode

from .config import MaiCompanionConfig
from .indextts_client import IndexTTSClient
from .runner import CompanionRunner
from .voice_reply import VoiceReplyTransformer


class MaiCompanionPlugin(MaiBotPlugin):
    config_model = MaiCompanionConfig

    def __init__(self) -> None:
        super().__init__()
        self.personality = ""
        self.reply_style = ""
        self.runner: CompanionRunner | None = None
        self.voice_reply_transformer: VoiceReplyTransformer | None = None

    def _build_voice_reply_transformer(self) -> VoiceReplyTransformer | None:
        if not self.config.voice_reply_enabled:
            return None
        tts_client = self.runner.tts if self.runner is not None else None
        if tts_client is None:
            tts_client = IndexTTSClient(
                self.config.tts_url,
                self.config.reference_audio_path,
                self.config.tts_timeout_seconds,
                self.config.tts_duration_factor,
            )
        return VoiceReplyTransformer(self.config, tts_client)

    async def on_load(self) -> None:
        personality = await self.ctx.config.get("personality", "fail")
        if isinstance(personality, dict):
            self.personality = str(personality.get("personality", ""))
            self.reply_style = str(personality.get("reply_style", ""))
        self.runner = CompanionRunner(self)
        self.voice_reply_transformer = self._build_voice_reply_transformer()
        await self.runner.start()

    async def on_unload(self) -> None:
        if self.runner:
            await self.runner.stop()

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        del scope, config_data, version
        if self.runner:
            await self.runner.stop()
            self.runner = CompanionRunner(self)
            self.voice_reply_transformer = self._build_voice_reply_transformer()
            await self.runner.start()

    @HookHandler(
        "send_service.outbound_transform",
        mode=HookMode.BLOCKING,
        timeout_ms=120_000,
        error_policy=ErrorPolicy.SKIP,
    )
    async def handle_voice_reply_transform(self, **kwargs: Any):
        if self.voice_reply_transformer is None:
            return {
                "action": "continue",
                "modified_kwargs": {"message": kwargs.get("message")},
            }
        return await self.voice_reply_transformer.transform_hook(**kwargs)

    @Command("companion_test", pattern=r"^/companion_test$")
    async def handle_companion_test(self, **kwargs: Any):
        """运行只读健康检查并把结果回复到发起命令的聊天流。"""
        stream_id = str(kwargs.get("stream_id", "")).strip()
        if not self.runner:
            message = "陪伴插件尚未完成初始化"
        else:
            status = await self.runner.diagnostic()
            yes_no = lambda value: "成功" if value else "失败"
            maizone_status = "成功" if status["maizone"] else ("接口成功但暂无动态" if status.get("maizone_no_data") else "失败")
            message = (
                "陪伴插件只读测试结果：\n"
                f"联网话题：{yes_no(status['internet'])}\n"
                f"Maizone QQ空间：{maizone_status}（读取 {status.get('qzone_count', 0)} 条）\n"
                f"IndexTTS 语音：{yes_no(status['tts'])}\n"
                f"回复模型任务 {status.get('model_name', self.config.text_model)}：{yes_no(status['model'])}\n"
                f"目标私聊流：{yes_no(status['private_chat'])}\n"
                "消息发送：未执行"
            )
            if status.get("model_error"):
                message += f"\n模型探测原因：{status['model_error']}"
            elif status.get("model_probe"):
                message += f"\n模型探测回复：{status['model_probe']}"
            if status.get("tts_error"):
                message += f"\n语音探测原因：{status['tts_error']}"
        if stream_id:
            await self.ctx.send.text(message, stream_id)
        return True, message, 2

    @Command("companion_now", pattern=r"^/companion_now$")
    async def handle_companion_now(self, **kwargs: Any):
        """立即触发一条主动陪伴消息，语音失败时由运行器回退文字。"""
        stream_id = str(kwargs.get("stream_id", "")).strip()
        if not self.runner:
            message = "陪伴插件尚未完成初始化"
        else:
            ok = self.runner.trigger_now()
            message = "已开始生成陪伴语音，请稍等片刻" if ok else "已有一条陪伴消息正在生成，请稍等"
        if stream_id:
            await self.ctx.send.text(message, stream_id)
        return True, message, 2


def create_plugin() -> MaiCompanionPlugin:
    return MaiCompanionPlugin()
