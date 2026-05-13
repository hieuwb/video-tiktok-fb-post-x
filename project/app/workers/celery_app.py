from celery import Celery
from celery.schedules import crontab
from kombu.exceptions import OperationalError

from app.core.config import get_settings


settings = get_settings()

celery_app = Celery("video_x_bot", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_track_started=True,
    broker_connection_retry_on_startup=False,
    broker_connection_timeout=2,
    imports=(
        "app.workers.tasks_download",
        "app.workers.tasks_transcribe",
        "app.workers.tasks_caption",
        "app.workers.tasks_publish",
        "app.workers.tasks_reup",
        "app.workers.tasks_cleanup",
    ),
    # 3 lần/ngày theo giờ VN (UTC+7): 08:00 / 14:00 / 20:00 → UTC: 01:00 / 07:00 / 13:00
    beat_schedule={
        "auto-crawl-morning": {
            "task": "app.workers.tasks_reup.auto_crawl_and_prepare",
            "schedule": crontab(hour=1, minute=0),
        },
        "auto-crawl-afternoon": {
            "task": "app.workers.tasks_reup.auto_crawl_and_prepare",
            "schedule": crontab(hour=7, minute=0),
        },
        "auto-crawl-evening": {
            "task": "app.workers.tasks_reup.auto_crawl_and_prepare",
            "schedule": crontab(hour=13, minute=0),
        },
        "expire-stale-reviews": {
            "task": "app.workers.tasks_reup.expire_stale_reviews",
            "schedule": crontab(minute="*/30"),
        },
        # Daily cleanup 04:30 UTC = 11:30 VN (ngoài window 13-02).
        "storage-cleanup-daily": {
            "task": "app.workers.tasks_cleanup.cleanup_storage",
            "schedule": crontab(hour=4, minute=30),
        },
        # Slot dispatcher 5p/lần — kiểm tra job approved tới giờ slot thì publish.
        "publish-slot-dispatch": {
            "task": "app.workers.tasks_publish.dispatch_due_slots",
            "schedule": crontab(minute="*/5"),
        },
    },
)


def dispatch_task(task_name: str, *args, eta=None) -> bool:
    try:
        celery_app.send_task(task_name, args=args, eta=eta)
        return True
    except OperationalError:
        return False
