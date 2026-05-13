from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from app.core.security import detect_platform_from_url, validate_source_url
from app.core.utils import ensure_utc_datetime
from app.db import crud
from app.db.session import SessionLocal
from app.services.profile_selector import ProfileSelectorService
from app.services.publish_scheduler import PublishScheduler
from app.services.runtime_settings import RuntimeSettingsService
from app.services.telegram_notifier import TelegramNotifier
from app.workers.tasks_caption import retry_caption_generation
from app.workers.tasks_download import enqueue_processing_job
from app.workers.tasks_publish import enqueue_publish_job
from app.workers.tasks_reup import enqueue_auto_crawl


HELP_TEXT = """Huong dan su dung bot:

LUONG CHINH (auto-find → auto-edit → review):
Bot tu chay 3 lan/ngay (08h, 14h, 20h VN), moi lan crawl TikTok+YouTube,
tim 1 video silent, tu strip audio + mix nhac no-copyright + launder
anti-fingerprint, sinh caption EN, gui review card ve day. Ban /approve
hoac /reject. Approved job tu post vao slot ke tiep (14h/19h/01h VN).

/start
Bat dau va kiem tra bot dang online.

/help
Xem huong dan day du bang tieng Viet.

/platforms
Liet ke cac nen tang video dang duoc ho tro.

/mode
Xem nhanh bot dang o che do auto-post hay review thu cong.

/autopost <on|off>
Bat/tat tu dong dang bai len X ngay trong Telegram.

/profiles
Xem danh sach 4 profile ngon ngu: English, Japanese, Korean, Chinese.

/add <url> [A1-A4] [YYYY-MM-DD HH:MM]
Them link video Facebook, TikTok, Instagram hoac YouTube de xu ly, co the chon profile va lich dang theo gio Viet Nam ngay trong lenh.

/status <job_id>
Xem tien do xu ly, caption, profile, output va loi neu co.

/profile <job_id> <A1-A4>
Ep job dung profile cu the thay vi profile theo khung gio.

/caption <job_id>
Xem nhanh caption da tao cho job.

/schedule <job_id> YYYY-MM-DD HH:MM
Dat lich dang bai theo gio Viet Nam (ICT, UTC+7).

/sub <job_id>
Thong bao rang subtitle da duoc tat.

/retry <job_id>
Chay lai job neu job dang fail hoac can xu ly lai.

/approve <job_id>
Duyet va dang bai len tat ca (X + YouTube + Facebook).

/approve_x <job_id>
Chi dang len X.

/approve_yt <job_id>
Chi dang len YouTube.

/approve_fb <job_id>
Chi dang len Facebook.

/reject <job_id>
Tu choi job va dung dang bai.

/find  hoac  /crawl_now
Trigger auto-crawl TikTok+YouTube ngay, khong doi cron 3 lan/ngay.

/queue
Xem danh sach job dang awaiting_review."""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Bot Telegram -> X da san sang.\nDung /help de xem huong dan."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def platforms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Nen tang dang ho tro:\n- Facebook\n- TikTok (manual + auto-crawl)\n- Instagram\n- YouTube (manual + auto-crawl)"
    )


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime = RuntimeSettingsService()
    autopost = runtime.get_auto_post_enabled()
    require_approval = runtime.get_require_approval_before_post()
    mode = "auto-post" if autopost and not require_approval else "review"
    detail = (
        "Bot se tu dang len X sau khi caption xong."
        if autopost and not require_approval
        else "Bot se dung o awaiting_review va cho /approve."
    )
    await update.message.reply_text(
        f"Che do hien tai: {mode}\nAuto-post: {'on' if autopost else 'off'}\nRequire approval: {'on' if require_approval else 'off'}\n{detail}"
    )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parsed = parse_add_arguments(context.args)
    if not parsed:
        await update.message.reply_text("Cach dung: /add <link_facebook|tiktok|instagram|youtube> [A1-A4] [YYYY-MM-DD HH:MM]")
        return
    url, profile_code, scheduled_utc = parsed
    if not validate_source_url(url):
        await update.message.reply_text("Link khong hop le hoac chua duoc ho tro.")
        return

    target_language = None
    if profile_code:
        selector = ProfileSelectorService()
        if profile_code not in selector.settings.caption_profiles_json:
            await update.message.reply_text("Profile khong hop le. Hay dung A1-A4.")
            return
        target_language = selector.get_profile(profile_code).language

    db = SessionLocal()
    try:
        job = crud.create_job(
            db,
            source_url=url,
            source_platform=detect_platform_from_url(url),
            status="queued",
        )
        if profile_code and target_language:
            job = crud.set_job_profile(db, job, profile_code, target_language)
        if scheduled_utc:
            job = crud.set_job_schedule(db, job, scheduled_utc)
        enqueue_processing_job(job.id)
        profile_text = f" Profile: {job.selected_profile}." if job.selected_profile else ""
        schedule_text = ""
        if scheduled_utc:
            schedule_text = f" Schedule: {scheduled_utc.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%Y-%m-%d %H:%M ICT')}."
        await update.message.reply_text(
            f"Da tao job {job.id} cho nen tang {job.source_platform}. Trang thai hien tai: {job.status}.{profile_text}{schedule_text}"
        )
    finally:
        db.close()


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job_id = await _get_job_from_args(update, context)
    if not job_id:
        return
    db = SessionLocal()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            await update.message.reply_text("Khong tim thay job.")
            return
        notifier = TelegramNotifier()
        await update.message.reply_text(notifier.format_job_status(job))
    finally:
        db.close()


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _approve_job(update, context, targets="all")


