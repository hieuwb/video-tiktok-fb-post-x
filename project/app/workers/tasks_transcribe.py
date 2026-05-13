import logging
from pathlib import Path

from app.core.config import get_settings
from app.db import crud
from app.db.session import SessionLocal
from app.services.audio_replacer import AudioReplacerService, mood_for_tags
from app.services.transcriber import TranscriberService
from app.services.translator import TranslatorService
from app.services.video_processor import VideoProcessorService
from app.workers.tasks_caption import enqueue_caption_job
from app.workers.celery_app import celery_app, dispatch_task


logger = logging.getLogger(__name__)


def enqueue_transcription_job(job_id: int) -> None:
    if not dispatch_task("app.workers.tasks_transcribe.process_transcription", job_id):
        logger.warning("Celery broker unavailable. Transcription job %s was not queued.", job_id)


@celery_app.task(name="app.workers.tasks_transcribe.process_transcription")
def process_transcription(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            return
        crud.update_job(db, job, status="extracting_audio")
        transcriber = TranscriberService()
        audio_path = transcriber.extract_audio(job.id, job.raw_video_path)
        crud.update_job(db, job, audio_path=audio_path, status="transcribing")

        transcript = transcriber.transcribe(audio_path)
        crud.update_job(
            db,
            job,
            transcript_original=transcript.text,
            status="transcribing",
        )

        transcript_en = transcript.text
        if transcript.language.lower() != "en":
            crud.update_job(db, job, status="translating")
            translator = TranslatorService()
            transcript_en = translator.translate_to_english(transcript.text)

        # Strip audio gốc + mix nhạc no-copyright (manual job, optional).
        # Bảo vệ khỏi copyright YT/X. Chạy SAU transcribe (transcribe đã có text)
        # và TRƯỚC launder.
        settings = get_settings()
        working_video = job.raw_video_path
        music_track = None
        if settings.strip_audio_for_manual and working_video:
            crud.update_job(db, job, status="replacing_audio")
            replacer = AudioReplacerService(settings)
            silent = replacer.strip_audio(working_video)
            try:
                mood = mood_for_tags(
                    job.source_title or "",
                    [job.source_caption or ""],
                )
                mood = replacer.refine_mood_by_energy(working_video, mood)
                music_track = replacer.pick_music(mood, target_duration=0)
                working_video = str(replacer.mix_music(silent, music_track))
            except Exception:
                logger.exception("Music mix failed for job %s, using silent video", job_id)
                working_video = str(silent)
                music_track = None
            else:
                Path(silent).unlink(missing_ok=True)

        # Laundering (anti-fingerprint) — blur bg + fg overlay + audio
        # pitch/tempo/EQ/echo. Xem plan.md (creator-x-bot) MODULE 3C.
        final_video = working_video
        if settings.enable_launder and working_video:
            crud.update_job(db, job, status="laundering")
            # Tiêu đề video luôn dùng TIẾNG ANH: ưu tiên transcript EN
            # (đã dịch ở trên), fallback sang caption/title gốc nếu rỗng.
            title = (
                (transcript_en or "").strip()
                or (job.source_caption or "").strip()
                or (job.source_title or "").strip()
            )
            try:
                final_video = VideoProcessorService().launder(
                    job.id, working_video, title_text=title or None,
                )
            except Exception as exc:
                logger.exception("Laundering failed for job %s, keeping non-laundered", job_id)
                final_video = working_video

        crud.update_job(
            db,
            job,
            transcript_en=transcript_en,
            subtitle_srt_path=None,
            output_video_path=final_video,
            music_track_path=str(music_track) if music_track else None,
        )
        enqueue_caption_job(job.id)
    except Exception as exc:
        logger.exception("Transcription failed for job %s", job_id)
        if "job" in locals() and job:
            crud.update_job(db, job, status="failed", error_message=str(exc))
    finally:
        db.close()
