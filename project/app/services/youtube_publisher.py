from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubePublisherError(RuntimeError):
    pass


class YouTubePublisherService:
    """Upload Shorts lên YouTube qua YouTube Data API v3.

    OAuth flow:
      - Chạy `scripts/yt_oauth_bootstrap.py` 1 lần trên máy có browser để tạo
        token.json (chứa refresh_token). Copy cả credentials.json + token.json
        lên VPS tại đường dẫn config.
      - Mỗi lần upload, service đọc token.json → tự refresh nếu hết hạn →
        ghi lại token.json.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._youtube = None

    def _client(self):
        if self._youtube is not None:
            return self._youtube

        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise YouTubePublisherError(
                "Thiếu google-api-python-client. Chạy: pip install google-api-python-client google-auth-oauthlib"
            ) from exc

        token_path = Path(self.settings.youtube_token_path)
        if not token_path.exists():
            raise YouTubePublisherError(
                f"Không thấy token.json tại {token_path}. Chạy scripts/yt_oauth_bootstrap.py trước."
            )

        with token_path.open("r", encoding="utf-8") as handle:
            token_data = json.load(handle)

        creds = Credentials.from_authorized_user_info(token_data, scopes=YOUTUBE_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise YouTubePublisherError(
                    "YouTube token không hợp lệ và không thể refresh. Chạy lại bootstrap."
                )

        self._youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        return self._youtube

    def publish(
        self,
        video_path: str | Path,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, str]:
        video_path = Path(video_path)
        if not video_path.exists():
            raise YouTubePublisherError(f"Video not found: {video_path}")
        if not self.settings.youtube_enabled:
            raise YouTubePublisherError("YOUTUBE_ENABLED=false — bỏ qua upload.")

        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise YouTubePublisherError("Thiếu googleapiclient.") from exc

        youtube = self._client()

        final_title = self._force_shorts_tag(title)[:100] or "Untitled #Shorts"
        final_tags = (tags or []) + self.settings.youtube_default_tags
        final_tags = list(dict.fromkeys(t.strip().lstrip("#") for t in final_tags if t.strip()))[:15]

        body = {
            "snippet": {
                "title": final_title,
                "description": description[:5000],
                "tags": final_tags,
                "categoryId": str(self.settings.youtube_category_id),
            },
            "status": {
                "privacyStatus": self.settings.youtube_privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info("YouTube upload progress: %d%%", int(status.progress() * 100))

        video_id = response.get("id")
        if not video_id:
            raise YouTubePublisherError(f"YouTube upload failed: {response}")
        return {
            "video_id": video_id,
            "url": f"https://youtube.com/shorts/{video_id}",
        }

    def _force_shorts_tag(self, title: str) -> str:
        cleaned = " ".join((title or "").split()).strip()
        if "#shorts" in cleaned.lower():
            return cleaned
        # +8 chars " #Shorts"; trim title để tổng ≤ 100
        if len(cleaned) + 8 > 100:
            cleaned = cleaned[: 100 - 8].rstrip()
        return f"{cleaned} #Shorts".strip()