async def approve_x_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _approve_job(update, context, targets="x")


async def approve_yt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _approve_job(update, context, targets="youtube")


async def approve_fb_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _approve_job(update, context, targets="facebook")


async def _approve_job(update: Update, context: ContextTypes.DEFAULT_TYPE, targets: str) -> None:
    job_id = await _get_job_from_args(update, context)
    if not job_id:
        return
    db = SessionLocal()
    try:
        refreshed = crud.get_job(db, job_id)
        if not refreshed:
            await update.message.reply_text("Khong tim thay job.")
            return
        if refreshed.status != "awaiting_review":
            await update.message.reply_text(
                f"Job {refreshed.id} dang o trang thai {refreshed.status}, khong phai awaiting_review."
            )
            return

        # Gán slot tự động nếu user chưa /schedule. 3 slot/ngày trong window
        # 13:00-02:00 VN — slot dispatcher chạy 5p/lần sẽ kích publish khi tới giờ.
        if not refreshed.scheduled_publish_at:
            try:
                slot = PublishScheduler().next_slot_utc(db)
                refreshed = crud.set_job_schedule(db, refreshed, slot)
            except Exception:
                # Fallback: publish ngay nếu scheduler lỗi (vd: POST_SLOTS_VN rỗng).
                pass

        crud.update_job(
            db,
            refreshed,
            status="approved",
            approved_at=datetime.now(timezone.utc),
            error_message=None,
        )
        # KHÔNG enqueue publish ngay — slot dispatcher (beat 5p/lần) sẽ pick up
        # khi tới giờ. Trường hợp user /schedule sớm hơn now → vẫn dispatch tới.

        label = {"all": "X + YouTube + Facebook", "both": "X + YouTube", "x": "chỉ X", "youtube": "chỉ YouTube", "facebook": "chỉ Facebook"}.get(targets, targets)
        message = f"Da duyet job {refreshed.id} ({label})"
        scheduled_publish_at = ensure_utc_datetime(refreshed.scheduled_publish_at)
        if scheduled_publish_at:
            schedule_vn = scheduled_publish_at.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M ICT")
            message += f" — slot publish: {schedule_vn}."
        else:
            # Không có slot → publish ngay (fallback path).
            enqueue_publish_job(refreshed.id, targets=targets)
            message += " (publish ngay vì khong co slot trong)."
        await update.message.reply_text(message)
    finally:
        db.close()


