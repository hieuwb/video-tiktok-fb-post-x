import logging

from datetime import datetime, timezone

from app.db import crud
from app.db.session import SessionLocal
from app.core.utils import ensure_utc_datetime
from app.services.telegram_notifier import TelegramNotifier
from app.services.x_publisher import XPublisherService
from app.workers.celery_app import celery_app, dispatch_task


logger = logging.getLogger(__name__)


def enqueue_publish_job(job_id: int, eta: datetime | None = None) -> None:
    if not dispatch_task("app.workers.tasks_publish.process_publish", job_id, eta=eta):
        logger.warning("Celery broker unavailable. Publish job %s was not queued.", job_id)


@celery_app.task(name="app.workers.tasks_publish.process_publish")
def process_publish(job_id: int) -> None:
    db = SessionLocal()
    notifier = TelegramNotifier()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            return
        scheduled_publish_at = ensure_utc_datetime(job.scheduled_publish_at)
        if scheduled_publish_at and scheduled_publish_at > datetime.now(timezone.utc):
            logger.info("Job %s is scheduled for later at %s UTC, skipping early publish.", job_id, scheduled_publish_at)
            return
        crud.update_job(db, job, status="publishing")
        publisher = XPublisherService()
        result = publisher.publish(job)
        crud.mark_job_posted(db, job, result["post_id"], result["post_url"])
        notifier.notify_publish_success(job.id)
    except Exception as exc:
        logger.exception("Publish failed for job %s", job_id)
        if "job" in locals() and job:
            crud.update_job(db, job, status="failed_publish", error_message=str(exc))
            notifier.notify_failure(job.id, str(exc))
    finally:
        db.close()
