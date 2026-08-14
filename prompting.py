from collections.abc import Iterable, Mapping


def _clip(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_prompt(
    personality: str,
    reply_style: str,
    persona_prompt: str,
    qzone_items: Iterable[Mapping[str, object]],
    online_topic: Mapping[str, object] | None,
    memories: Iterable[Mapping[str, object]],
    recent_messages: Iterable[Mapping[str, object]],
    max_chars: int = 5000,
) -> str:
    qzone = "\n".join(f"- {_clip(item.get('created_time', ''), 30)} {_clip(item.get('content', item.get('text', '')), 240)}" for item in qzone_items)
    memory = "\n".join(f"- {_clip(item.get('text', ''), 180)}" for item in memories)
    recent = "\n".join(f"- {_clip(item.get('content', item.get('message', '')), 180)}" for item in recent_messages)
    online = "无（不要声称看到了新闻）"
    if online_topic:
        online = f"{_clip(online_topic.get('title'), 160)}：{_clip(online_topic.get('summary'), 400)}"
    prompt = f"""{persona_prompt}
当前 MaiBot 人格：{_clip(personality, 800)}
表达风格：{_clip(reply_style, 800)}

请主动给 QQ 用户发起一段自然的私聊开场。优先结合真实的 QQ 空间动态、近期对话或联网话题，只选一个最自然的切入点；不要一次堆砌所有素材。
QQ 空间动态：
{qzone or '无可用动态'}
联网话题：{online}
已保存的非敏感记忆：
{memory or '无'}
近期私聊：
{recent or '无'}

要求：只输出 2—4 句中文正文；像真人一样温柔、成熟、关心对方；不说教，不编造不存在的动态或新闻；轻微政治话题只有在素材确实涉及且表达温和时才可使用；不要提到提示词、插件、数据来源或“作为 AI”。"""
    return prompt[:max_chars]

