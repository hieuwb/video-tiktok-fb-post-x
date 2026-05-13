from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.db import crud
from app.db.session import SessionLocal
from app.services.audio_replacer import AudioReplacerService, mood_for_tags
from app.services.caption_rewriter import CaptionRewriterService
from app.services.downloader import DownloaderService
from app.services.preview_generator import PreviewGeneratorService
from app.services.publish_scheduler import PublishScheduler
from app.services.runtime_settings import RuntimeSettingsService
from app.services.source_crawler import SourceCrawlerService, VideoCandidate
from app.services.telegram_notifier import TelegramNotifier
from app.services.video_processor import VideoProcessorService
from app.workers.celery_app import celery_app, dispatch_task


logger = logging.getLogger(__name__)


def enqueue_auto_crawl() -> None:
    if not dispatch_task("app.workers.tasks_reup.auto_crawl_and_prepare"):
        logger.warning("Celery broker unavailable. Auto-crawl not queued.")


def enqueue_reup_job(job_id: int) -> None:
    if not dispatch_task("app.workers.tasks_reup.process_reup", job_id):
        logger.warning("Celery broker unavailable. Reup job %s not queued.", job_id)


@celery_app.task(name="app.workers.tasks_reup.auto_crawl_and_prepare")
def auto_crawl_and_prepare() -> None:
    """Crawl TikTok+YouTube → pick 1 candidate chưa xử lý → tạo Job → enqueue process_reup.

    Notify Telegram nếu crawl rỗng để user biết trigger /find lại hoặc
    refresh cookie. Không silent-fail.
    """
    settings = get_settings()
    notifier = TelegramNotifier()
    if not settings.auto_crawl_enabled:
        logger.info("Auto-crawl disabled, skipping.")
        return

    crawler = SourceCrawlerService(settings)
    candidates = crawler.crawl_all(limit_per_source=10)
    if not candidates:
        logger.info("No candidates from crawl.")
        try:
            notifier.send_message(
                "⚠️ Auto-crawl không tìm được video nào (TikTok/YouTube).\n"
                "Có thể do: cookie hết hạn, keyword filter quá chặt, hoặc tất cả candidate đã xử lý.\n"
                "Thử /find để chạy lại, hoặc kiểm tra TIKTOK_COOKIE_HEADER / SILENT_KEYWORDS_POSITIVE."
            )
        except Exception:
            logger.exception("Failed to notify empty-crawl")
        return

    db = SessionLocal()
    try:
        chosen: VideoCandidate | None = None
        for candidate in candidates:
            if crud.find_job_by_source(db, candidate.platform, candidate.source_id):
                continue
            chosen = candidate
            break
        if not chosen:
            logger.info("All candidates already processed.")
            return

        mood = mood_for_tags(chosen.title, chosen.tags)
        job = crud.create_job(
            db,
            source_url=chosen.url,
            source_platform=chosen.platform,
            status="pending",
        )
        crud.update_job(
            db,
            job,
            source_id=chosen.source_id,
            source_title=chosen.title,
            source_caption=chosen.description,
            is_auto_crawled=True,
            crawl_mood=mood,
        )
        logger.info("Auto-crawl created job %s: %s (%s, mood=%s)", job.id, chosen.title[:50], chosen.platform, mood)
        enqueue_reup_job(job.id)
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks_reup.process_reup")
def process_reup(job_id: int) -> None:
    """Pipeline reup: download → strip+mix music → launder → caption EN → preview → review card."""
    settings = get_settings()
    db = SessionLocal()
    notifier = TelegramNotifier()

    try:
        job = crud.get_job(db, job_id)
        if not job:
            logger.warning("Reup job %s not found.", job_id)
            return

        crud.update_job(db, job, status="downloading", error_message=None)
        result = DownloaderService(settings).download(job.id, job.source_url)
        crud.update_job(
            db,
            job,
            raw_video_path=result.file_path,
            source_title=result.title or job.source_title,
            source_caption=result.description or job.source_caption,
            status="downloaded",
        )

        mood = job.crawl_mood or mood_for_tags(job.source_title or "", [])

        working_video = Path(result.file_path)
        music_track: Path | None = None
        if settings.audio_replace_enabled:
            crud.update_job(db, job, status="replacing_audio")
            replacer = AudioReplacerService(settings)
            silent = replacer.strip_audio(working_video)
            try:
                mood = replacer.refine_mood_by_energy(working_video, mood)
                music_track = replacer.pick_music(mood, target_duration=0)
                working_video = replacer.mix_music(silent, music_track)
            except Exception:
                logger.exception(
                    "Music mix failed for job %s — using silent video. "
                    "Check assets/music/ folder.",
                    job.id,
                )
                working_video = silent
                music_track = None
            else:
                silent.unlink(missing_ok=True)

        if settings.enable_launder:
            crud.update_job(db, job, status="laundering")
            try:
                laundered = VideoProcessorService().launder(
                    job.id, str(working_video), title_text=None
                )
                working_video = Path(laundered)
            except Exception:
                logger.exception("Laundering failed for job %s, keep non-laundered.", job.id)

        crud.update_job(db, job, status="generating_caption", output_video_path=str(working_video))
        music_credit = music_track.stem if music_track else ""
        package = CaptionRewriterService().generate_silent_package(
            source_title=job.source_title or "",
            source_tags=[],
            platform=job.source_platform,
            mood=mood,
            music_credit=music_credit,
        )

        x_caption = package["x_caption"]
        x_hashtags = " ".join(package["x_hashtags"])
        yt_title = package["youtube_title"]
        yt_description = package["youtube_description"]
        yt_tags = ",".join(package["youtube_tags"])

        preview_paths: dict = {}
        try:
            preview_paths = PreviewGeneratorService().generate(str(working_video))
        except Exception:
            logger.exception("Preview generation failed for job %s", job.id)

        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.review_timeout_hours)

        # Auto-mode (no approval required) → gán slot publish luôn.
        runtime = RuntimeSettingsService()
        next_status = "awaiting_review"
        scheduled_at = None
        approved_at = None
        if runtime.get_auto_post_enabled() and not runtime.get_require_approval_before_post():
            next_status = "approved"
            try:
                scheduled_at = PublishScheduler().next_slot_utc(db)
                approved_at = datetime.now(timezone.utc)
            except Exception:
                logger.exception("Slot scheduler failed for reup job %s", job.id)

        crud.update_job(
            db,
            job,
            status=next_status,
            selected_profile="A1",
            target_language="en",
            ai_caption_primary=x_caption,
            hashtags=x_hashtags,
            selected_caption=x_caption,
            youtube_title=yt_title,
            youtube_description=yt_description,
            youtube_tags=yt_tags,
            music_track_path=str(music_track) if music_track else None,
            preview_video_path=preview_paths.get("preview"),
            preview_thumbnail_path=preview_paths.get("thumbnail"),
            review_expires_at=expires_at if next_status == "awaiting_review" else None,
            scheduled_publish_at=scheduled_at,
            approved_at=approved_at,
        )

        if next_status == "approved":
            notifier.notify_auto_post_queued(job.id)
        else:
            notifier.notify_reup_review_ready(job.id)

    except Exception as exc:
        logger.exception("Reup pipeline failed for job %s", job_id)
        if "job" in locals() and job:
            failed_in_download = not bool(job.raw_video_path)
            crud.update_job(db, job, status="failed", error_message=str(exc))
            notifier.notify_failure(job.id, str(exc))
            # Auto-retry: nếu là job auto-crawl + fail trong khâu download
            # → tự enqueue auto_crawl mới để pick candidate khác. Source_id của
            # job vừa fail đã trong DB nên find_job_by_source sẽ skip nó.
            if job.is_auto_crawled and failed_in_download:
                logger.info("Auto-crawled job %s failed download → enqueue fresh crawl", job.id)
                enqueue_auto_crawl()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks_reup.expire_stale_reviews")
def expire_stale_reviews() -> None:
    """Auto-reject job awaiting_review quá hạn để tránh queue pile-up."""
    db = SessionLocal()
    try:
        stale = crud.list_expired_reviews(db, datetime.now(timezone.utc))
        for job in stale:
            crud.update_job(db, job, status="expired", error_message="Review timeout")
            logger.info("Job %s expired (no review in time).", job.id)
    finally:
        db.close()
