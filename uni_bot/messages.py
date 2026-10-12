"""User-facing strings. English is the default; a few keys are translated (e.g. Arabic).

The LLM already answers in whatever language the student writes, so these cover the
fixed text the bot sends on its own: greetings, buttons, confirmations, errors, reminders.
"""

from __future__ import annotations

DEFAULT_LANG = "en"

_STRINGS: dict[str, dict[str, str]] = {
    "greeting": {
        "en": ("Hey! 👋 I'm your university assistant: I'll remind you about assignment "
               "deadlines until you're done.\nFirst up, what's your name?"),
        "ar": ("أهلاً فيك! 👋 أنا مساعدك الجامعي: بذكّرك بمواعيد تسليم الأسايمنتات لحتى تخلّصها.\n"
               "قبل ما نبلش، شو اسمك؟"),
    },
    "welcome_back": {
        "en": "Welcome back, {name}! Send /list to see your assignments.",
        "ar": "أهلاً من جديد يا {name}! /list لتشوف أسايمنتاتك.",
    },
    "list_header": {
        "en": "Open assignments:",
        "ar": "الأسايمنتات المفتوحة:",
    },
    "list_empty": {
        "en": "No open assignments 🎉",
        "ar": "ما في أي أسايمنت مفتوح 🎉",
    },
    "done_button": {"en": "✅ Done", "ar": "✅ عملتو"},
    "snooze_button": {"en": "⏰ Remind me in an hour", "ar": "⏰ ذكرني بعد ساعة"},
    "postback_who": {"en": ", {name}", "ar": " يا {name}"},
    "done_confirm": {
        "en": "Nice work{who}! ✔️ {kind} for {course} is off your list.",
        "ar": "برافو عليك{who}! ✔️ خلصنا من {kind} تبع {course}.",
    },
    "snooze_confirm": {
        "en": "Okay{who}, I'll remind you again in {n} minutes.",
        "ar": "تمام{who}، برجع بذكّرك بعد {n} دقيقة.",
    },
    "no_deadline": {"en": "no deadline", "ar": "بلا تسليم محدد"},
    "scope_week": {"en": "this week", "ar": "هذا الأسبوع"},
    "scope_next": {"en": "next week", "ar": "الأسبوع القادم"},
    "scope_both": {"en": "this & next week", "ar": "هذا والأسبوع القادم"},
    "scope_month": {"en": "this month", "ar": "هذا الشهر"},
    "scope_all": {"en": "all", "ar": "الكل"},
    "list_title": {"en": "📅 {label} — {n} assignment(s)", "ar": "📅 {label} — {n} مهمة"},
    "scope_empty": {"en": "Nothing {label} 🎉", "ar": "ما في شي {label} 🎉"},
    "model_down": {
        "en": "I couldn't reach a model right now — try again in a bit.",
        "ar": "ما قدرت أوصل للموديل هلق، جرب بعد شوي.",
    },
    "reminder_who": {"en": "{name}, ", "ar": "يا {name}، "},
    "reminder_when": {"en": " (due: {due})", "ar": " (التسليم: {due})"},
    "reminder_fallback": {
        "en": "{who}Reminder: you have a {kind} for {course}{when}. Did you finish it?",
        "ar": "{who}تذكير: عندك {kind} بمادة {course}{when}. عملتو؟",
    },
}


def t(lang: str | None, key: str, **kw: object) -> str:
    """The string for `key` in `lang` (2-letter), falling back to English, then to ""."""
    table = _STRINGS.get(key, {})
    code = (lang or DEFAULT_LANG)[:2].lower()
    text = table.get(code) or table.get(DEFAULT_LANG) or ""
    return text.format(**kw) if kw else text
