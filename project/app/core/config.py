import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="video-x-bot", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list, alias="TELEGRAM_ALLOWED_USER_IDS"
    )
    telegram_webhook_url: str = Field(default="", alias="TELEGRAM_WEBHOOK_URL")

    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")

    # ────── GPM Login (browser automation cho post X) ──────
    gpm_api_base: str = Field(default="http://127.0.0.1:19995", alias="GPM_API_BASE")
    gpm_profile_id: str = Field(default="", alias="GPM_PROFILE_ID")
    gpm_close_after_post: bool = Field(default=True, alias="GPM_CLOSE_AFTER_POST")
    gpm_post_timeout_sec: int = Field(default=120, alias="GPM_POST_TIMEOUT_SEC")
    # Redis lock TTL — chỉ 1 publish job được chiếm GPM profile cùng lúc.
    gpm_lock_ttl_sec: int = Field(default=600, alias="GPM_LOCK_TTL_SEC")
    gpm_lock_wait_sec: int = Field(default=900, alias="GPM_LOCK_WAIT_SEC")

    database_url: str = Field(default="sqlite:///./storage/app.db", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    storage_root: str = Field(default="./storage", alias="STORAGE_ROOT")
    raw_video_dir: str = Field(default="./storage/raw", alias="RAW_VIDEO_DIR")
    audio_dir: str = Field(default="./storage/audio", alias="AUDIO_DIR")
    transcript_dir: str = Field(default="./storage/transcript", alias="TRANSCRIPT_DIR")
    subtitle_dir: str = Field(default="./storage/subtitle", alias="SUBTITLE_DIR")
    output_video_dir: str = Field(default="./storage/output", alias="OUTPUT_VIDEO_DIR")
    log_dir: str = Field(default="./storage/logs", alias="LOG_DIR")

    enable_auto_translate_to_en: bool = Field(default=True, alias="ENABLE_AUTO_TRANSLATE_TO_EN")
    enable_send_preview_to_telegram: bool = Field(default=True, alias="ENABLE_SEND_PREVIEW_TO_TELEGRAM")
    require_approval_before_post: bool = Field(default=True, alias="REQUIRE_APPROVAL_BEFORE_POST")
    enable_auto_post: bool = Field(default=False, alias="ENABLE_AUTO_POST")

    # Strip audio gốc + mix nhạc no-copyright cho cả manual /add (giống auto-crawl).
    # Bật để né copyright YT/X. Tắt nếu cần giữ audio gốc (vd: clip nhạc/lyrics).
    strip_audio_for_manual: bool = Field(default=True, alias="STRIP_AUDIO_FOR_MANUAL")

    # ────── Lịch post (3 slot/ngày trong khung 13h-2h sáng VN) ──────
    post_slots_vn: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["14:00", "19:00", "01:00"], alias="POST_SLOTS_VN"
    )
    # Retention (cleanup task)
    retention_days_posted: int = Field(default=7, alias="RETENTION_DAYS_POSTED")
    retention_days_failed: int = Field(default=14, alias="RETENTION_DAYS_FAILED")
    storage_max_gb: float = Field(default=20.0, alias="STORAGE_MAX_GB")

    # ────── Content Laundering (anti-fingerprint) ──────
    # Phá Visual Hash + Audio Fingerprint; output luôn 9:16 1080×1920.
    enable_launder: bool = Field(default=True, alias="ENABLE_LAUNDER")
    launder_target_w: int = Field(default=1080, alias="LAUNDER_TARGET_W")
    launder_target_h: int = Field(default=1920, alias="LAUNDER_TARGET_H")
    launder_blur_strength: int = Field(default=25, alias="LAUNDER_BLUR_STRENGTH")
    launder_blur_passes: int = Field(default=5, alias="LAUNDER_BLUR_PASSES")
    launder_fg_scale_portrait: float = Field(default=0.90, alias="LAUNDER_FG_SCALE_PORTRAIT")
    launder_landscape_threshold: float = Field(default=1.3, alias="LAUNDER_LANDSCAPE_THRESHOLD")
    launder_pitch_shift: float = Field(default=1.04, alias="LAUNDER_PITCH_SHIFT")
    launder_total_tempo: float = Field(default=1.15, alias="LAUNDER_TOTAL_TEMPO")
    launder_eq_freq: int = Field(default=1500, alias="LAUNDER_EQ_FREQ")
    launder_eq_gain: float = Field(default=-2.0, alias="LAUNDER_EQ_GAIN")
    launder_eq_width: float = Field(default=1.0, alias="LAUNDER_EQ_WIDTH")
    launder_echo_in_gain: float = Field(default=0.8, alias="LAUNDER_ECHO_IN_GAIN")
    launder_echo_out_gain: float = Field(default=0.9, alias="LAUNDER_ECHO_OUT_GAIN")
    launder_echo_delay_ms: int = Field(default=40, alias="LAUNDER_ECHO_DELAY_MS")
    launder_echo_decay: float = Field(default=0.10, alias="LAUNDER_ECHO_DECAY")
    launder_noise_path: str = Field(default="assets/noise/rain.mp3", alias="LAUNDER_NOISE_PATH")
    launder_noise_volume: float = Field(default=0.15, alias="LAUNDER_NOISE_VOLUME")
    launder_crf: int = Field(default=24, alias="LAUNDER_CRF")
    launder_maxrate_kbps: int = Field(default=8000, alias="LAUNDER_MAXRATE_KBPS")
    launder_preset: str = Field(default="medium", alias="LAUNDER_PRESET")

    # Overlay: watermark + title
    launder_font_path: str = Field(
        default="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        alias="LAUNDER_FONT_PATH",
    )
    launder_watermark_text: str = Field(default="@WBteamz", alias="LAUNDER_WATERMARK_TEXT")
    launder_watermark_opacity: float = Field(default=0.55, alias="LAUNDER_WATERMARK_OPACITY")
    launder_title_max_words: int = Field(default=10, alias="LAUNDER_TITLE_MAX_WORDS")
    launder_title_max_chars: int = Field(default=22, alias="LAUNDER_TITLE_MAX_CHARS")
    # Cắt N giây cuối output để bỏ end-card watermark của creator gốc.
    # 0 = không trim. Tính SAU khi tempo speedup, nên 3s ở đây = 3s thực ở output.
    launder_trim_end_sec: float = Field(default=0.0, alias="LAUNDER_TRIM_END_SEC")

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
    profile_timezone: str = Field(default="Asia/Ho_Chi_Minh", alias="PROFILE_TIMEZONE")

    # ────── Auto-crawl (TikTok + YouTube, silent content) ──────
    auto_crawl_enabled: bool = Field(default=False, alias="AUTO_CRAWL_ENABLED")
    crawl_max_candidates: int = Field(default=50, alias="CRAWL_MAX_CANDIDATES")
    crawl_min_duration_sec: int = Field(default=10, alias="CRAWL_MIN_DURATION_SEC")
    crawl_max_duration_sec: int = Field(default=60, alias="CRAWL_MAX_DURATION_SEC")

    tiktok_hashtag_urls: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "https://www.tiktok.com/tag/anime",
            "https://www.tiktok.com/tag/animeedit",
            "https://www.tiktok.com/tag/lifehack",
            "https://www.tiktok.com/tag/oddlysatisfying",
        ],
        alias="TIKTOK_HASHTAG_URLS",
    )
    tiktok_cookie_header: str = Field(default="", alias="TIKTOK_COOKIE_HEADER")

    youtube_search_queries: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "anime edit shorts no subtitle",
            "anime amv shorts raw",
            "life hack shorts no talking",
            "oddly satisfying shorts no sub",
        ],
        alias="YOUTUBE_SEARCH_QUERIES",
    )
    youtube_hashtag_urls: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="YOUTUBE_HASHTAG_URLS"
    )
    # Loại uploader/channel khỏi crawl YT — tránh self-reupload loop.
    youtube_exclude_uploaders: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="YOUTUBE_EXCLUDE_UPLOADERS"
    )

    silent_keywords_positive: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "anime", "animation", "amv", "anime edit", "manga", "aesthetic",
            "life hack", "lifehack", "hack", "kitchen hack", "diy",
            "satisfying", "oddly satisfying", "clever", "trick", "smart hack",
            "no sub", "no subtitle", "no subs", "raw", "clean",
            "no voice", "no talking", "no dialogue", "silent",
        ],
        alias="SILENT_KEYWORDS_POSITIVE",
    )
    silent_keywords_negative: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            # Subtitle indicators (từ chối content có sub bất kỳ ngôn ngữ nào)
            "subtitle", "subtitles", "subs", "vietsub", "engsub", "eng sub",
            "sub indo", "sub español", "esp sub", "kor sub", "jp sub",
            "字幕", "中字", "中文字幕", "翻译", "dubbed", "dub", "fandub",
            # Talking-format content
            "tutorial", "vlog", "reaction", "review", "interview", "podcast",
            "explained", "commentary", "storytime", "rant",
        ],
        alias="SILENT_KEYWORDS_NEGATIVE",
    )

    # ────── Audio Replacer (xóa audio gốc + mix nhạc No-Copyright) ──────
    audio_replace_enabled: bool = Field(default=True, alias="AUDIO_REPLACE_ENABLED")
    music_library_dir: str = Field(default="./assets/music", alias="MUSIC_LIBRARY_DIR")
    music_default_mood: str = Field(default="cinematic", alias="MUSIC_DEFAULT_MOOD")
    music_volume: float = Field(default=0.85, alias="MUSIC_VOLUME")
    music_fade_in_sec: float = Field(default=1.0, alias="MUSIC_FADE_IN_SEC")
    music_fade_out_sec: float = Field(default=1.5, alias="MUSIC_FADE_OUT_SEC")
    music_loop_if_shorter: bool = Field(default=True, alias="MUSIC_LOOP_IF_SHORTER")

    # ────── Review / Publish Targets ──────
    review_timeout_hours: int = Field(default=4, alias="REVIEW_TIMEOUT_HOURS")
    publish_to_x: bool = Field(default=True, alias="PUBLISH_TO_X")
    publish_to_youtube: bool = Field(default=False, alias="PUBLISH_TO_YOUTUBE")
    publish_to_facebook: bool = Field(default=False, alias="PUBLISH_TO_FACEBOOK")

    # ────── Facebook Page API ──────
    facebook_page_id: str = Field(default="", alias="FACEBOOK_PAGE_ID")
    facebook_page_access_token: str = Field(default="", alias="FACEBOOK_PAGE_ACCESS_TOKEN")

    # ────── YouTube Data API v3 ──────
    youtube_enabled: bool = Field(default=False, alias="YOUTUBE_ENABLED")
    youtube_credentials_path: str = Field(
        default="/app/secrets/yt_credentials.json", alias="YOUTUBE_CREDENTIALS_PATH"
    )
    youtube_token_path: str = Field(
        default="/app/secrets/yt_token.json", alias="YOUTUBE_TOKEN_PATH"
    )
    youtube_category_id: str = Field(default="1", alias="YOUTUBE_CATEGORY_ID")
    youtube_privacy: str = Field(default="public", alias="YOUTUBE_PRIVACY")
    youtube_default_tags: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["shorts", "animation", "cute", "pets", "satisfying"],
        alias="YOUTUBE_DEFAULT_TAGS",
    )
    caption_profiles_json: Annotated[dict[str, dict[str, Any]], NoDecode] = Field(
        default_factory=lambda: default_caption_profiles(), alias="CAPTION_PROFILES_JSON"
    )
    profile_hourly_map: Annotated[list[str], NoDecode] = Field(
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

    @field_validator(
        "tiktok_hashtag_urls",
        "youtube_search_queries",
        "youtube_hashtag_urls",
        "youtube_exclude_uploaders",
        "youtube_default_tags",
        "silent_keywords_positive",
        "silent_keywords_negative",
        "post_slots_vn",
        mode="before",
    )
    @classmethod
    def parse_string_list(cls, value):
        if isinstance(value, list):
            return value
        if not value:
            return []
        return [item.strip() for item in str(value).split(",") if item.strip()]

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
    return ["A1"] * 24
