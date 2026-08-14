import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


class StateStore:
    """在插件专属 data_dir 中保存调度、去重和非敏感记忆。"""

    def __init__(self, data_dir: str | Path, retention_days: int = 90) -> None:
        self.path = Path(data_dir) / "companion_state.json"
        self.retention_days = max(1, retention_days)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"date": "", "schedule": [], "sent": [], "topics": [], "memory": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"date": "", "schedule": [], "sent": [], "topics": [], "memory": []}
        for key, default in (("schedule", []), ("sent", []), ("topics", []), ("memory", [])):
            if not isinstance(data.get(key), list):
                data[key] = default
        return data

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="companion_", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def prune(self, state: dict[str, Any], now: datetime | None = None) -> None:
        cutoff = (now or datetime.now()) - timedelta(days=self.retention_days)
        cutoff_text = cutoff.date().isoformat()
        state["memory"] = [item for item in state.get("memory", []) if str(item.get("date", "")) >= cutoff_text]
        state["topics"] = [item for item in state.get("topics", []) if str(item.get("date", "")) >= cutoff_text]

    def add_memory(self, state: dict[str, Any], text: str, now: datetime | None = None) -> None:
        value = " ".join(str(text).split())[:240]
        if not value:
            return
        state.setdefault("memory", []).append({"date": (now or datetime.now()).date().isoformat(), "text": value})
        self.prune(state, now)

    def remember_topic(self, state: dict[str, Any], topic_hash: str, now: datetime | None = None) -> None:
        state.setdefault("topics", []).append({"date": (now or datetime.now()).date().isoformat(), "hash": topic_hash})
        self.prune(state, now)

