"""Daily cleanup: xóa file media cũ + enforce dung lượng tối đa.

Beat schedule: 04:30 UTC mỗi ngày (= 11:30 VN, ngoài window post 13-02).

Logic:
  1. Job đã `posted` quá `RETENTION_DAYS_POSTED` ngày → xoá file (raw/audio/output/preview),
     đổi status = "archived", giữ DB row để analytics.
  2. Job `failed/expired/rejected/archived` quá `RETENTION_DAYS_FAILED` ngày → xoá
     file + xoá hẳn DB row.
  3. Nếu tổng dung lượng `storage/` vẫn vượt `STORAGE_MAX_GB`, tiếp tục xoá file
     cũ nhất (theo mtime) trong raw/output/audio cho đến khi dưới ngưỡng.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.db import crud
from app.db.session import SessionLocal
from app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


_FILE_FIELDS = (
    "raw_video_path",
    "audio_path",
    "subtitle_srt_path",
    "output_video_path",
    "preview_video_path",
    "preview_thumbnail_path",
    "music_track_path",
)


@celery_app.task(name="app.workers.tasks_cleanup.cleanup_storage")
def cleanup_storage() -> dict:
    settings = get_settings()
    db = SessionLocal()
    summary = {"archived": 0, "purged": 0, "files_deleted": 0, "bytes_freed": 0}
    try:
        now_utc = datetime.now(timezone.utc)

        # 1) Archive job posted cũ
        archive_cutoff = now_utc - timedelta(days=settings.retention_days_posted)
        for job in crud.list_archive_candidates(db, archive_cutoff):
            freed = _delete_job_files(job)
            summary["files_deleted"] += freed["count"]
            summary["bytes_freed"] += freed["bytes"]
            crud.update_job(
                db,
                job,
                status="archived",
                **{field: None for field in _FILE_FIELDS},
            )
            summary["archived"] += 1

        # 2) Purge job terminal cũ
        purge_cutoff = now_utc - timedelta(days=settings.retention_days_failed)
        for job in crud.list_purge_candidates(db, purge_cutoff):
            freed = _delete_job_files(job)
            summary["files_deleted"] += freed["count"]
            summary["bytes_freed"] += freed["bytes"]
            db.delete(job)
            summary["purged"] += 1
        db.commit()

        # 3) Emergency: nếu vẫn over storage_max_gb, xoá file cũ nhất.
        max_bytes = int(settings.storage_max_gb * 1024 * 1024 * 1024)
        used = _dir_size(Path(settings.storage_root))
        if used > max_bytes:
            extra = _enforce_storage_ceiling(settings, max_bytes)
            summary["files_deleted"] += extra["count"]
            summary["bytes_freed"] += extra["bytes"]

        logger.info("cleanup_storage summary: %s", summary)
        return summary
    finally:
        db.close()


def _delete_job_files(job) -> dict:
    count = 0
    total_bytes = 0
    for field in _FILE_FIELDS:
        path_str = getattr(job, field, None)
        if not path_str:
            continue
        path = Path(path_str)
        if not path.exists() or not path.is_file():
            continue
        try:
            size = path.stat().st_size
            path.unlink()
            count += 1
            total_bytes += size
        except OSError as exc:
            logger.warning("Failed to delete %s: %s", path, exc)
    return {"count": count, "bytes": total_bytes}


def _dir_size(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _enforce_storage_ceiling(settings, max_bytes: int) -> dict:
    """Xoá file cũ nhất trong raw/output/audio/transcript cho đến khi total ≤ max_bytes."""
    candidates: list[Path] = []
    for sub in (
        settings.raw_video_dir,
        settings.audio_dir,
        settings.output_video_dir,
        settings.transcript_dir,
        settings.subtitle_dir,
    ):
        for path in Path(sub).rglob("*"):
            if path.is_file():
                candidates.append(path)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0)

    used = _dir_size(Path(settings.storage_root))
    count = 0
    freed = 0
    for path in candidates:
        if used <= max_bytes:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            used -= size
            freed += size
            count += 1
        except OSError as exc:
            logger.warning("Cannot evict %s: %s", path, exc)
    if count:
        logger.warning("Storage ceiling enforced: evicted %d file(s), freed %.1f MB", count, freed / 1024 / 1024)
    return {"count": count, "bytes": freed}
