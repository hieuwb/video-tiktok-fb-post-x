from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.core.security import detect_platform_from_url, validate_source_url
from app.db import crud
from app.db.models import Job
from app.db.session import get_db
from app.workers.tasks_download import enqueue_processing_job


router = APIRouter()


class JobCreateRequest(BaseModel):
    source_url: HttpUrl


class JobResponse(BaseModel):
    id: int
    source_url: str
    source_platform: str
    status: str
    selected_profile: str | None
    target_language: str | None
    selected_caption: str | None
    error_message: str | None

    @classmethod
    def from_model(cls, job: Job) -> "JobResponse":
        return cls(
            id=job.id,
            source_url=job.source_url,
            source_platform=job.source_platform,
            status=job.status,
            selected_profile=job.selected_profile,
            target_language=job.target_language,
            selected_caption=job.selected_caption,
            error_message=job.error_message,
        )


@router.post("", response_model=JobResponse)
def create_job(payload: JobCreateRequest, db: Session = Depends(get_db)) -> JobResponse:
    url = str(payload.source_url)
    if not validate_source_url(url):
        raise HTTPException(status_code=400, detail="Unsupported or invalid video URL.")

    platform = detect_platform_from_url(url)
    job = crud.create_job(
        db,
        source_url=url,
        source_platform=platform,
        status="queued",
    )
    enqueue_processing_job(job.id)
    return JobResponse.from_model(job)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobResponse:
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobResponse.from_model(job)


@router.get("")
def list_jobs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    jobs = crud.list_jobs(db)
    return [
        {
            "id": job.id,
            "source_url": job.source_url,
            "source_platform": job.source_platform,
            "status": job.status,
            "created_at": job.created_at,
            "posted_at": job.posted_at,
        }
        for job in jobs
    ]
