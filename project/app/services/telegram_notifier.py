from __future__ import annotations

from pathlib import Path

import requests

from app.core.config import get_settings
from app.db import crud
from app.db.session import SessionLocal
from app.db.models import Job
from app.services.runtime_settings import RuntimeSettingsService


class TelegramNotifier:
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

    def format_job_status(self, job: Job) -> str:
        autopost_status = "on" if RuntimeSettingsService().get_auto_post_enabled() else "off"
        return "\n".join(
            [
                f"Job ID: {job.id}",
                f"URL: {job.source_url}",
                f"Platform: {job.source_platform}",
                f"Status: {job.status}",
                f"Auto-post: {autopost_status}",
                f"Profile: {job.selected_profile or '-'}",
                f"Language: {job.target_language or '-'}",
                f"Caption: {job.selected_caption or '-'}",
                f"Hashtags: {job.hashtags or '-'}",
                f"Subtitle: {job.subtitle_srt_path or '-'}",
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
            if job.subtitle_srt_path and Path(job.subtitle_srt_path).exists():
                self.send_document(job.subtitle_srt_path)
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
            self.send_message(
                f"Job {job.id} posted successfully.\nPost URL: {job.x_post_url or '-'}"
            )
        finally:
            db.close()

    def notify_failure(self, job_id: int, error_message: str) -> None:
        self.send_message(f"Job {job_id} failed.\nError: {error_message[:1000]}")

    def notify_auto_post_queued(self, job_id: int) -> None:
        db = SessionLocal()
        try:
            job = crud.get_job(db, job_id)
            if not job:
                return
            self.send_message(
                f"Job {job.id} auto-post queued.\nProfile: {job.selected_profile or '-'}\nLanguage: {job.target_language or '-'}"
            )
        finally:
            db.close()
