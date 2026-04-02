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


def mark_job_approved(db: Session, job: Job) -> Job:
    return update_job(db, job, status="approved", approved_at=datetime.now(timezone.utc))


def mark_job_posted(db: Session, job: Job, post_id: str, post_url: str) -> Job:
    return update_job(
        db,
        job,
        status="posted",
        x_post_id=post_id,
        x_post_url=post_url,
        scheduled_publish_at=None,
        posted_at=datetime.now(timezone.utc),
    )


def set_job_profile(db: Session, job: Job, profile_code: str, target_language: str) -> Job:
    return update_job(
        db,
        job,
        selected_profile=profile_code,
        target_language=target_language,
    )


def set_job_schedule(db: Session, job: Job, scheduled_publish_at: datetime | None) -> Job:
    return update_job(db, job, scheduled_publish_at=scheduled_publish_at)
