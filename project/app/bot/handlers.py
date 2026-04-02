from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.bot.commands import (
    add_command,
    approve_command,
    autopost_command,
    caption_command,
    help_command,
    mode_command,
    platforms_command,
    profiles_command,
    schedule_command,
    profile_command,
    reject_command,
    retry_command,
    start_command,
    status_command,
    sub_command,
)
from app.core.config import get_settings


def register_handlers(application: Application) -> None:
    settings = get_settings()
    authorized = filters.User(user_id=settings.telegram_allowed_user_ids)

    async def unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await update.message.reply_text("Unauthorized user.")

    application.add_handler(CommandHandler("start", start_command, filters=authorized))
    application.add_handler(CommandHandler("help", help_command, filters=authorized))
    application.add_handler(CommandHandler("platforms", platforms_command, filters=authorized))
    application.add_handler(CommandHandler("mode", mode_command, filters=authorized))
    application.add_handler(CommandHandler("add", add_command, filters=authorized))
    application.add_handler(CommandHandler("status", status_command, filters=authorized))
    application.add_handler(CommandHandler("approve", approve_command, filters=authorized))
    application.add_handler(CommandHandler("reject", reject_command, filters=authorized))
    application.add_handler(CommandHandler("retry", retry_command, filters=authorized))
    application.add_handler(CommandHandler("profiles", profiles_command, filters=authorized))
    application.add_handler(CommandHandler("schedule", schedule_command, filters=authorized))
    application.add_handler(CommandHandler("autopost", autopost_command, filters=authorized))
    application.add_handler(CommandHandler("profile", profile_command, filters=authorized))
    application.add_handler(CommandHandler("caption", caption_command, filters=authorized))
    application.add_handler(CommandHandler("sub", sub_command, filters=authorized))
    application.add_handler(MessageHandler(filters.COMMAND & ~authorized, unauthorized))
