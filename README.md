# 结合IndexTTS和Maizone(麦麦空间)的主动发起对话插件

这是一个 MaiBot 插件：结合 Maizone 提供的 QQ 空间动态、公开联网话题和 MaiBot 记忆，为配置的 QQ 私聊目标生成主动陪伴消息。插件只读取 QQ 空间内容，不会发布动态、点赞或评论。

## 安装

在 MaiBot WebUI 的插件管理中使用 GitHub 地址安装：

`https://github.com/yudanpi/mai-companion`

依赖：

- MaiBot 1.1.x 或更高版本
- `internetsb.maizone` 插件（用于读取公开的 QQ 空间动态）
- Python 包 `httpx`
- 可选：本地 IndexTTS WebUI（用于语音回复）

## 配置

插件安装后，在插件配置中填写自己的目标 QQ 号和语音白名单。下面的值只是示例，请勿直接照抄：

```toml
target_qq = "你的QQ号"
voice_private_whitelist = ["你的QQ号"]
voice_enabled = true
voice_reply_enabled = true
reference_audio_path = "D:/voices/companion.wav"
```

如果要让插件自动按需启动和空闲关闭 IndexTTS，可以配置：

```toml
tts_auto_manage_process = true
tts_process_dir = "D:/IndexTTS/index-tts"
tts_python_path = "D:/IndexTTS/index-tts/.venv/Scripts/python.exe"
tts_webui_script = "webui.py"
tts_start_timeout_seconds = 90.0
tts_idle_shutdown_minutes = 5
```

插件只会关闭由它自己启动的 IndexTTS 进程；如果 WebUI 已经由用户手动启动，插件会复用它，不会主动关闭。

## 使用

- `companion_now`：立即生成并发送一次陪伴消息。
- `companion_test`：只读测试联网话题、Maizone、模型、语音和目标私聊流，不发送消息。
- 默认每天最多主动发送 3 次，00:00–09:00 静默；可在配置中调整。
- 语音生成成功时优先发送语音；语音失败时回退为文字。
- 如果不会配置丢给ai就行了（大雾）

## 开发

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```
