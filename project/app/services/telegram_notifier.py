from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from app.core.config import get_settings
from app.core.utils import ensure_utc_datetime
from app.db import crud
from app.db.session import SessionLocal
from app.db.models import Job
from app.services.runtime_settings import RuntimeSettingsService


class TelegramNotifier:
    vietnam_tz = ZoneInfo("Asia/Ho_Chi_Minh")

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}"

    def _default_chat_id(self) -> int:
        return self.settings.telegram_allowed_user_ids[0]

    def send_message(self, text: str, chat_id: int | None = None) -> None:
        requests.post(
            f"{self.base_url}/sendMessage",
            json={"chat_id": chat_id or self._default_chat_id(), "text": text},
            timeout=30,
        ).raise_for_status()

    def send_document(self, file_path: str, chat_id: int | None = None) -> None:
        with open(file_path, "rb") as handle:
            requests.post(
                f"{self.base_url}/sendDocument",
                data={"chat_id": chat_id or self._default_chat_id()},
                files={"document": handle},
                timeout=60,
            ).raise_for_status()

    def send_video(self, file_path: str, caption: str, chat_id: int | None = None) -> None:
        with open(file_path, "rb") as handle:
            requests.post(
                f"{self.base_url}/sendVideo",
                data={"chat_id": chat_id or self._default_chat_id(), "caption": caption[:1024]},
                files={"video": handle},
                timeout=120,
            ).raise_for_status()

    def send_photo(self, file_path: str, caption: str = "", chat_id: int | None = None) -> None:
        with open(file_path, "rb") as handle:
            requests.post(
                f"{self.base_url}/sendPhoto",
                data={"chat_id": chat_id or self._default_chat_id(), "caption": caption[:1024]},
                files={"photo": handle},
                timeout=60,
            ).raise_for_status()

    def format_job_status(self, job: Job) -> str:
        autopost_status = "on" if RuntimeSettingsService().get_auto_post_enabled() else "off"
        scheduled_at = "-"
        scheduled_publish_at = ensure_utc_datetime(job.scheduled_publish_at)
        if scheduled_publish_at:
            scheduled_at = scheduled_publish_at.astimezone(self.vietnam_tz).strftime("%Y-%m-%d %H:%M ICT")
        return "\n".join(
            [
                f"Job ID: {job.id}",
                f"URL: {job.source_url}",
                f"Platform: {job.source_platform}",
                f"Status: {job.status}",
                f"Auto-post: {autopost_status}",
                f"Profile: {job.selected_profile or '-'}",
                f"Language: {job.target_language or '-'}",
                f"Schedule (VN): {scheduled_at}",
                f"Caption: {job.selected_caption or '-'}",
                f"Hashtags: {job.hashtags or '-'}",
                f"Output: {job.output_video_path or job.raw_video_path or '-'}",
                f"Error: {job.error_message or '-'}",
            ]
        )

    def notify_review_ready(self, job_id: int) -> None:
        if not self.settings.enable_send_preview_to_telegram:
            return
        db = SessionLocal()
        try:
            job = crud.get_job(db, job_id)
            if not job:
                return
            message = "\n".join(
                [
                    "Review ready.",
                    self.format_job_status(job),
                    f"Approve: /approve {job.id}",
                    f"Reject: /reject {job.id}",
                    f"Status: /status {job.id}",
                ]
            )
            self.send_message(message)
            preview_path = job.output_video_path or job.raw_video_path
            if preview_path and Path(preview_path).exists():
                self.send_video(preview_path, caption=f"Preview job {job.id}")
        finally:
            db.close()

    def notify_publish_success(self, job_id: int) -> None:
        db = SessionLocal()
        try:
            job = crud.get_job(db, job_id)
            if not job:
                return
            lines = [f"✅ Job {job.id} posted."]
            if job.x_post_url:
                lines.append(f"🐦 X: {job.x_post_url}")
            if job.youtube_url:
                lines.append(f"📺 YouTube: {job.youtube_url}")
            if job.error_message:
                lines.append(f"⚠️ Warnings: {job.error_message[:300]}")
            self.send_message("\n".join(lines))
        finally:
            db.close()

    def notify_failure(self, job_id: int, error_message: str) -> None:
        self.send_message(f"Job {job_id} failed.\nError: {error_message[:1000]}")

    def notify_reup_review_ready(self, job_id: int) -> None:
        """Review card cho auto-crawl job: thumbnail + preview clip + caption + commands."""
        if not self.settings.enable_send_preview_to_telegram:
            return
        db = SessionLocal()
        try:
            job = crud.get_job(db, job_id)
            if not job:
                return
            expires_text = "-"
            if job.review_expires_at:
                expires_text = ensure_utc_datetime(job.review_expires_at).astimezone(
                    self.vietnam_tz
                ).strftime("%Y-%m-%d %H:%M ICT")

            lines = [
                f"🎬 Auto-crawl job {job.id} sẵn sàng review",
                f"Source: {job.source_platform} | mood: {job.crawl_mood or '-'}",
                f"Title: {(job.source_title or '')[:120]}",
                f"URL: {job.source_url}",
                "",
                f"📝 X caption:\n{job.selected_caption or '-'}",
                f"Hashtags: {job.hashtags or '-'}",
                "",
                f"📺 YT title: {job.youtube_title or '-'}",
                f"YT tags: {job.youtube_tags or '-'}",
                "",
                f"🎵 Music: {Path(job.music_track_path).stem if job.music_track_path else '-'}",
                f"Expires: {expires_text}",
                "",
                f"/approve {job.id}       → đăng cả X + YouTube + Facebook",
                f"/approve_x {job.id}     → chỉ X",
                f"/approve_yt {job.id}    → chỉ YouTube",
                f"/approve_fb {job.id}    → chỉ Facebook",
                f"/reject {job.id}        → bỏ",
            ]
            self.send_message("\n".join(lines))

            if job.preview_thumbnail_path and Path(job.preview_thumbnail_path).exists():
                self.send_photo(job.preview_thumbnail_path, caption=f"Thumbnail job {job.id}")
            full_video = job.output_video_path or job.raw_video_path
            if full_video and Path(full_video).exists():
                self.send_video(full_video, caption=f"Full video job {job.id}")
        finally:
            db.close()

    def notify_auto_post_queued(self, job_id: int) -> None:
        db = SessionLocal()
        try:
            job = crud.get_job(db, job_id)
            if not job:
                return
            message = [
                f"Job {job.id} auto-post queued.",
                f"Profile: {job.selected_profile or '-'}",
                f"Language: {job.target_language or '-'}",
            ]
            scheduled_publish_at = ensure_utc_datetime(job.scheduled_publish_at)
            if scheduled_publish_at:
                message.append(
                    f"Schedule (VN): {scheduled_publish_at.astimezone(self.vietnam_tz).strftime('%Y-%m-%d %H:%M ICT')}"
                )
            self.send_message("\n".join(message))
        finally:
            db.close()
