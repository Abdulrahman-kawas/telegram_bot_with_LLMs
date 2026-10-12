"""LINE Messaging API channel: webhook in, reply/push out.

LINE has no polling — it POSTs events to our webhook, so this runs a small aiohttp server
(the bot must be reachable on a public HTTPS URL, e.g. via a cloudflared tunnel).
Shares logic.py with Telegram, so the agent behaves the same on both.

Note: LINE's free plan caps push messages at ~200/month; replies are unlimited.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request

from aiohttp import web

from uni_bot import logic, messages
from uni_bot.agent import Agent
from uni_bot.store import Store

log = logging.getLogger("uni_bot.line")

LINE_API = "https://api.line.me/v2/bot/message"


class LineChannel:
    def __init__(self, store: Store, agent: Agent, secret: str, token: str):
        self.store = store
        self.agent = agent
        self.secret = secret.encode()
        self.token = token
        self.app = web.Application()
        self.app.router.add_post("/line/webhook", self.webhook)

    async def start(self, host: str, port: int) -> None:
        runner = web.AppRunner(self.app)
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        log.info("LINE webhook listening on %s:%s/line/webhook", host, port)

    # ── incoming ──────────────────────────────────────────────────────────

    def _valid(self, body: bytes, signature: str) -> bool:
        digest = hmac.new(self.secret, body, hashlib.sha256).digest()
        return hmac.compare_digest(base64.b64encode(digest).decode(), signature or "")

    async def webhook(self, request: web.Request) -> web.Response:
        body = await request.read()
        if not self._valid(body, request.headers.get("X-Line-Signature", "")):
            return web.Response(status=403)
        try:
            events = json.loads(body).get("events", [])
        except ValueError:
            return web.Response(status=400)
        for ev in events:
            asyncio.create_task(self._handle(ev))
        return web.Response(text="OK")

    async def _handle(self, ev: dict) -> None:
        try:
            user_id = (ev.get("source") or {}).get("userId")
            if not user_id:
                return
            chat_id = f"line:{user_id}"
            reply_token = ev.get("replyToken")
            if ev.get("type") == "follow":
                await asyncio.to_thread(self._call, "reply", reply_token,
                                        messages.t(self.store.user(chat_id)["lang"], "greeting"))
            elif ev.get("type") == "message" and (ev.get("message") or {}).get("type") == "text":
                reply = await asyncio.to_thread(logic.handle_text, self.store, self.agent,
                                                chat_id, ev["message"]["text"])
                await asyncio.to_thread(self._call, "reply", reply_token, reply[:4900])
            elif ev.get("type") == "postback":
                conf = logic.handle_postback(self.store, chat_id,
                                             (ev.get("postback") or {}).get("data", ""))
                if conf:
                    await asyncio.to_thread(self._call, "reply", reply_token, conf)
        except Exception:
            log.exception("LINE event failed: %s", ev.get("type"))

    # ── outgoing ──────────────────────────────────────────────────────────

    def push(self, chat_id: str, text: str, assignment_id: str | None = None) -> None:
        """A reminder ping, with Done / Remind-me-in-an-hour quick-reply buttons."""
        message = {"type": "text", "text": text}
        if assignment_id:
            lang = self.store.user(chat_id)["lang"]
            done, snooze = messages.t(lang, "done_button"), messages.t(lang, "snooze_button")
            message["quickReply"] = {"items": [
                {"type": "action", "action": {"type": "postback", "label": done,
                                              "data": f"done:{assignment_id}",
                                              "displayText": done}},
                {"type": "action", "action": {"type": "postback", "label": snooze,
                                              "data": f"snooze:{assignment_id}:60",
                                              "displayText": snooze}},
            ]}
        self._call("push", None, None, to=chat_id.removeprefix("line:"), extra=message)

    def _call(self, kind: str, reply_token: str | None, text: str | None,
              to: str | None = None, extra: dict | None = None) -> None:
        message = extra or {"type": "text", "text": text}
        payload = ({"replyToken": reply_token, "messages": [message]} if kind == "reply"
                   else {"to": to, "messages": [message]})
        req = urllib.request.Request(
            f"{LINE_API}/{kind}", data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30):
                pass
        except urllib.error.HTTPError as e:
            log.warning("LINE %s failed: %s %s", kind, e.code, e.read()[:200])
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.warning("LINE %s unreachable: %s", kind, e)
