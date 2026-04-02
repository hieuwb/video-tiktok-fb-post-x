from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.core.security import detect_platform_from_url, validate_source_url
from app.db import crud
from app.db.session import SessionLocal
from app.services.profile_selector import ProfileSelectorService
from app.services.runtime_settings import RuntimeSettingsService
from app.services.telegram_notifier import TelegramNotifier
from app.workers.tasks_caption import retry_caption_generation
from app.workers.tasks_download import enqueue_processing_job
from app.workers.tasks_publish import enqueue_publish_job


HELP_TEXT = """Huong dan su dung bot:

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

/add <url> [A1-A4]
Them link video Facebook, TikTok hoac Instagram de xu ly, co the chon profile ngay trong lenh.

/status <job_id>
Xem tien do xu ly, caption, profile, output va loi neu co.

/profile <job_id> <A1-A4>
Ep job dung profile cu the thay vi profile theo khung gio.

/caption <job_id>
Xem nhanh caption da tao cho job.

/sub <job_id>
Thong bao rang subtitle da duoc tat.

/retry <job_id>
Chay lai job neu job dang fail hoac can xu ly lai.

/approve <job_id>
Duyet dang bai len X khi dang o che do review.

/reject <job_id>
Tu choi job va dung dang bai."""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Bot Telegram -> X da san sang.\nDung /help de xem huong dan."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def platforms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Nen tang dang ho tro:\n- Facebook\n- TikTok\n- Instagram"
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
        await update.message.reply_text("Cach dung: /add <link_facebook_or_tiktok_or_instagram> [A1-A4]")
        return
    url, profile_code = parsed
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
        enqueue_processing_job(job.id)
        profile_text = f" Profile: {job.selected_profile}." if job.selected_profile else ""
        await update.message.reply_text(
            f"Da tao job {job.id} cho nen tang {job.source_platform}. Trang thai hien tai: {job.status}.{profile_text}"
        )
    finally:
        db.close()


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job = await _get_job_from_args(update, context)
    if not job:
        return
    notifier = TelegramNotifier()
    await update.message.reply_text(notifier.format_job_status(job))


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job = await _get_job_from_args(update, context)
    if not job:
        return
    db = SessionLocal()
    try:
        refreshed = crud.get_job(db, job.id)
        if not refreshed:
            await update.message.reply_text("Khong tim thay job.")
            return
        if refreshed.status != "awaiting_review":
            await update.message.reply_text(
                f"Job {refreshed.id} dang o trang thai {refreshed.status}, khong phai awaiting_review."
            )
            return
        crud.mark_job_approved(db, refreshed)
        enqueue_publish_job(refreshed.id)
        await update.message.reply_text(f"Da duyet job {refreshed.id} va dua vao hang doi publish.")
    finally:
        db.close()


async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job = await _get_job_from_args(update, context)
    if not job:
        return
    db = SessionLocal()
    try:
        refreshed = crud.get_job(db, job.id)
        if not refreshed:
            await update.message.reply_text("Khong tim thay job.")
            return
        crud.update_job(db, refreshed, status="rejected")
        await update.message.reply_text(f"Da tu choi job {refreshed.id}.")
    finally:
        db.close()


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job = await _get_job_from_args(update, context)
    if not job:
        return
    enqueue_processing_job(job.id)
    await update.message.reply_text(f"Dang chay lai job {job.id}.")


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
        maybe_job = await _get_job_from_args(update, context)
        if not maybe_job:
            return
        await update.message.reply_text(
            f"Job {maybe_job.id} dang dung profile: {maybe_job.selected_profile or '-'} | ngon ngu: {maybe_job.target_language or '-'}"
        )
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
    job = await _get_job_from_args(update, context)
    if not job:
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


def parse_add_arguments(args: list[str]) -> tuple[str, str | None] | None:
    if not args:
        return None

    url = args[0].strip()
    if not url:
        return None

    profile_code = None
    if len(args) > 1:
        profile_code = args[1].strip().upper() or None

    return url, profile_code


async def sub_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Subtitle da duoc tat trong pipeline hien tai.")


async def recaption_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    job = await _get_job_from_args(update, context)
    if not job:
        return
    retry_caption_generation(job.id)
    await update.message.reply_text(f"Da dua caption regeneration cua job {job.id} vao queue.")


async def _get_job_from_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        if not job and update.message:
            await update.message.reply_text("Khong tim thay job.")
        return job
    finally:
        db.close()
