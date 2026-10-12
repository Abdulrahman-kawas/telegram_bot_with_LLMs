"""Run the bot: Telegram polling always; the LINE webhook server too when its keys are set.

    TELEGRAM_BOT_TOKEN=... python -m uni_bot
    + LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, LINE_PORT (default 8080) for LINE
"""

import asyncio
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import Application

from uni_bot.agent import Agent
from uni_bot.bot import register
from uni_bot.store import Store

DATA_PATH = Path(os.environ.get("UNI_BOT_DATA")
                 or Path(__file__).resolve().parent.parent / "data.json")


async def run(token: str) -> None:
    store = Store(DATA_PATH)
    agent = Agent(store)

    line = None
    secret, line_token = os.environ.get("LINE_CHANNEL_SECRET"), os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if secret and line_token:
        from uni_bot.line_channel import LineChannel
        line = LineChannel(store, agent, secret, line_token)

    app = Application.builder().token(token).build()
    register(app, store, agent, push_line=line.push if line else None)

    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        if line:
            await line.start("0.0.0.0", int(os.environ.get("LINE_PORT", "8080")))
        logging.getLogger("uni_bot").info("bot is up (telegram%s)",
                                          " + line" if line else "")
        await asyncio.Event().wait()  # until Ctrl+C


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("set TELEGRAM_BOT_TOKEN (see .env.example)")
    try:
        asyncio.run(run(token))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
