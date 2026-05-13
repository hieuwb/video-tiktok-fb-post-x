from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from app.core.config import Settings, get_settings
from app.db.models import Job

logger = logging.getLogger(__name__)


class FacebookPublisherError(RuntimeError):
    pass


class FacebookPublisherService:
    """Post video lên Facebook Page qua Graph API.

    Setup:
      1. Tạo Facebook App tại developers.facebook.com
      2. Lấy Page Access Token (long-lived) với quyền:
         pages_manage_posts, pages_read_engagement, pages_show_list
      3. Set FACEBOOK_PAGE_ID và FACEBOOK_PAGE_ACCESS_TOKEN trong .env

    Flow:
      1. POST /{page_id}/videos  (resumable upload)
         → upload video file
      2. Poll video status until ready
      3. Return post_id + post_url
    """

    GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def publish(self, job: Job) -> dict[str, str]:
        if not self.settings.facebook_page_id:
            raise FacebookPublisherError("FACEBOOK_PAGE_ID not configured in .env")
        if not self.settings.facebook_page_access_token:
            raise FacebookPublisherError("FACEBOOK_PAGE_ACCESS_TOKEN not configured in .env")

        media_source = job.output_video_path or job.raw_video_path
        if not media_source or not Path(media_source).exists():
            raise FileNotFoundError("Video file not found for Facebook publishing.")

        description = self._build_description(job)

        result = self._upload_video(media_source, description)
        return result

    def _build_description(self, job: Job) -> str:
        text = (job.selected_caption or job.ai_caption_primary or "").strip()
        if job.hashtags:
            text = f"{text}\n\n{job.hashtags}".strip()
        return text

    def _upload_video(self, video_path: str, description: str) -> dict[str, str]:
        page_id = self.settings.facebook_page_id
        token = self.settings.facebook_page_access_token
        url = f"{self.GRAPH_API_BASE}/{page_id}/videos"

        file_path = Path(video_path)
        file_size = file_path.stat().st_size

        if file_size < 100 * 1024 * 1024:
            return self._upload_simple(url, file_path, description, token)
        return self._upload_resumable(url, file_path, description, token)

    def _upload_simple(
        self, url: str, file_path: Path, description: str, token: str,
    ) -> dict[str, str]:
        with file_path.open("rb") as fh:
            resp = requests.post(
                url,
                files={"source": (file_path.name, fh, "video/mp4")},
                data={
                    "description": description,
                    "access_token": token,
                    "published": "true",
                },
                timeout=300,
            )

        if resp.status_code != 200:
            raise FacebookPublisherError(
                f"Facebook upload failed ({resp.status_code}): {resp.text[:500]}"
            )

        data = resp.json()
        video_id = data.get("id")
        if not video_id:
            raise FacebookPublisherError(f"Facebook upload returned no id: {data}")

        page_id = self.settings.facebook_page_id
        post_url = f"https://www.facebook.com/{page_id}/videos/{video_id}"

        logger.info("Facebook video uploaded: %s", post_url)
        return {"post_id": video_id, "post_url": post_url}

    def _upload_resumable(
        self, url: str, file_path: Path, description: str, token: str,
    ) -> dict[str, str]:
        file_size = file_path.stat().st_size

        start_resp = requests.post(
            url,
            data={
                "upload_phase": "start",
                "file_size": file_size,
                "access_token": token,
            },
            timeout=30,
        )
        if start_resp.status_code != 200:
            raise FacebookPublisherError(
                f"Facebook resumable start failed: {start_resp.text[:500]}"
            )
        start_data = start_resp.json()
        upload_session_id = start_data.get("upload_session_id")
        video_id = start_data.get("video_id")

        with file_path.open("rb") as fh:
            offset = 0
            while offset < file_size:
                chunk = fh.read(4 * 1024 * 1024)
                transfer_resp = requests.post(
                    url,
                    files={"video_file_chunk": (file_path.name, chunk, "video/mp4")},
                    data={
                        "upload_phase": "transfer",
                        "upload_session_id": upload_session_id,
                        "start_offset": offset,
                        "access_token": token,
                    },
                    timeout=120,
                )
                if transfer_resp.status_code != 200:
                    raise FacebookPublisherError(
                        f"Facebook chunk upload failed at offset {offset}: {transfer_resp.text[:500]}"
                    )
                transfer_data = transfer_resp.json()
                offset = int(transfer_data.get("start_offset", file_size))

        finish_resp = requests.post(
            url,
            data={
                "upload_phase": "finish",
                "upload_session_id": upload_session_id,
                "access_token": token,
                "description": description,
                "published": "true",
            },
            timeout=60,
        )
        if finish_resp.status_code != 200:
            raise FacebookPublisherError(
                f"Facebook finish failed: {finish_resp.text[:500]}"
            )

        finish_data = finish_resp.json()
        success = finish_data.get("success", False)
        if not success and not video_id:
            raise FacebookPublisherError(f"Facebook finish returned: {finish_data}")

        page_id = self.settings.facebook_page_id
        post_url = f"https://www.facebook.com/{page_id}/videos/{video_id}"

        logger.info("Facebook video uploaded (resumable): %s", post_url)
        return {"post_id": str(video_id), "post_url": post_url}
