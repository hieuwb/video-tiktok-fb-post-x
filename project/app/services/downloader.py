from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yt_dlp import DownloadError, YoutubeDL

from app.core.config import Settings, get_settings
from app.core.security import enforce_download_limits


@dataclass
class DownloadResult:
    file_path: str
    title: str | None
    description: str | None


class DownloaderService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def download(self, job_id: int, url: str) -> DownloadResult:
        output_template = str(Path(self.settings.raw_video_dir) / f"{job_id}.%(ext)s")
        opts = {
            "outtmpl": output_template,
            "format": "mp4/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "socket_timeout": self.settings.download_timeout_seconds,
        }
        if self.settings.ytdlp_cookie_file:
            opts["cookiefile"] = self.settings.ytdlp_cookie_file
        elif self.settings.ytdlp_cookies_from_browser:
            browser_spec = self.settings.ytdlp_cookies_from_browser
            if self.settings.ytdlp_browser_profile:
                opts["cookiesfrombrowser"] = (browser_spec, self.settings.ytdlp_browser_profile)
            else:
                opts["cookiesfrombrowser"] = (browser_spec,)

        with YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                enforce_download_limits(
                    duration=info.get("duration"),
                    filesize=info.get("filesize") or info.get("filesize_approx"),
                )
                ydl.download([url])
                filename = ydl.prepare_filename(info)
            except DownloadError as exc:
                raise ValueError(self._friendly_error(url, str(exc))) from exc

        final_path = Path(filename)
        if final_path.suffix != ".mp4":
            mp4_candidate = final_path.with_suffix(".mp4")
            if mp4_candidate.exists():
                final_path = mp4_candidate

        return DownloadResult(
            file_path=str(final_path),
            title=info.get("title"),
            description=info.get("description"),
        )

    def _friendly_error(self, url: str, raw_error: str) -> str:
        lowered = raw_error.lower()
        if "instagram" in url.lower() and (
            "login required" in lowered or "requested content is not available" in lowered
        ):
            return (
                "Instagram link nay yeu cau dang nhap hoac dang bi gioi han. "
                "Ban co the bo qua nguon nay, thu link khac, hoac cau hinh cookie neu muon tai Instagram on dinh hon."
            )
        return raw_error
