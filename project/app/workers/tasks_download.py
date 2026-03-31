import logging

from app.core.config import get_settings
from app.db import crud
from app.db.session import SessionLocal
from app.services.downloader import DownloaderService
from app.services.telegram_notifier import TelegramNotifier
from app.workers.celery_app import celery_app, dispatch_task
from app.workers.tasks_transcribe import enqueue_transcription_job


logger = logging.getLogger(__name__)


def enqueue_processing_job(job_id: int) -> None:
    if not dispatch_task("app.workers.tasks_download.process_download", job_id):
        logger.warning("Celery broker unavailable. Job %s remains queued.", job_id)


@celery_app.task(name="app.workers.tasks_download.process_download")
def process_download(job_id: int) -> None:
    settings = get_settings()
    db = SessionLocal()
    notifier = TelegramNotifier()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            logger.warning("Job %s not found for download.", job_id)
            return

        crud.update_job(db, job, status="validating", error_message=None)
        downloader = DownloaderService(settings)
        crud.update_job(db, job, status="downloading")
        result = downloader.download(job.id, job.source_url)
        crud.update_job(
            db,
            job,
            status="downloaded",
            raw_video_path=result.file_path,
            source_title=result.title,
            source_caption=result.description,
        )
        enqueue_transcription_job(job.id)
    except Exception as exc:
        logger.exception("Download failed for job %s", job_id)
        if "job" in locals() and job:
            crud.update_job(db, job, status="failed", error_message=str(exc))
            notifier.notify_failure(job.id, str(exc))
    finally:
        db.close()