async def crawl_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    enqueue_auto_crawl()
    await update.message.reply_text("Da trigger auto-crawl ngay. Theo doi qua /queue.")


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = SessionLocal()
    try:
        awaiting = crud.list_jobs_by_status(db, "awaiting_review", limit=20)
        approved = crud.list_jobs_by_status(db, "approved", limit=20)
        vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
        lines: list[str] = []

        if approved:
            lines.append(f"Approved (waiting slot, {len(approved)}):")
            for job in approved:
                slot_text = "-"
                if job.scheduled_publish_at:
                    slot_text = ensure_utc_datetime(job.scheduled_publish_at).astimezone(vn_tz).strftime(
                        "%H:%M %d/%m"
                    )
                title = (job.source_title or "")[:50]
                lines.append(f"#{job.id} [{job.source_platform}] {title} | slot {slot_text}")
            lines.append("")

        if awaiting:
            lines.append(f"Awaiting_review ({len(awaiting)}):")
            for job in awaiting:
                expires = "-"
                if job.review_expires_at:
                    expires = ensure_utc_datetime(job.review_expires_at).astimezone(vn_tz).strftime(
                        "%H:%M %d/%m"
                    )
                title = (job.source_title or "")[:50]
                lines.append(f"#{job.id} [{job.source_platform}] {title} | expires {expires}")

        if not lines:
            await update.message.reply_text("Queue trong (khong co job awaiting_review/approved).")
            return
        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job_id = await _get_job_from_args(update, context)
    if not job_id:
        return
    db = SessionLocal()
    try:
        refreshed = crud.get_job(db, job_id)
        if not refreshed:
            await update.message.reply_text("Khong tim thay job.")
            return
        crud.update_job(db, refreshed, status="rejected")
        await update.message.reply_text(f"Da tu choi job {refreshed.id}.")
    finally:
        db.close()


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job_id = await _get_job_from_args(update, context)
    if not job_id:
        return
    enqueue_processing_job(job_id)
    await update.message.reply_text(f"Dang chay lai job {job_id}.")


async def profiles_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    selector = ProfileSelectorService()
    lines = ["Danh sach profile caption hien tai:"]
    for code, payload in selector.settings.caption_profiles_json.items():
        lines.append(
            f"{code}: {payload['language_name']} | style={payload['style']} | tone={payload['tone']}"
        )
    await update.message.reply_text("\n".join(lines))


