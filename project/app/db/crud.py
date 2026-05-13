from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.models import Job


def create_job(db: Session, source_url: str, source_platform: str, status: str) -> Job:
    job = Job(source_url=source_url, source_platform=source_platform, status=status)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()


def list_jobs(db: Session) -> list[Job]:
    return db.query(Job).order_by(desc(Job.created_at)).limit(100).all()


def update_job(db: Session, job: Job, **fields: Any) -> Job:
    for key, value in fields.items():
        setattr(job, key, value)
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def set_job_profile(db: Session, job: Job, profile_code: str, target_language: str) -> Job:
    return update_job(
        db,
        job,
        selected_profile=profile_code,
        target_language=target_language,
    )


def set_job_schedule(db: Session, job: Job, scheduled_publish_at: datetime | None) -> Job:
    return update_job(db, job, scheduled_publish_at=scheduled_publish_at)


def find_job_by_source(db: Session, platform: str, source_id: str) -> Job | None:
    if not source_id:
        return None
    return (
        db.query(Job)
        .filter(Job.source_platform == platform, Job.source_id == source_id)
        .first()
    )


def list_jobs_by_status(db: Session, status: str, limit: int = 50) -> list[Job]:
    return (
        db.query(Job)
        .filter(Job.status == status)
        .order_by(desc(Job.created_at))
        .limit(limit)
        .all()
    )


def list_expired_reviews(db: Session, now: datetime) -> list[Job]:
    return (
        db.query(Job)
        .filter(
            Job.status == "awaiting_review",
            Job.review_expires_at.isnot(None),
            Job.review_expires_at < now,
        )
        .all()
    )


def list_due_slot_jobs(db: Session, now: datetime, limit: int = 5) -> list[Job]:
    """Job approved có scheduled_publish_at <= now → chờ slot tới giờ."""
    return (
        db.query(Job)
        .filter(
            Job.status == "approved",
            Job.scheduled_publish_at.isnot(None),
            Job.scheduled_publish_at <= now,
        )
        .order_by(Job.scheduled_publish_at)
        .limit(limit)
        .all()
    )


def list_scheduled_after(db: Session, after_utc: datetime) -> list[Job]:
    """Tất cả slot đã đặt từ thời điểm `after_utc` về sau (để publish_scheduler tránh trùng)."""
    return (
        db.query(Job)
        .filter(
            Job.scheduled_publish_at.isnot(None),
            Job.scheduled_publish_at >= after_utc,
            Job.status.in_(["approved", "publishing", "awaiting_review"]),
        )
        .all()
    )


def list_archive_candidates(db: Session, posted_before_utc: datetime) -> list[Job]:
    """Job đã posted trước `posted_before_utc` → archive (xóa file, giữ DB row)."""
    return (
        db.query(Job)
        .filter(
            Job.status == "posted",
            Job.posted_at.isnot(None),
            Job.posted_at < posted_before_utc,
        )
        .all()
    )


def list_purge_candidates(db: Session, updated_before_utc: datetime) -> list[Job]:
    """Job failed/expired/rejected cũ → xoá hẳn cả DB row."""
    terminal = ("failed", "failed_publish", "expired", "rejected", "archived")
    return (
        db.query(Job)
        .filter(
            Job.status.in_(terminal),
            Job.updated_at < updated_before_utc,
        )
        .all()
    )


def mark_job_posted_multi(
    db: Session,
    job: Job,
    x_result: dict | None = None,
    youtube_result: dict | None = None,
    facebook_result: dict | None = None,
) -> Job:
    fields: dict = {
        "status": "posted",
        "scheduled_publish_at": None,
        "posted_at": datetime.now(timezone.utc),
    }
    if x_result:
        fields["x_post_id"] = x_result.get("post_id")
        fields["x_post_url"] = x_result.get("post_url")
    if youtube_result:
        fields["youtube_video_id"] = youtube_result.get("video_id")
        fields["youtube_url"] = youtube_result.get("url")
    if facebook_result:
        fields["facebook_post_id"] = facebook_result.get("post_id")
        fields["facebook_post_url"] = facebook_result.get("post_url")
    return update_job(db, job, **fields)
