from celery import Celery
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
        "app.workers.tasks_subtitle",
        "app.workers.tasks_caption",
        "app.workers.tasks_publish",
    ),
)


def dispatch_task(task_name: str, *args) -> bool:
    try:
        celery_app.send_task(task_name, args=args)
        return True
    except OperationalError:
        return False
