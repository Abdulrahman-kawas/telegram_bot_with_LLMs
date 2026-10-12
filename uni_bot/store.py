"""JSON store: users, their names/languages/history, and assignments.

Everything lives in one data.json file, written atomically under a lock — the same pattern
free_llm uses for .state.json.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

HISTORY_KEEP = 12
DEFAULT_REPING_HOURS = 3


def first_ping_at(due: float | None, now: float) -> float:
    """Ping a day before the deadline; if that's already past (or there's none), ping now."""
    if due is None:
        return now
    return max(now, due - 24 * 3600)


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        data.setdefault("users", {})
        data.setdefault("assignments", {})
        data.setdefault("seq", 0)
        return data

    def change(self, fn: Callable[[dict], Any]) -> Any:
        with self._lock:
            data = self.read()
            result = fn(data)
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
            tmp.replace(self.path)
            return result

    # ── users ─────────────────────────────────────────────────────────────

    def user(self, chat_id: int) -> dict:
        u = self.read()["users"].get(str(chat_id)) or {}
        u.setdefault("name", None)
        u.setdefault("lang", None)
        u.setdefault("history", [])
        return u

    def set_user(self, chat_id: int, **fields: Any) -> dict:
        def up(d: dict) -> dict:
            u = d["users"].setdefault(str(chat_id), {"name": None, "lang": None, "history": []})
            u.update(fields)
            return u

        return self.change(up)

    def push_history(self, chat_id: int, role: str, content: str) -> None:
        def up(d: dict) -> None:
            u = d["users"].setdefault(str(chat_id), {"name": None, "lang": None, "history": []})
            u["history"] = (u["history"] + [{"role": role, "content": content}])[-HISTORY_KEEP:]

        self.change(up)

    # ── assignments ───────────────────────────────────────────────────────

    def add_assignment(self, chat_id: str, course: str, kind: str,
                       due: float | None, next_ping: float,
                       title: str | None = None) -> dict:
        def up(d: dict) -> dict:
            d["seq"] += 1
            a = {
                "id": f"as{d['seq']}",
                "chat_id": chat_id,
                "course": course,
                "kind": kind,
                "title": title,
                "due": due,
                "done": False,
                "next_ping": next_ping,
                "created": time.time(),
            }
            d["assignments"][a["id"]] = a
            return a

        return self.change(up)

    def open_assignments(self, chat_id: str) -> list[dict]:
        return [a for a in self.read()["assignments"].values()
                if a["chat_id"] == chat_id and not a["done"]]

    def find_open(self, chat_id: str, ref: str) -> dict | None:
        """An open assignment by id, or by a course/kind fragment."""
        ref = (ref or "").strip().lower()
        open_ = self.open_assignments(chat_id)
        for a in open_:
            if a["id"] == ref:
                return a
        hits = [a for a in open_
                if ref and (ref in a["course"].lower() or ref in a["kind"].lower())]
        return hits[0] if len(hits) == 1 else None

    def update_assignment(self, assignment_id: str, **fields: Any) -> dict | None:
        def up(d: dict) -> dict | None:
            a = d["assignments"].get(assignment_id)
            if a:
                a.update(fields)
            return a

        return self.change(up)

    def due_pings(self, now: float) -> list[dict]:
        return [a for a in self.read()["assignments"].values()
                if not a["done"] and a["next_ping"] <= now]
