import logging

from app.core.config import get_settings
from app.db import crud
from app.db.session import SessionLocal
from app.core.utils import ensure_utc_datetime
from app.services.caption_rewriter import CaptionRewriterService
from app.services.profile_selector import ProfileSelectorService
from app.services.runtime_settings import RuntimeSettingsService
from app.services.telegram_notifier import TelegramNotifier
from app.workers.celery_app import celery_app, dispatch_task
from app.workers.tasks_publish import enqueue_publish_job


logger = logging.getLogger(__name__)


def enqueue_caption_job(job_id: int) -> None:
    if not dispatch_task("app.workers.tasks_caption.process_caption", job_id):
        logger.warning("Celery broker unavailable. Caption job %s was not queued.", job_id)


def retry_caption_generation(job_id: int) -> None:
    if not dispatch_task("app.workers.tasks_caption.process_caption", job_id):
        logger.warning("Celery broker unavailable. Caption retry for job %s was not queued.", job_id)


@celery_app.task(name="app.workers.tasks_caption.process_caption")
def process_caption(job_id: int) -> None:
    runtime = RuntimeSettingsService()
    db = SessionLocal()
    notifier = TelegramNotifier()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            return
        crud.update_job(db, job, status="generating_caption")
        service = CaptionRewriterService()
        selector = ProfileSelectorService()
        profile = (
            selector.get_profile(job.selected_profile)
            if job.selected_profile
            else selector.get_active_profile()
        )
        package = service.generate_caption_package(job, profile)
        next_status = "awaiting_review"
        if runtime.get_auto_post_enabled() and not runtime.get_require_approval_before_post():
            next_status = "approved"
        crud.update_job(
            db,
            job,
            status=next_status,
            selected_profile=profile.code,
            target_language=profile.language,
            ai_caption_primary=package["captions"]["public_clean"],
            ai_caption_alt_1=package["captions"]["neutral"],
            ai_caption_alt_2=package["captions"]["more_engaging"],
            selected_caption=package["captions"].get(profile.style, package["captions"]["public_clean"]),
            hashtags=" ".join(package["hashtags"]),
        )
        if next_status == "approved":
            notifier.notify_auto_post_queued(job.id)
            enqueue_publish_job(job.id, eta=ensure_utc_datetime(job.scheduled_publish_at))
        else:
            notifier.notify_review_ready(job.id)
    except Exception as exc:
        logger.exception("Caption generation failed for job %s", job_id)
        if "job" in locals() and job:
            crud.update_job(db, job, status="failed", error_message=str(exc))
            notifier.notify_failure(job.id, str(exc))
    finally:
        db.close()
