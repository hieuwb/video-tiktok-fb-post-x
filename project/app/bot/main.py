import asyncio
import sys

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

    # Python 3.10+ removed implicit event loop creation in get_event_loop().
    # python-telegram-bot 22.x app.run_polling() vẫn gọi get_event_loop()
    # → fail trên 3.12+. Tự tạo loop trước.
    if sys.version_info >= (3, 10):
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

    app = build_application()
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
