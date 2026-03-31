import logging

from app.core.config import get_settings
from app.db import crud
from app.db.session import SessionLocal
from app.services.subtitle_generator import SubtitleGeneratorService
from app.services.video_processor import VideoProcessorService
from app.workers.celery_app import celery_app, dispatch_task
from app.workers.tasks_caption import enqueue_caption_job


logger = logging.getLogger(__name__)


def enqueue_subtitle_job(job_id: int, transcript_payload: dict) -> None:
    if not dispatch_task("app.workers.tasks_subtitle.process_subtitles", job_id, transcript_payload):
        logger.warning("Celery broker unavailable. Subtitle job %s was not queued.", job_id)


@celery_app.task(name="app.workers.tasks_subtitle.process_subtitles")
def process_subtitles(job_id: int, transcript_payload: dict) -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            return
        crud.update_job(db, job, status="generating_subtitle")
        subtitle_service = SubtitleGeneratorService()
        srt_path = subtitle_service.generate_srt(job.id, transcript_payload)
        update_fields = {"subtitle_srt_path": srt_path}

        if settings.enable_burned_subtitle and job.raw_video_path:
            crud.update_job(db, job, status="burning_subtitle")
            video_processor = VideoProcessorService()
            output_path = video_processor.burn_subtitles(job.id, job.raw_video_path, srt_path)
            update_fields["output_video_path"] = output_path
        else:
            update_fields["output_video_path"] = job.raw_video_path

        crud.update_job(db, job, **update_fields)
        enqueue_caption_job(job.id)
    except Exception as exc:
        logger.exception("Subtitle generation failed for job %s", job_id)
        if "job" in locals() and job:
            crud.update_job(db, job, status="failed", error_message=str(exc))
    finally:
        db.close()
