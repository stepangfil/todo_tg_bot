import os
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from taskbot import db
from taskbot.handlers import start, on_panel_button, on_text, cmd_timezone, cmd_help
from taskbot.reminders import restore_reminders
from taskbot.recurring import start_recurring_job

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("taskbot.main")


async def _error_handler(update: object, context) -> None:
    logger.error("Unhandled exception in handler", exc_info=context.error)


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("ERROR: set BOT_TOKEN env var BOT_TOKEN")

    db.db_init()

    app = Application.builder().token(token).build()

    if app.job_queue is None:
        logger.warning("JobQueue is not available. Install: python-telegram-bot[job-queue]")
        logger.warning("Repeating reminders will NOT work without JobQueue.")

    restore_reminders(app)
    start_recurring_job(app)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("timezone", cmd_timezone))
    app.add_handler(CallbackQueryHandler(on_panel_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(_error_handler)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
