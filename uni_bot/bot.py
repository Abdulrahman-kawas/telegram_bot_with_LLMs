"""Telegram side: thin handlers over logic.py, plus the reminder loop.

The reminder loop also serves LINE chats (chat_id "line:...") when a LINE pusher is
registered, so both channels share one scheduler.
"""

from __future__ import annotations

import asyncio
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from uni_bot import logic, messages
from uni_bot.agent import Agent
from uni_bot.store import DEFAULT_REPING_HOURS, Store

log = logging.getLogger("uni_bot")

def ping_keyboard(assignment_id: str, lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(messages.t(lang, "done_button"), callback_data=f"done:{assignment_id}"),
        InlineKeyboardButton(messages.t(lang, "snooze_button"), callback_data=f"snooze:{assignment_id}:60"),
    ]])


def tg_id(update: Update) -> str:
    return f"tg:{update.effective_chat.id}"


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    store: Store = ctx.application.bot_data["store"]
    chat_id = tg_id(update)
    logic.subscribe(store, chat_id)
    user = store.user(chat_id)
    if user["name"]:
        await update.message.reply_text(messages.t(user["lang"], "welcome_back", name=user["name"]))
    else:
        await update.message.reply_text(messages.t(user["lang"], "greeting"))


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    store: Store = ctx.application.bot_data["store"]
    chat_id = tg_id(update)
    lang = store.user(chat_id)["lang"]
    parts = (update.message.text or "").split(maxsplit=1)
    scope = logic.parse_scope(parts[1] if len(parts) > 1 else "")
    await update.message.reply_text(logic.list_assignments(store, chat_id, scope, lang)[:4000])


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    store: Store = ctx.application.bot_data["store"]
    agent: Agent = ctx.application.bot_data["agent"]
    reply = await asyncio.to_thread(logic.handle_text, store, agent, tg_id(update),
                                    update.message.text)
    await update.message.reply_text(reply[:4000])


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    store: Store = ctx.application.bot_data["store"]
    confirmation = logic.handle_postback(store, tg_id(update), query.data)
    if confirmation is None:
        return
    await query.edit_message_reply_markup(None)
    await query.message.reply_text(confirmation)


async def reminder_tick(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    store: Store = ctx.application.bot_data["store"]
    agent: Agent = ctx.application.bot_data["agent"]
    push_line = ctx.application.bot_data.get("push_line")
    now = time.time()
    for a in store.due_pings(now):
        # re-arm first so a send failure never causes a flood
        store.update_assignment(a["id"], next_ping=now + DEFAULT_REPING_HOURS * 3600)
        try:
            text = await asyncio.to_thread(agent.reminder_text, a["chat_id"], a)
            if a["chat_id"].startswith("line:") and push_line:
                await asyncio.to_thread(push_line, a["chat_id"], text[:4000], a["id"])
            else:
                lang = store.user(a["chat_id"])["lang"]
                await ctx.bot.send_message(int(a["chat_id"].removeprefix("tg:")),
                                           text[:4000], reply_markup=ping_keyboard(a["id"], lang))
        except Exception:
            log.exception("ping failed for %s", a["id"])


def register(app: Application, store: Store, agent: Agent, push_line=None) -> None:
    app.bot_data["store"] = store
    app.bot_data["agent"] = agent
    app.bot_data["push_line"] = push_line
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.job_queue.run_repeating(reminder_tick, interval=60, first=10)
