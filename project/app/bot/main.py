from telegram.ext import Application

from app.bot.handlers import register_handlers
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import init_db


def build_application() -> Application:
    settings = get_settings()
    application = Application.builder().token(settings.telegram_bot_token).build()
    register_handlers(application)
    return application


def main() -> None:
    configure_logging()
    init_db()
    app = build_application()
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
