"""The LLM brain: sends the chat to the first free model (via free_llm.Router) and reads
back a JSON envelope:

    {"reply": "what to send the user", "actions": [...]}

Actions:
    set_name        {"type": "set_name", "name": "..."}
    set_lang        {"type": "set_lang", "lang": "ar"}            (ISO code the user writes in)
    add_assignment  {"type": "add_assignment", "course": "...", "kind": "...", "due": ISO|null}
    mark_done       {"type": "mark_done", "id": "as1"}
    snooze          {"type": "snooze", "id": "as1", "minutes": 60}
    list            {"type": "list", "scope": "week"|"next"|"both"|"month"|"all"}

If the model does not return clean JSON, its whole answer is treated as the reply.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from free_llm import AllModelsFailed, Router, text_of

from uni_bot import messages
from uni_bot.store import Store

log = logging.getLogger("uni_bot.agent")

TZ = ZoneInfo("Asia/Damascus")

SYSTEM = """You are a university student's assignment-reminder assistant on Telegram.

Right now it is: {now} (Asia/Damascus).
Student's name: {name}.
The student writes in language: {lang}.

Open assignments (not done yet):
{assignments}

Rules:
- Reply in the SAME language the student used in their last message. The default language
  is English: if the student's language is unknown or you can't tell, reply in English.
- If the student's name is UNKNOWN, politely ask for it in your reply; when they tell you,
  add a set_name action.
- When the student mentions a new assignment/homework/quiz/project, add an add_assignment
  action with the course name (course), its type (kind, e.g. "assignment", "quiz",
  "project", "report"), and the deadline (due) as ISO 8601 if they gave one, else null.
  If the deadline is missing and unclear, ask about it in your reply but still add the
  assignment with due=null.
- When the student says they finished an assignment, add a mark_done action with its id.
- When the student asks to see their assignments, add ONE list action and set scope to match
  their words: "week" (this week), "next" (next week), "both" (this AND next week), "month"
  (this month), or "all" (everything / no filter). Keep your reply to one short sentence —
  the bot formats and sends the list itself, so do NOT list the assignments in your reply.
- When the student asks to be reminded later ("ذكرني بعد ساعة", "remind me in 30 minutes"),
  add a snooze action with minutes as an integer (and id of the assignment if known).
- When you can tell which language the student writes in, add a set_lang action with the
  ISO 639-1 code (e.g. "ar", "en").
- Address the student by their name once you know it.

Answer with ONLY this JSON, no other text:
{{"reply": "<your message to the student>", "actions": [<action objects, or empty>]}}"""


def _assignments_block(store: Store, chat_id: int) -> str:
    open_ = store.open_assignments(chat_id)
    if not open_:
        return "(none)"
    lines = []
    for a in open_:
        due = datetime.fromtimestamp(a["due"], TZ).strftime("%Y-%m-%d %H:%M") if a["due"] else "no deadline"
        title = f" — {a['title']}" if a.get("title") else ""
        lines.append(f"- id={a['id']}: {a['course']} — {a['kind']}{title} (due: {due})")
    return "\n".join(lines)


def _parse_actions(text: str) -> tuple[str, list[dict]]:
    """-> (reply, actions). Falls back to the raw text when it is not JSON."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return text.strip(), []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return text.strip(), []
    reply = str(data.get("reply") or "").strip()
    actions = [a for a in data.get("actions") or [] if isinstance(a, dict) and a.get("type")]
    return reply or text.strip(), actions


class Agent:
    def __init__(self, store: Store, router: Router | None = None):
        self.store = store
        self.router = router or Router()

    def think(self, chat_id: int, user_text: str) -> tuple[str, list[dict]]:
        user = self.store.user(chat_id)
        system = SYSTEM.format(
            now=datetime.now(TZ).strftime("%Y-%m-%d %H:%M (%A)"),
            name=user["name"] or "UNKNOWN",
            lang=user["lang"] or "unknown",
            assignments=_assignments_block(self.store, chat_id),
        )
        messages = [{"role": "system", "content": system}, *user["history"],
                    {"role": "user", "content": user_text}]
        try:
            answer = self.router.chat(messages, max_tokens=600)
            raw = text_of(answer)
            log.info("answered by %s", answer["x_free_llm"]["model"])
        except AllModelsFailed as exc:
            log.error("all models failed: %s", exc)
            raw = ""
        if not raw.strip():
            return messages.t(user["lang"], "model_down"), []
        reply, actions = _parse_actions(raw)
        self.store.push_history(chat_id, "user", user_text)
        self.store.push_history(chat_id, "assistant", reply)
        return reply, actions

    def reminder_text(self, chat_id: int, assignment: dict) -> str:
        """A short ping naming the course and the assignment type, in the user's language."""
        user = self.store.user(chat_id)
        due = (datetime.fromtimestamp(assignment["due"], TZ).strftime("%Y-%m-%d %H:%M")
               if assignment["due"] else None)
        named = f" named {user['name']}" if user["name"] else ""
        title = f" titled '{assignment['title']}'" if assignment.get("title") else ""
        prompt = (
            f"Write a short friendly reminder in language '{user['lang'] or messages.DEFAULT_LANG}'"
            f" for a student{named}. It MUST mention the course"
            f" name '{assignment['course']}' and the assignment type '{assignment['kind']}'{title}"
            + (f" and the deadline {due}." if due else ".")
            + " Ask if they finished it. Two or three sentences max, no JSON."
        )
        try:
            answer = self.router.chat([{"role": "user", "content": prompt}], max_tokens=200)
            text = text_of(answer).strip()
            if text:
                return text
        except AllModelsFailed:
            log.warning("reminder_text: all models failed, using template")
        lang = user["lang"]
        who = messages.t(lang, "reminder_who", name=user["name"]) if user["name"] else ""
        when = messages.t(lang, "reminder_when", due=due) if due else ""
        return messages.t(lang, "reminder_fallback", who=who, kind=assignment["kind"],
                          course=assignment["course"], when=when)
