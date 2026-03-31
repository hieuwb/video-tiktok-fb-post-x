from __future__ import annotations

from urllib.parse import urlparse

from app.core.config import get_settings


ALLOWED_DOMAINS = {
    "facebook.com",
    "www.facebook.com",
    "fb.watch",
    "m.facebook.com",
    "instagram.com",
    "www.instagram.com",
    "tiktok.com",
    "www.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}


def validate_source_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return parsed.netloc.lower() in ALLOWED_DOMAINS


def detect_platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "instagram" in host:
        return "instagram"
    if "tiktok" in host:
        return "tiktok"
    if "facebook" in host or host == "fb.watch":
        return "facebook"
    return "unknown"


def enforce_download_limits(duration: int | None, filesize: int | None) -> None:
    settings = get_settings()
    if duration and duration > settings.max_video_duration_seconds:
        raise ValueError("Video exceeds max duration.")
    if filesize and filesize > settings.max_video_file_size_mb * 1024 * 1024:
        raise ValueError("Video exceeds max file size.")
