from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import requests
from yt_dlp import DownloadError, YoutubeDL

from app.core.config import Settings, get_settings
from app.core.security import detect_platform_from_url, enforce_download_limits


@dataclass
class DownloadResult:
    file_path: str
    title: str | None
    description: str | None


class DownloaderService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def download(self, job_id: int, url: str) -> DownloadResult:
        platform = detect_platform_from_url(url)
        resolved_url = self._resolve_source_url(url)
        self._cleanup_existing_artifacts(job_id)
        output_template = str(Path(self.settings.raw_video_dir) / f"{job_id}.%(ext)s")
        request_headers = self._build_request_headers(platform)
        generated_cookie_file = self._build_cookie_file_from_header(platform, resolved_url)
        opts = {
            "outtmpl": output_template,
            "format": "mp4/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "socket_timeout": self.settings.download_timeout_seconds,
            "http_headers": request_headers,
        }
        if generated_cookie_file:
            opts["cookiefile"] = generated_cookie_file
        elif self.settings.ytdlp_cookie_file:
            opts["cookiefile"] = self.settings.ytdlp_cookie_file
        elif self.settings.ytdlp_cookies_from_browser:
            browser_spec = self.settings.ytdlp_cookies_from_browser
            if self.settings.ytdlp_browser_profile:
                opts["cookiesfrombrowser"] = (browser_spec, self.settings.ytdlp_browser_profile)
            else:
                opts["cookiesfrombrowser"] = (browser_spec,)

        with YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(resolved_url, download=True)
                selected_info = self._select_primary_info(info, resolved_url)
                enforce_download_limits(
                    duration=selected_info.get("duration"),
                    filesize=selected_info.get("filesize") or selected_info.get("filesize_approx"),
                )
                filename = self._resolve_downloaded_file_path(selected_info, ydl)
            except DownloadError as exc:
                raise ValueError(self._friendly_error(resolved_url, str(exc))) from exc
            finally:
                if generated_cookie_file:
                    Path(generated_cookie_file).unlink(missing_ok=True)

        final_path = Path(filename)
        if final_path.suffix != ".mp4":
            mp4_candidate = final_path.with_suffix(".mp4")
            if mp4_candidate.exists():
                final_path = mp4_candidate

        return DownloadResult(
            file_path=str(final_path),
            title=selected_info.get("title"),
            description=selected_info.get("description"),
        )

    def _resolve_source_url(self, url: str) -> str:
        platform = detect_platform_from_url(url)
        try:
            response = requests.get(
                url,
                allow_redirects=True,
                timeout=min(self.settings.download_timeout_seconds, 20),
                headers=self._build_request_headers(platform),
            )
            response.close()
            if response.url:
                return response.url
        except requests.RequestException:
            pass
        return url

    def _cleanup_existing_artifacts(self, job_id: int) -> None:
        for directory in [
            self.settings.raw_video_dir,
            self.settings.output_video_dir,
            self.settings.subtitle_dir,
            self.settings.audio_dir,
            self.settings.transcript_dir,
        ]:
            path = Path(directory)
            for candidate in path.glob(f"{job_id}*"):
                if candidate.is_file():
                    candidate.unlink(missing_ok=True)

    def _build_request_headers(self, platform: str) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        if platform == "instagram":
            headers["Referer"] = "https://www.instagram.com/"
            if self.settings.instagram_cookie_header:
                headers["Cookie"] = self.settings.instagram_cookie_header
        elif platform == "facebook":
            headers["Referer"] = "https://www.facebook.com/"
            if self.settings.facebook_cookie_header:
                headers["Cookie"] = self.settings.facebook_cookie_header

        return headers

    def _build_cookie_file_from_header(self, platform: str, source_url: str) -> str | None:
        cookie_header = ""
        if platform == "instagram":
            cookie_header = self.settings.instagram_cookie_header
        elif platform == "facebook":
            cookie_header = self.settings.facebook_cookie_header

        if not cookie_header:
            return None

        domain = urlparse(source_url).hostname or ""
        if not domain:
            return None

        cookie_lines = ["# Netscape HTTP Cookie File"]
        for fragment in cookie_header.split(";"):
            if "=" not in fragment:
                continue
            name, value = fragment.split("=", 1)
            name = name.strip()
            value = value.strip()
            if not name:
                continue
            cookie_lines.append(
                "\t".join(
                    [
                        domain,
                        "TRUE",
                        "/",
                        "FALSE",
                        "0",
                        name,
                        value,
                    ]
                )
            )

        if len(cookie_lines) == 1:
            return None

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".cookies.txt",
            prefix=f"{platform}_",
            dir=self.settings.storage_root,
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write("\n".join(cookie_lines))
            handle.write("\n")
            return handle.name

    def _select_primary_info(self, info: dict, source_url: str) -> dict:
        entries = [entry for entry in info.get("entries", []) if entry]
        if not entries:
            return info

        source_key = self._canonicalize_url(source_url)
        for entry in entries:
            for candidate in [
                entry.get("webpage_url"),
                entry.get("original_url"),
                entry.get("url"),
            ]:
                if candidate and self._canonicalize_url(candidate) == source_key:
                    return entry
        return entries[0]

    def _resolve_downloaded_file_path(self, info: dict, ydl: YoutubeDL | None) -> str:
        requested_downloads = info.get("requested_downloads") or []
        for item in requested_downloads:
            filepath = item.get("filepath")
            if filepath:
                return str(filepath)

        filename = info.get("_filename")
        if filename:
            return str(filename)

        if not ydl:
            raise ValueError("Unable to determine downloaded file path.")
        return str(ydl.prepare_filename(info))

    def _canonicalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        query = "&".join(
            f"{key}={value}"
            for key, value in sorted(parse_qsl(parsed.query, keep_blank_values=True))
            if key not in {"igshid", "igsh", "share_app_id", "utm_source", "utm_medium", "utm_campaign"}
        )
        return parsed._replace(query=query, fragment="").geturl().rstrip("/")

    def _friendly_error(self, url: str, raw_error: str) -> str:
        lowered = raw_error.lower()
        if "tiktok" in url.lower() and "unable to extract webpage video data" in lowered:
            return (
                "TikTok dang doi extractor cua yt-dlp. "
                "Hay rebuild image de cap nhat yt-dlp roi thu lai job nay."
            )
        if "instagram" in url.lower() and (
            "login required" in lowered or "requested content is not available" in lowered
        ):
            return (
                "Instagram link nay yeu cau dang nhap hoac dang bi gioi han. "
                "Hay kiem tra lai INSTAGRAM_COOKIE_HEADER trong .env, uu tien cookie co sessionid hop le, "
                "hoac thu link khac neu bai nay bi chan."
            )
        return raw_error
