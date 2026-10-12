# telegram_bot_with_LLMs

A personal university-assignment reminder bot for Telegram and LINE, powered entirely by
free LLM providers. Tell it about an assignment in plain language, and it
reminds you before the deadline, asks "did you finish it?", and keeps asking until you say
yes — or until you tell it to remind you later.

## What it does

- **Readable, filtered lists** — `/list` groups deadlines by day, with the time and a
  short course name and the assignment title. Ask in plain
  language for a window — "this week", "next week", "this week and next", "this month" —
  or use `/list week|next|both|month|all`.
- **Reminds you before deadlines** — a first ping 24 hours before the due date, then every
  3 hours until you mark it done. Every reminder carries two buttons:
  **✅ Done** and **⏰ Remind me in an hour** — so the common answers never even need the LLM.
- **Talks any language** — the LLM answers in whatever language you use and stores your
  preference, so reminder pings are written in your language too.
- **Knows your name** — on first contact it asks for your name and addresses you with it
  from then on.
- **Each user tracks their own assignments** — anyone can subscribe with just their name;
  everyone's list, done marks, and snoozes are separate.
- **Understands natural requests** — "remind me in an hour", "I finished the stats quiz",
  "I have a marketing report due Friday" are all handled by the LLM through structured
  actions (add / mark done / snooze).
- **Costs $0 for the brain** — all LLM calls go through
  [free-llms](https://github.com/Abdulrahman-kawas/free-llms), a router that walks a list
  of free providers (Gemini, Groq, Z AI, Ollama Cloud, Cloudflare) and falls over to the
  next one whenever a model is rate-limited, resting, or out of daily quota.
- **Two channels, one brain** — Telegram (long polling, no open ports needed) and LINE
  (Messaging API webhook) share the same agent, storage, and reminder scheduler.

## Project layout

```
uni_bot/
  __main__.py      entry point: Telegram polling + optional LINE webhook server
  bot.py           Telegram handlers and the reminder loop
  line_channel.py  LINE webhook (aiohttp), reply/push with quick-reply buttons
  logic.py         channel-agnostic logic: LLM actions, buttons, text handling
  agent.py         the LLM brain: prompts free_llm.Router, parses JSON actions
  messages.py      fixed user-facing strings (English default, Arabic)
  store.py         atomic JSON store (users, names, languages, assignments)
free-llms/         free LLM router (git submodule)
deploy/
  setup.sh         one-shot installer for any Ubuntu VM
  uni-bot.service  systemd unit (auto-restart, state in /var/lib/uni-bot)
```

## Setup

1. **Install dependencies** (Python 3.11+):
   ```bash
   git clone --recursive https://github.com/Abdulrahman-kawas/telegram_bot_with_LLMs.git
   cd telegram_bot_with_LLMs
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
2. **Add at least one free LLM key** in `free-llms/.env` (see `free-llms/.env.example`
   for where to get each key — Groq and Gemini are the quickest). Providers without a key
   are simply skipped.
3. **Create a Telegram bot** with [@BotFather](https://t.me/BotFather) and put the token
   in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=...
   ```
4. **Run:**
   ```bash
   export TELEGRAM_BOT_TOKEN=...
   .venv/bin/python -m uni_bot
   ```
5. In Telegram, send `/start` and your name, then tell the bot about your assignments
   ("I have a stats quiz on Monday at 10"). `/list` shows your open
   assignments at any time (`/list week` for just this week, `/list next`, `/list both`,
   `/list month`, or `/list all`).

### LINE (optional)

LINE has no polling, so the webhook needs a public HTTPS URL:

1. Create a Messaging API channel at [developers.line.biz](https://developers.line.biz)
   and set `LINE_CHANNEL_SECRET` and `LINE_CHANNEL_ACCESS_TOKEN` in `.env`.
2. Expose port 8080, e.g. `cloudflared tunnel --url http://localhost:8080`, and set the
   webhook URL in the LINE console to `https://<your-url>/line/webhook`.
3. Restart the bot. If the LINE variables are empty, the bot runs Telegram-only.

Note: LINE's free plan caps push messages at roughly 200/month (replies are unlimited);
Telegram has no such cap.

## Deployment (AWS or any Ubuntu VM)

The bot is tiny — a `t4g.micro` (~$6/month, or covered by new-account free credits) is
more than enough. Telegram needs **no inbound ports** (outbound polling only), so the
security group can allow just SSH, and no Elastic IP is required. A truly free alternative
is Oracle Cloud's Always Free VM — the same installer works there unchanged.

```bash
# from your machine:
rsync -av --exclude .venv --exclude .git ./ ubuntu@<server-ip>:~/telegram_bot_with_LLMs/
# on the server:
cd ~/telegram_bot_with_LLMs && bash deploy/setup.sh
sudo nano /opt/uni-bot/.env               # TELEGRAM_BOT_TOKEN (+ LINE_* if wanted)
sudo nano /opt/uni-bot/free-llms/.env     # at least one free LLM key
sudo systemctl restart uni-bot
sudo journalctl -u uni-bot -f             # logs
```

`deploy/setup.sh` installs dependencies, syncs the project to `/opt/uni-bot`, and enables
a systemd service that starts on boot and restarts on failure. Bot data and the free-llm
state live in `/var/lib/uni-bot/`. Re-running the same two commands after local changes
deploys an update.

## Notes

- Reminders and chat run even if a model fails: the router tries the next free provider,
  and reminder pings fall back to a built-in template if every provider is down.
- Free LLM providers may train on what you send them; don't paste secrets into the chat.
