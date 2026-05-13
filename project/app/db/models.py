from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    source_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    is_auto_crawled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    crawl_mood: Mapped[str | None] = mapped_column(String(30), nullable=True)
    raw_video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle_srt_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_profile: Mapped[str | None] = mapped_column(String(10), nullable=True)
    target_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_caption_primary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_caption_alt_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_caption_alt_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    music_track_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    x_post_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    x_post_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_video_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    facebook_post_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    facebook_post_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
