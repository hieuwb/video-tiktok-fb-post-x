from __future__ import annotations

from pathlib import Path

import tweepy

from app.core.config import get_settings
from app.db.models import Job


class XPublisherService:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.v1_client = tweepy.API(
            tweepy.OAuth1UserHandler(
                settings.x_api_key,
                settings.x_api_key_secret,
                settings.x_access_token,
                settings.x_access_token_secret,
            )
        )
        self.v2_client = tweepy.Client(
            bearer_token=settings.x_bearer_token,
            consumer_key=settings.x_api_key,
            consumer_secret=settings.x_api_key_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_token_secret,
        )

    def publish(self, job: Job) -> dict[str, str]:
        if self.settings.require_approval_before_post and job.status != "publishing":
            raise ValueError("Job is not approved for publishing.")
        media_source = job.output_video_path or job.raw_video_path
        if not media_source or not Path(media_source).exists():
            raise FileNotFoundError("Video file not found for publishing.")

        uploaded = self.v1_client.media_upload(filename=media_source, media_category="tweet_video")
        text = job.selected_caption or job.ai_caption_primary or ""
        if job.hashtags:
            text = f"{text}\n\n{job.hashtags}".strip()
        tweet = self.v2_client.create_tweet(text=text[:280], media_ids=[uploaded.media_id_string])
        post_id = str(tweet.data["id"])
        return {"post_id": post_id, "post_url": f"https://x.com/i/web/status/{post_id}"}
