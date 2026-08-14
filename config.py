from maibot_sdk import Field, PluginConfigBase


class PluginSectionConfig(PluginConfigBase):
    """基础插件配置。"""

    enabled: bool = Field(default=True, description="是否启用主动陪伴")
    config_version: str = Field(default="0.1.0", description="配置版本")


class MaiCompanionConfig(PluginConfigBase):
    """年上陪伴主动对话插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig, description="插件基础配置")
    target_qq: str = Field(default="", description="唯一主动私聊目标 QQ；请在本地配置")
    daily_max_messages: int = Field(default=3, description="每天最多主动发送次数")
    quiet_hours: str = Field(default="00:00-09:00", description="免打扰时间段")
    min_gap_minutes: int = Field(default=180, description="主动消息之间的最小间隔分钟数")
    poll_interval_seconds: int = Field(default=45, description="调度轮询间隔秒数")
    feed_count: int = Field(default=5, description="读取的 QQ 空间动态数量")
    text_model: str = Field(default="replyer", description="使用的 MaiBot 文本模型任务名")
    request_timeout_seconds: float = Field(default=8.0, description="联网请求超时秒数")
    news_feeds: list[str] = Field(
        default=[
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://www.solidot.org/index.rss",
        ],
        description="公开 RSS/Atom 话题来源，每行一个 URL",
    )
    weather_location: str = Field(default="", description="天气城市；留空则不请求天气")
    memory_retention_days: int = Field(default=90, description="本地非敏感记忆保留天数")
    max_context_chars: int = Field(default=5000, description="发送给模型的上下文最大字符数")
    save_recent_memory: bool = Field(default=True, description="是否保存近期对话摘要片段")
    voice_enabled: bool = Field(default=True, description="是否优先使用 IndexTTS 发送语音")
    voice_reply_enabled: bool = Field(default=True, description="是否将白名单私聊中的普通回复转换为语音")
    voice_private_whitelist: list[str] = Field(
        default_factory=list,
        description="允许发送语音回复的 QQ 私聊白名单",
    )
    tts_url: str = Field(default="http://127.0.0.1:7860", description="IndexTTS WebUI 地址")
    reference_audio_path: str = Field(default="", description="IndexTTS 参考音频完整路径")
    tts_timeout_seconds: float = Field(default=120.0, description="IndexTTS 请求超时秒数")
    voice_max_chars: int = Field(default=240, description="送入语音生成的最大字符数")
    send_text_on_voice_failure: bool = Field(default=True, description="语音失败时是否回退发送文字")
    tts_duration_factor: float = Field(default=1.0, description="IndexTTS 语速系数")
    tts_auto_manage_process: bool = Field(default=False, description="是否由插件按需管理 IndexTTS 进程")
    tts_process_dir: str = Field(default="", description="IndexTTS 项目目录；请在本地配置")
    tts_python_path: str = Field(default="", description="IndexTTS Python 路径；请在本地配置")
    tts_webui_script: str = Field(default="webui.py", description="IndexTTS WebUI 启动脚本")
    tts_start_timeout_seconds: float = Field(default=90.0, description="IndexTTS 启动健康检查超时")
    tts_idle_shutdown_minutes: int = Field(default=5, description="IndexTTS 空闲自动关闭分钟数")
    persona_prompt: str = Field(
        default=(
            "你是一位成熟温柔、知性体贴的年上大姐姐，像可靠的亲密陪伴者。"
            "你善于倾听和关心，不控制、不说教，偶尔轻轻调侃或撒娇。"
        ),
        description="主动陪伴角色设定",
    )

