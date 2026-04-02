import logging

from app.db import crud
from app.db.session import SessionLocal
from app.services.transcriber import TranscriberService
from app.services.translator import TranslatorService
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

        crud.update_job(
            db,
            job,
            transcript_en=transcript_en,
            subtitle_srt_path=None,
            output_video_path=job.raw_video_path,
        )
        enqueue_caption_job(job.id)
    except Exception as exc:
        logger.exception("Transcription failed for job %s", job_id)
        if "job" in locals() and job:
            crud.update_job(db, job, status="failed", error_message=str(exc))
    finally:
        db.close()
