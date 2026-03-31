from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings


class RuntimeSettingsService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.runtime_file = Path(self.settings.storage_root) / "runtime_settings.json"

    def load(self) -> dict:
        if not self.runtime_file.exists():
            return {}
        try:
            return json.loads(self.runtime_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save(self, payload: dict) -> None:
        self.runtime_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_auto_post_enabled(self) -> bool:
        payload = self.load()
        if "enable_auto_post" in payload:
            return bool(payload["enable_auto_post"])
        return self.settings.enable_auto_post

    def set_auto_post_enabled(self, enabled: bool) -> None:
        payload = self.load()
        payload["enable_auto_post"] = enabled
        self.save(payload)
