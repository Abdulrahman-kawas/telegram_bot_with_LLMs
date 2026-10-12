"""Channel-agnostic logic: apply LLM actions, handle text and button/postback answers.

Both the Telegram handlers and the LINE webhook go through here, so behaviour is identical
on both. A chat_id is "tg:<telegram chat id>" or "line:<LINE user id>".
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

from uni_bot import messages
from uni_bot.agent import TZ, Agent
from uni_bot.store import Store, first_ping_at

log = logging.getLogger("uni_bot.logic")

VALID_SCOPES = {"week", "next", "both", "month", "all"}
_SCOPE_ALIASES = {
    "": "all", "all": "all", "week": "week", "this": "week", "this_week": "week",
    "next": "next", "next_week": "next", "both": "both", "month": "month",
    "this_month": "month",
}


def parse_scope(text: str | None) -> str:
    return _SCOPE_ALIASES.get((text or "").strip().lower().replace(" ", "_"), "all")


def date_range(scope: str, now: float) -> tuple[float | None, float | None]:
    """The [start, end) window for a scope, or (None, None) for "all"."""
    dt = datetime.fromtimestamp(now, TZ)
    today = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=dt.weekday())
    if scope == "week":
        return monday.timestamp(), (monday + timedelta(days=7)).timestamp()
    if scope == "next":
        start = monday + timedelta(days=7)
        return start.timestamp(), (start + timedelta(days=7)).timestamp()
    if scope == "both":
        return monday.timestamp(), (monday + timedelta(days=14)).timestamp()
    if scope == "month":
        first = today.replace(day=1)
        return first.timestamp(), (first + timedelta(days=32)).replace(day=1).timestamp()
    return None, None


def assignments_in_scope(store: Store, chat_id: str, scope: str, now: float | None = None) -> list[dict]:
    now = now or time.time()
    start, end = date_range(scope, now)
    open_ = store.open_assignments(chat_id)

    def keep(a: dict) -> bool:
        if start is None:
            return True
        due = a.get("due")
        return due is not None and start <= due < end

    return sorted((a for a in open_ if keep(a)), key=lambda a: a.get("due") or 0)


def list_assignments(store: Store, chat_id: str, scope: str, lang: str | None = None) -> str:
    scope = scope if scope in VALID_SCOPES else "all"
    return format_assignments(assignments_in_scope(store, chat_id, scope), lang, scope)


def short_course(course: str) -> str:
    """'What is a Company for? - Exploring ... - 2028' -> 'What is a Company for?'."""
    c = re.split(r"\s+-\s+", course or "", maxsplit=1)[0].strip()
    c = re.sub(r"\s*\b20\d\d\b\s*$", "", c).strip()
    if len(c) > 34:
        c = c[:33].rstrip() + "…"
    return c or (course or "")


def clean_title(title: str) -> str:
    """Collapse whitespace and cap the length so a list line stays readable."""
    t = re.sub(r"\s+", " ", title or "").strip()
    if len(t) > 80:
        t = t[:79].rstrip() + "…"
    return t


def format_assignments(assignments: list[dict], lang: str | None, scope: str) -> str:
    label = messages.t(lang, f"scope_{scope}")
    if not assignments:
        return (messages.t(lang, "list_empty") if scope == "all"
                else messages.t(lang, "scope_empty", label=label))
    lines = [messages.t(lang, "list_title", label=label.capitalize(), n=len(assignments))]
    current: object = object()
    for a in assignments:
        due = a.get("due")
        when = datetime.fromtimestamp(due, TZ) if due else None
        day = when.date() if when else None
        if day != current:
            current = day
            lines.append("")
            lines.append(when.strftime("%a %d %b") if when else messages.t(lang, "no_deadline"))
        course = short_course(a["course"])
        item = f"• {when.strftime('%H:%M')} — {course}" if when else f"• {course}"
        sub = clean_title(a.get("title")) or a.get("kind") or ""
        if sub and sub.lower() not in course.lower():
            item += f"\n   {sub}"
        lines.append(item)
    return "\n".join(lines)


def parse_due(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.timestamp()


def apply_actions(store: Store, chat_id: str, actions: list[dict]) -> str | None:
    """Run the LLM's actions. Returns a rendered assignment list if a `list` action fired."""
    now = time.time()
    listing = None
    for act in actions:
        kind = act.get("type")
        try:
            if kind == "set_name" and act.get("name"):
                store.set_user(chat_id, name=str(act["name"]).strip())
            elif kind == "set_lang" and act.get("lang"):
                store.set_user(chat_id, lang=str(act["lang"]).strip()[:5])
            elif kind == "add_assignment" and act.get("course"):
                due = parse_due(act.get("due"))
                a = store.add_assignment(chat_id, str(act["course"]).strip(),
                                         str(act.get("kind") or "assignment").strip(),
                                         due, first_ping_at(due, now))
                log.info("added %s for %s", a["id"], chat_id)
            elif kind == "mark_done":
                a = store.find_open(chat_id, str(act.get("id") or act.get("course") or ""))
                if a:
                    store.update_assignment(a["id"], done=True)
            elif kind == "snooze":
                minutes = max(1, int(act.get("minutes") or 60))
                target = store.find_open(chat_id, str(act.get("id") or ""))
                ids = [target["id"]] if target else [a["id"] for a in store.open_assignments(chat_id)]
                for aid in ids:
                    store.update_assignment(aid, next_ping=now + minutes * 60)
            elif kind == "list":
                lang = store.user(chat_id)["lang"]
                listing = list_assignments(store, chat_id, parse_scope(act.get("scope")), lang)
        except Exception:
            log.exception("action failed: %s", act)
    return listing


def subscribe(store: Store, chat_id: str) -> None:
    """Register the chat on first contact."""
    if str(chat_id) not in store.read()["users"]:
        store.set_user(chat_id)


def handle_text(store: Store, agent: Agent, chat_id: str, text: str) -> str:
    subscribe(store, chat_id)
    reply, actions = agent.think(chat_id, text)
    return apply_actions(store, chat_id, actions) or reply


def handle_postback(store: Store, chat_id: str, data: str) -> str | None:
    """A "done:as1" / "snooze:as1:60" answer from a button. Returns the confirmation text."""
    action, _, rest = data.partition(":")
    aid, _, extra = rest.partition(":")
    fields = ({"done": True} if action == "done" else
              {"next_ping": time.time() + int(extra or 60) * 60} if action == "snooze" else None)
    if fields is None:
        return None
    a = store.read()["assignments"].get(aid)
    if not a or a["chat_id"] != chat_id:
        return None
    a = store.update_assignment(aid, **fields)
    user = store.user(chat_id)
    lang = user["lang"]
    who = messages.t(lang, "postback_who", name=user["name"]) if user["name"] else ""
    if action == "done":
        return messages.t(lang, "done_confirm", who=who, kind=a["kind"], course=a["course"])
    return messages.t(lang, "snooze_confirm", who=who, n=int(extra or 60))
