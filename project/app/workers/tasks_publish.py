import logging

from datetime import datetime, timezone

from app.core.config import get_settings
from app.db import crud
from app.db.session import SessionLocal
from app.core.utils import ensure_utc_datetime
from app.services.facebook_publisher import FacebookPublisherError, FacebookPublisherService
from app.services.telegram_notifier import TelegramNotifier
from app.services.x_publisher import XPublisherService
from app.services.youtube_publisher import YouTubePublisherError, YouTubePublisherService
from app.workers.celery_app import celery_app, dispatch_task


logger = logging.getLogger(__name__)


def enqueue_publish_job(job_id: int, eta: datetime | None = None, targets: str = "both") -> None:
    if not dispatch_task("app.workers.tasks_publish.process_publish", job_id, targets, eta=eta):
        logger.warning("Celery broker unavailable. Publish job %s was not queued.", job_id)


@celery_app.task(name="app.workers.tasks_publish.dispatch_due_slots")
def dispatch_due_slots() -> int:
    """Beat task 5p/lần — kích publish cho job approved có scheduled_publish_at <= now.

    Lý do tách dispatcher khỏi `eta` của Celery:
      - Worker restart có thể mất task pending với ETA xa.
      - DB là source of truth bền hơn message queue.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due = crud.list_due_slot_jobs(db, now, limit=10)
        for job in due:
            logger.info("Slot dispatch: enqueue publish for job %s (slot=%s)", job.id, job.scheduled_publish_at)
            enqueue_publish_job(job.id, targets="all")
        return len(due)
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks_publish.process_publish")
def process_publish(job_id: int, targets: str = "both") -> None:
    db = SessionLocal()
    notifier = TelegramNotifier()
    settings = get_settings()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            return
        scheduled_publish_at = ensure_utc_datetime(job.scheduled_publish_at)
        if scheduled_publish_at and scheduled_publish_at > datetime.now(timezone.utc):
            logger.info("Job %s scheduled for %s UTC, skipping early publish.", job_id, scheduled_publish_at)
            return

        want_x = targets in {"both", "x", "all"} and settings.publish_to_x
        want_yt = targets in {"both", "youtube", "all"} and settings.publish_to_youtube and settings.youtube_enabled
        want_fb = targets in {"both", "facebook", "all"} and settings.publish_to_facebook

        if not want_x and not want_yt and not want_fb:
            crud.update_job(db, job, status="failed_publish", error_message="No active publish target")
            notifier.notify_failure(job.id, "No active publish target (check PUBLISH_TO_X / PUBLISH_TO_YOUTUBE / PUBLISH_TO_FACEBOOK).")
            return

        crud.update_job(db, job, status="publishing")

        x_result = None
        yt_result = None
        errors: list[str] = []

        if want_x:
            try:
                x_result = XPublisherService().publish(job)
                logger.info("Job %s posted on X: %s", job.id, x_result.get("post_url"))
            except Exception as exc:
                logger.exception("X publish failed for job %s", job.id)
                errors.append(f"X: {exc}")

        if want_yt:
            try:
                title = job.youtube_title or job.source_title or "Silent short"
                description = job.youtube_description or ""
                tags = [t.strip() for t in (job.youtube_tags or "").split(",") if t.strip()]
                yt_raw = YouTubePublisherService().publish(
                    video_path=job.output_video_path or job.raw_video_path,
                    title=title,
                    description=description,
                    tags=tags,
                )
                yt_result = {"video_id": yt_raw["video_id"], "url": yt_raw["url"]}
                logger.info("Job %s posted on YouTube: %s", job.id, yt_result["url"])
            except YouTubePublisherError as exc:
                logger.warning("YouTube skipped/failed for job %s: %s", job.id, exc)
                errors.append(f"YT: {exc}")
            except Exception as exc:
                logger.exception("YouTube publish failed for job %s", job.id)
                errors.append(f"YT: {exc}")

        fb_result = None
        if want_fb:
            try:
                fb_raw = FacebookPublisherService().publish(job)
                fb_result = {"post_id": fb_raw["post_id"], "post_url": fb_raw["post_url"]}
                logger.info("Job %s posted on Facebook: %s", job.id, fb_result["post_url"])
            except FacebookPublisherError as exc:
                logger.warning("Facebook skipped/failed for job %s: %s", job.id, exc)
                errors.append(f"FB: {exc}")
            except Exception as exc:
                logger.exception("Facebook publish failed for job %s", job.id)
                errors.append(f"FB: {exc}")

        if not x_result and not yt_result and not fb_result:
            crud.update_job(
                db, job, status="failed_publish",
                error_message="; ".join(errors)[:1000] or "All publish targets failed",
            )
            notifier.notify_failure(job.id, "; ".join(errors) or "Publish failed")
            return

        crud.mark_job_posted_multi(db, job, x_result=x_result, youtube_result=yt_result, facebook_result=fb_result)
        if errors:
            crud.update_job(db, job, error_message="; ".join(errors)[:1000])
        notifier.notify_publish_success(job.id)

    except Exception as exc:
        logger.exception("Publish failed for job %s", job_id)
        if "job" in locals() and job:
            crud.update_job(db, job, status="failed_publish", error_message=str(exc))
            notifier.notify_failure(job.id, str(exc))
    finally:
        db.close()
