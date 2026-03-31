from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


@dataclass
class CaptionProfile:
    code: str
    language: str
    language_name: str
    style: str
    tone: str


class ProfileSelectorService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def get_active_profile(self, now: datetime | None = None) -> CaptionProfile:
        current = now or datetime.now(ZoneInfo(self.settings.profile_timezone))
        code = self.settings.profile_hourly_map[current.hour]
        return self.get_profile(code)

    def get_profile(self, code: str | None) -> CaptionProfile:
        normalized = (code or self.settings.default_profile_code).upper()
        profiles = self.settings.caption_profiles_json
        payload = profiles.get(normalized) or profiles[self.settings.default_profile_code]
        return CaptionProfile(
            code=normalized,
            language=str(payload["language"]),
            language_name=str(payload["language_name"]),
            style=str(payload["style"]),
            tone=str(payload["tone"]),
        )