async def autopost_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime = RuntimeSettingsService()
    if not context.args:
        status = "on" if runtime.get_auto_post_enabled() else "off"
        await update.message.reply_text(
            f"Auto-post hien dang {status}. Dung /autopost on|off de thay doi."
        )
        return

    desired = context.args[0].strip().lower()
    if desired not in {"on", "off"}:
        await update.message.reply_text("Cach dung: /autopost on|off")
        return

    enabled = desired == "on"
    runtime.set_post_mode(enabled)
    await update.message.reply_text(
        f"Da chuyen auto-post sang {'on' if enabled else 'off'}. Require approval hien dang {'off' if enabled else 'on'}."
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Cach dung: /profile <job_id> <A1-A4>")
        return
    if len(context.args) == 1:
        maybe_job_id = await _get_job_from_args(update, context)
        if not maybe_job_id:
            return
        db2 = SessionLocal()
        try:
            maybe_job = crud.get_job(db2, maybe_job_id)
            if not maybe_job:
                await update.message.reply_text("Khong tim thay job.")
                return
            await update.message.reply_text(
                f"Job {maybe_job.id} dang dung profile: {maybe_job.selected_profile or '-'} | ngon ngu: {maybe_job.target_language or '-'}"
            )
        finally:
            db2.close()
        return

    try:
        job_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("job_id phai la so nguyen.")
        return

    profile_code = context.args[1].upper().strip()
    selector = ProfileSelectorService()
    if profile_code not in selector.settings.caption_profiles_json:
        await update.message.reply_text("Profile khong hop le. Hay dung A1-A4.")
        return
    profile = selector.get_profile(profile_code)

    db = SessionLocal()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            await update.message.reply_text("Khong tim thay job.")
            return
        if job.status in {"posted", "publishing"}:
            await update.message.reply_text(
                f"Job {job.id} da o trang thai {job.status}; khong the doi profile nua."
            )
            return
        crud.set_job_profile(db, job, profile.code, profile.language)
        if job.transcript_en or job.transcript_original:
            retry_caption_generation(job.id)
            await update.message.reply_text(
                f"Job {job.id} da chuyen sang profile {profile.code} ({profile.language_name}). Da dua caption regeneration vao queue."
            )
        else:
            await update.message.reply_text(
                f"Job {job.id} se dung profile {profile.code} ({profile.language_name}) khi bat dau tao caption."
            )
    finally:
        db.close()


async def caption_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job_id = await _get_job_from_args(update, context)
    if not job_id:
        return
    db = SessionLocal()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            await update.message.reply_text("Khong tim thay job.")
            return
        text = "\n".join(
            [
                f"Job {job.id}",
                f"Selected: {job.selected_caption or '-'}",
                f"Profile: {job.selected_profile or '-'}",
                f"Language: {job.target_language or '-'}",
                f"Primary: {job.ai_caption_primary or '-'}",
                f"Alt 1: {job.ai_caption_alt_1 or '-'}",
                f"Alt 2: {job.ai_caption_alt_2 or '-'}",
                f"Hashtags: {job.hashtags or '-'}",
            ]
        )
        await update.message.reply_text(text)
    finally:
        db.close()


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 3:
        await update.message.reply_text("Cach dung: /schedule <job_id> YYYY-MM-DD HH:MM")
        return

    try:
        job_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("job_id phai la so nguyen.")
        return

    datetime_text = f"{context.args[1].strip()} {context.args[2].strip()}"
    try:
        vietnam_tz = ZoneInfo("Asia/Ho_Chi_Minh")
        scheduled_vn = datetime.strptime(datetime_text, "%Y-%m-%d %H:%M").replace(tzinfo=vietnam_tz)
        scheduled_utc = scheduled_vn.astimezone(timezone.utc)
    except ValueError:
        await update.message.reply_text("Sai dinh dang. Vi du: /schedule 12 2026-04-02 19:30")
        return

    if scheduled_utc <= datetime.now(timezone.utc):
        await update.message.reply_text("Thoi gian dat lich phai o tuong lai theo gio Viet Nam.")
        return

    db = SessionLocal()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            await update.message.reply_text("Khong tim thay job.")
            return

        job = crud.set_job_schedule(db, job, scheduled_utc)
        if job.status == "approved":
            enqueue_publish_job(job.id, eta=ensure_utc_datetime(job.scheduled_publish_at))
        await update.message.reply_text(
            f"Da dat lich job {job.id} luc {scheduled_vn.strftime('%Y-%m-%d %H:%M ICT')}."
        )
    finally:
        db.close()


def parse_add_arguments(args: list[str]) -> tuple[str, str | None, datetime | None] | None:
    if not args:
        return None

    url = args[0].strip()
    if not url:
        return None

    vietnam_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    profile_code: str | None = None
    scheduled_utc = None

    if len(args) == 1:
        return url, None, None

    if len(args) == 2:
        profile_code = args[1].strip().upper() or None
        return url, profile_code, None

    if len(args) != 4:
        return None

    profile_code = args[1].strip().upper() or None
    try:
        scheduled_vn = datetime.strptime(f"{args[2].strip()} {args[3].strip()}", "%Y-%m-%d %H:%M").replace(
            tzinfo=vietnam_tz
        )
        scheduled_utc = scheduled_vn.astimezone(timezone.utc)
    except ValueError:
        return None

    return url, profile_code, scheduled_utc


async def sub_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Subtitle da duoc tat trong pipeline hien tai.")


async def recaption_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job_id = await _get_job_from_args(update, context)
    if not job_id:
        return
    retry_caption_generation(job_id)
    await update.message.reply_text(f"Da dua caption regeneration cua job {job_id} vao queue.")


async def _get_job_from_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return job_id (int) if valid, else None. Does NOT return ORM object."""
    if not context.args:
        if update.message:
            await update.message.reply_text("Can truyen <job_id>.")
        return None
    try:
        job_id = int(context.args[0])
    except ValueError:
        if update.message:
            await update.message.reply_text("job_id phai la so nguyen.")
        return None

    db = SessionLocal()
    try:
        job = crud.get_job(db, job_id)
        if not job:
            if update.message:
                await update.message.reply_text("Khong tim thay job.")
            return None
        return job_id
    finally:
        db.close()
