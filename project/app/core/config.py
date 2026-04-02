import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="video-x-bot", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_ids: list[int] = Field(default_factory=list, alias="TELEGRAM_ALLOWED_USER_IDS")
    telegram_webhook_url: str = Field(default="", alias="TELEGRAM_WEBHOOK_URL")

    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")

    x_api_key: str = Field(default="", alias="X_API_KEY")
    x_api_key_secret: str = Field(default="", alias="X_API_KEY_SECRET")
    x_access_token: str = Field(default="", alias="X_ACCESS_TOKEN")
    x_access_token_secret: str = Field(default="", alias="X_ACCESS_TOKEN_SECRET")
    x_bearer_token: str = Field(default="", alias="X_BEARER_TOKEN")

    database_url: str = Field(default="sqlite:///./storage/app.db", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    storage_root: str = Field(default="./storage", alias="STORAGE_ROOT")
    raw_video_dir: str = Field(default="./storage/raw", alias="RAW_VIDEO_DIR")
    audio_dir: str = Field(default="./storage/audio", alias="AUDIO_DIR")
    transcript_dir: str = Field(default="./storage/transcript", alias="TRANSCRIPT_DIR")
    subtitle_dir: str = Field(default="./storage/subtitle", alias="SUBTITLE_DIR")
    output_video_dir: str = Field(default="./storage/output", alias="OUTPUT_VIDEO_DIR")
    log_dir: str = Field(default="./storage/logs", alias="LOG_DIR")

    enable_burned_subtitle: bool = Field(default=True, alias="ENABLE_BURNED_SUBTITLE")
    enable_auto_translate_to_en: bool = Field(default=True, alias="ENABLE_AUTO_TRANSLATE_TO_EN")
    enable_send_preview_to_telegram: bool = Field(default=True, alias="ENABLE_SEND_PREVIEW_TO_TELEGRAM")
    require_approval_before_post: bool = Field(default=True, alias="REQUIRE_APPROVAL_BEFORE_POST")
    enable_auto_post: bool = Field(default=False, alias="ENABLE_AUTO_POST")

    ffmpeg_bin: str = Field(default="ffmpeg", alias="FFMPEG_BIN")
    ffprobe_bin: str = Field(default="ffprobe", alias="FFPROBE_BIN")
    ytdlp_bin: str = Field(default="yt-dlp", alias="YTDLP_BIN")
    ytdlp_cookie_file: str = Field(default="", alias="YTDLP_COOKIE_FILE")
    ytdlp_cookies_from_browser: str = Field(default="", alias="YTDLP_COOKIES_FROM_BROWSER")
    ytdlp_browser_profile: str = Field(default="", alias="YTDLP_BROWSER_PROFILE")
    instagram_cookie_header: str = Field(default="", alias="INSTAGRAM_COOKIE_HEADER")
    facebook_cookie_header: str = Field(default="", alias="FACEBOOK_COOKIE_HEADER")

    max_video_duration_seconds: int = Field(default=300, alias="MAX_VIDEO_DURATION_SECONDS")
    max_video_file_size_mb: int = Field(default=200, alias="MAX_VIDEO_FILE_SIZE_MB")
    download_timeout_seconds: int = Field(default=180, alias="DOWNLOAD_TIMEOUT_SECONDS")

    default_caption_style: str = Field(default="public_clean", alias="DEFAULT_CAPTION_STYLE")
    default_output_language: str = Field(default="en", alias="DEFAULT_OUTPUT_LANGUAGE")
    default_profile_code: str = Field(default="A1", alias="DEFAULT_PROFILE_CODE")
    profile_timezone: str = Field(default="UTC", alias="PROFILE_TIMEZONE")
    caption_profiles_json: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: default_caption_profiles(), alias="CAPTION_PROFILES_JSON"
    )
    profile_hourly_map: list[str] = Field(
        default_factory=lambda: default_profile_hourly_map(), alias="PROFILE_HOURLY_MAP"
    )

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_telegram_ids(cls, value):
        if isinstance(value, list):
            return value
        if not value:
            return []
        return [int(item.strip()) for item in str(value).split(",") if item.strip()]

    @field_validator("caption_profiles_json", mode="before")
    @classmethod
    def parse_caption_profiles(cls, value):
        if isinstance(value, dict):
            return value
        if not value:
            return default_caption_profiles()
        return json.loads(value)

    @field_validator("profile_hourly_map", mode="before")
    @classmethod
    def parse_profile_hourly_map(cls, value):
        if isinstance(value, list):
            return value
        if not value:
            return default_profile_hourly_map()
        parsed = [item.strip() for item in str(value).split(",") if item.strip()]
        if len(parsed) != 24:
            raise ValueError("PROFILE_HOURLY_MAP must contain exactly 24 comma-separated profile codes.")
        return parsed

    @field_validator(
        "storage_root",
        "raw_video_dir",
        "audio_dir",
        "transcript_dir",
        "subtitle_dir",
        "output_video_dir",
        "log_dir",
        mode="after",
    )
    @classmethod
    def normalize_paths(cls, value: str) -> str:
        return str(Path(value))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    for path in [
        settings.storage_root,
        settings.raw_video_dir,
        settings.audio_dir,
        settings.transcript_dir,
        settings.subtitle_dir,
        settings.output_video_dir,
        settings.log_dir,
    ]:
        Path(path).mkdir(parents=True, exist_ok=True)
    return settings


def default_caption_profiles() -> dict[str, dict[str, Any]]:
    return {
        "A1": {"language": "en", "language_name": "English", "style": "public_clean", "tone": "clean, safe, concise"},
        "A2": {"language": "ja", "language_name": "Japanese", "style": "public_clean", "tone": "polite, concise"},
        "A3": {"language": "ko", "language_name": "Korean", "style": "public_clean", "tone": "natural, concise, social-safe"},
        "A4": {"language": "zh", "language_name": "Chinese", "style": "public_clean", "tone": "clear, concise, public-safe"},
    }


def default_profile_hourly_map() -> list[str]:
    return [
        "A1", "A1", "A1", "A1", "A2", "A2",
        "A2", "A2", "A3", "A3", "A3", "A3",
        "A4", "A4", "A4", "A4", "A1", "A1",
        "A1", "A2", "A2", "A3", "A4", "A4",
    ]
