"""Entry point: python -m bot.main"""

import logging

from telegram import BotCommand
from telegram.ext import Application

from .config import load_config
from .db import Database
from .handlers import register

COMMANDS = [
    BotCommand("post", "انتشار فوری پست"),
    BotCommand("schedule", "زمان‌بندی پست"),
    BotCommand("queue", "نمایش صف پست‌ها"),
    BotCommand("cancel", "لغو / حذف پست از صف"),
    BotCommand("help", "راهنما"),
]


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(COMMANDS)


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_config()
    db = Database(config.db_path)

    app = Application.builder().token(config.bot_token).post_init(_post_init).build()
    register(app, config, db)
    logging.info("Bot started; posting to %s", config.channel_id)
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
