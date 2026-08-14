import json
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Any

import httpx


async def get_qzone_context(api: Any, target_qq: str, count: int) -> list[dict[str, Any]]:
    result = await api.call(
        "internetsb.maizone.get_feeds_list_api",
        target_qq=target_qq,
        num=count,
        filter=False,
    )
    if not isinstance(result, Mapping) or not result.get("result"):
        return []
    data = result.get("data", [])
    return [item for item in data if isinstance(item, Mapping)]


def _parse_feed(payload: str, url: str) -> dict[str, str] | None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        try:
            raw = json.loads(payload)
        except ValueError:
            return None
        if isinstance(raw, Mapping):
            return {"title": str(raw.get("title", "")), "summary": str(raw.get("summary", raw.get("description", ""))), "link": str(raw.get("link", url)), "source": url}
        return None
    item = root.find(".//item") or root.find(".//entry")
    if item is None:
        return None
    def text(name: str) -> str:
        value = item.findtext(name)
        return " ".join((value or "").split())
    link = text("link") or url
    return {"title": text("title"), "summary": text("description") or text("summary"), "link": link, "source": url}


async def get_online_topic(
    feed_urls: list[str],
    weather_location: str = "",
    timeout_seconds: float = 8.0,
) -> dict[str, str] | None:
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": "MaiCompanion/0.1"}) as client:
        if weather_location.strip():
            weather_url = f"https://wttr.in/{httpx.URL(weather_location.strip()).raw_path.decode()}?format=j1"
            try:
                response = await client.get(weather_url)
                response.raise_for_status()
                weather = response.json()
                current = weather.get("current_condition", [{}])[0]
                description = current.get("weatherDesc", [{}])[0].get("value", "")
                return {"title": f"{weather_location}天气", "summary": f"{description}，气温 {current.get('temp_C', '')}°C", "link": weather_url, "source": "wttr.in"}
            except (httpx.HTTPError, ValueError, IndexError, AttributeError):
                pass
        for url in feed_urls:
            try:
                response = await client.get(url)
                response.raise_for_status()
                topic = _parse_feed(response.text[:1_000_000], url)
                if topic and topic.get("title"):
                    return topic
            except (httpx.HTTPError, ValueError, ET.ParseError):
                continue
    return None

