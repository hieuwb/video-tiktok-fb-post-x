from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class PreviewGeneratorError(RuntimeError):
    pass


class PreviewGeneratorService:
    """Sinh thumbnail (JPEG) + clip preview ngắn (MP4, ~4s) để gửi Telegram.

    Telegram giới hạn upload 50 MB qua bot API; preview ~1-3 MB cho phép
    hiển thị nhanh mà không cần tải full video laundered về xem.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def make_thumbnail(self, video_path: str | Path, out_path: str | Path | None = None) -> Path:
        video_path = Path(video_path)
        if out_path is None:
            out_path = video_path.with_name(f"{video_path.stem}.thumb.jpg")
        out_path = Path(out_path)

        duration = self._probe_duration(video_path)
        seek = max(0.1, duration * 0.5) if duration > 0 else 1.0

        cmd = [
            self.settings.ffmpeg_bin, "-y", "-loglevel", "error",
            "-ss", f"{seek:.2f}",
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", "scale=-2:720",
            "-q:v", "4",
            str(out_path),
        ]
        self._run(cmd)
        return out_path

    def make_preview_clip(
        self,
        video_path: str | Path,
        out_path: str | Path | None = None,
        clip_duration: float = 4.0,
    ) -> Path:
        video_path = Path(video_path)
        if out_path is None:
            out_path = video_path.with_name(f"{video_path.stem}.preview.mp4")
        out_path = Path(out_path)

        total = self._probe_duration(video_path)
        start = max(0.0, min(total * 0.25, max(0.0, total - clip_duration)))

        cmd = [
            self.settings.ffmpeg_bin, "-y", "-loglevel", "error",
            "-ss", f"{start:.2f}",
            "-i", str(video_path),
            "-t", f"{clip_duration:.2f}",
            "-vf", "scale=-2:540",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "96k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        self._run(cmd)
        return out_path

    def generate(self, video_path: str | Path) -> dict:
        thumb = self.make_thumbnail(video_path)
        clip = self.make_preview_clip(video_path)
        return {"thumbnail": str(thumb), "preview": str(clip)}

    def _probe_duration(self, media_path: str | Path) -> float:
        cmd = [
            self.settings.ffprobe_bin, "-v", "error",
            "-show_entries", "format=duration", "-of", "json", str(media_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(json.loads(result.stdout or "{}").get("format", {}).get("duration") or 0.0)
        except (subprocess.CalledProcessError, ValueError, json.JSONDecodeError):
            return 0.0

    def _run(self, cmd: list[str]) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise PreviewGeneratorError(
                f"ffmpeg preview failed: {result.stderr.strip()[:400]}"
            )
