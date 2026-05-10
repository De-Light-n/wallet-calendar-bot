# wallet-calendar-bot

Personal AI assistant that manages **Google Calendar events** and a **personal
finance ledger** (Google Sheets) through a chat interface — Telegram, Slack,
Discord, or the built-in web dashboard. Both text and voice messages are
supported; voice notes are transcribed via Whisper before being routed to the
agent.

## Highlights

- 🤖 **Function-calling agent** — single LLM loop creates calendar events,
  records expenses/income, lists upcoming events, updates and deletes events.
- 📨 **Multi-channel** — one orchestrator, four ingress paths (Telegram bot,
  Slack Events API, Discord Gateway client, web chat).
- 💱 **Native multi-currency** — every transaction stores both the original
  amount and a base-currency conversion using NBU FX rates with per-day caching.
- 📊 **Live spreadsheet dashboard** — provisioned per-user with three sheets
  (Dashboard, Transactions, Monthly, Categories) and three embedded charts.
- 🔐 **Google OAuth + PKCE** — single sign-in unlocks Calendar, Sheets, and
  Drive scopes; messaging accounts are bound through short-lived link codes.
- 🌐 **React dashboard** — Vite + TanStack Query SPA with finance summary,
  calendar grid, recent transactions, and chat panel.

## Architecture

```
wallet-calendar-bot/
│
├── app/
│   ├── main.py                    # FastAPI app + Telegram webhook/polling
│   │                                + Discord client lifecycle
│   │
│   ├── core/                      # Cross-cutting infrastructure
│   │   ├── config.py              # Typed AppSettings loaded from env
│   │   └── context.py             # AgentRequestContext (channel, tz, ...)
│   │
│   ├── agent/                     # LLM layer
│   │   ├── llm_client.py          # Function-calling loop with retries
│   │   ├── orchestrator.py        # Channel-agnostic message dispatcher
│   │   ├── tool_registry.py       # Pluggable tool registration / dispatch
│   │   ├── system_prompts.py      # System prompt with timezone/calendar/
│   │   │                            finance rules
│   │   └── stt.py                 # Voice → text via Groq Whisper
│   │
│   ├── tools/                     # Agent-callable tools
│   │   ├── calendar_tool.py       # Google Calendar: create/update/delete/list
│   │   ├── finance_tool.py        # Sheets ledger + dashboard provisioning
│   │   └── google_utils.py        # Shared Google API retry helper
│   │
│   ├── auth/                      # Web authentication
│   │   ├── google_oauth.py        # PKCE flow helpers
│   │   ├── routes.py              # /auth/google/init|callback, /me, /logout
│   │   ├── dependencies.py        # current_user FastAPI dependency
│   │   └── link_codes.py          # Short-lived chat-account binding codes
│   │
│   ├── channels/                  # Per-channel adapters and ingress routes
│   │   ├── base.py                # ChannelAdapter contract
│   │   ├── telegram.py            # Telegram normaliser
│   │   ├── slack.py / slack_client.py
│   │   ├── discord.py / discord_bot.py
│   │   ├── webchat.py
│   │   └── routes.py              # /api/channels/* webhooks
│   │
│   ├── api/                       # Authenticated dashboard API
│   │   └── me.py                  # /api/me/{transactions,calendar,...}
│   │
│   ├── bot/                       # Telegram aiogram handlers
│   │   ├── handlers.py            # /start, /link, /currency, /new_sheet, text, voice
│   │   └── utils.py               # Voice download helper
│   │
│   ├── integrations/              # Third-party clients
│   │   └── fx.py                  # NBU exchange-rate fetcher + per-day cache
│   │
│   └── database/
│       ├── models.py              # User, ChannelAccount, OAuthToken,
│       │                            Expense, ExchangeRate, LinkCode
│       └── session.py             # Engine, session factory, init_db()
│
├── frontend/                      # React + TypeScript dashboard (Vite)
├── tests/                         # Pytest suite
├── docs/                          # Architecture diagrams + setup notes
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

### Request lifecycle

```
   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
   │ Telegram  │   │   Slack   │   │  Discord  │   │  Web SPA  │
   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
         │ webhook /     │ event API     │ gateway       │ session cookie
         │ polling       │ webhook       │ websocket     │ /api/me/chat
         ▼               ▼               ▼               ▼
   ┌─────────────────────────────────────────────────────────────┐
   │             ChannelAdapter.normalize(payload)               │
   │             → NormalizedMessage(context, text)              │
   └─────────────────────────────────────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  agent.orchestrator           │
                │   process_user_message(...)   │
                └───────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  agent.llm_client.run_agent   │
                │   1. chat completion          │
                │   2. tool calls (if any)      │
                │   3. final completion         │
                └───────────────────────────────┘
                       │              │
              ┌────────▼─────┐  ┌─────▼─────────┐
              │ calendar_tool │  │ finance_tool │
              │ (Google Cal)  │  │ (Sheets+NBU) │
              └───────────────┘  └──────────────┘
```

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/De-Light-n/wallet-calendar-bot
cd wallet-calendar-bot
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in the variables used by the channels you actually plan to enable.
```

Required for a minimal Telegram-only deploy:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from [@BotFather](https://t.me/BotFather) |
| `GEMINI_API_KEY` | Google AI Studio key (used through the OpenAI-compatible endpoint) |
| `GROQ_API_KEY` | Groq key for Whisper voice transcription |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth2 credentials for Calendar + Sheets + Drive |
| `GOOGLE_REDIRECT_URI` | e.g. `http://localhost:8000/auth/google/callback` |
| `WEB_APP_URL` | Frontend origin, e.g. `http://localhost:5173` |
| `DATABASE_URL` | Postgres (default) or SQLite connection string |
| `SECRET_KEY` | Random string for signing session cookies |

Optional channels:

| Variable | Description |
|---|---|
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` | Slack Events API credentials |
| `SLACK_INSTALL_URL` / `SLACK_BOT_NAME` | Optional install link + bot handle shown on the dashboard so users know how to find the bot |
| `DISCORD_BOT_TOKEN` / `DISCORD_WEBHOOK_SECRET` | Discord gateway + relay webhook |
| `DISCORD_INSTALL_URL` / `DISCORD_BOT_NAME` | Optional invite URL + bot handle surfaced on the dashboard |
| `TELEGRAM_BOT_USERNAME` | Optional `@bot` handle (without `@`) for the dashboard's t.me deep link |
| `WEBCHAT_API_KEY` | Optional shared key for the anonymous web ingress |
| `WEBHOOK_URL` | Public HTTPS host (enables Telegram webhook mode) |
| `ENABLED_CHANNELS` | CSV allow-list, default `telegram,slack,discord,web` |

### 3. Run locally

```bash
uvicorn app.main:app --reload
# in another terminal
cd frontend && npm install && npm run dev
```

Then open http://localhost:5173, sign in with Google, generate a link code,
and type `/link <code>` in your messenger of choice.

### 4. Docker Compose

```bash
docker-compose up -d
```

## Usage Flow

1. Open Telegram, find your bot, send `/start`.
2. Open the web dashboard, complete Google sign-in, click *Connect Telegram*.
3. Type `/link <code>` in Telegram — the messaging account is now bound to your
   web profile, and a Google Sheets ledger is provisioned on first transaction.
4. Send messages or voice notes from any connected channel:
   - *"Запиши завтра на 15:00 зустріч з Максом"* → creates a Calendar event
   - *"Записати 150 грн за каву"* → appends an Expense row
   - *"Завтра о 18:00 зустріч і запиши 300 грн за вечерю"* → both at once

### Slash commands (Telegram / Slack / Discord)

| Command | Effect |
|---|---|
| `/start` | Register a new anonymous account (Telegram only) |
| `/link <code>` | Bind this chat account to a web user |
| `/currency [CODE]` | Show or change base currency (UAH, USD, EUR, ...) |
| `/new_sheet` | Provision a fresh spreadsheet with the latest layout |

## Tests

```bash
pytest tests/ -v
```

## Google API Setup

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project → enable **Calendar API**, **Sheets API**, and **Drive API**.
3. Create an **OAuth 2.0 Client ID** of type *Web Application*.
4. Add `GOOGLE_REDIRECT_URI` to *Authorized redirect URIs* (must match exactly).
5. Copy *Client ID* and *Client Secret* into `.env`.
6. On first sign-in the consent screen requests Calendar, Sheets, and
   `drive.file` scopes — the last one allows the app to create / edit only the
   spreadsheets it owns, never anything else in the user's Drive.

## Code Documentation

Every package and most callables ship a docstring; start from these entry
points when reading the code:

- [`app/main.py`](app/main.py) — process boot, channel lifecycle, Telegram
  webhook routing.
- [`app/agent/llm_client.run_agent`](app/agent/llm_client.py) — the agent loop
  with retry/fallback semantics.
- [`app/agent/orchestrator.process_user_message`](app/agent/orchestrator.py) —
  channel-agnostic dispatcher invoked by every adapter.
- [`app/tools/finance_tool`](app/tools/finance_tool.py) — spreadsheet
  provisioning, transaction recording, dashboard formulas.
- [`app/tools/calendar_tool`](app/tools/calendar_tool.py) — Calendar
  CRUD and free-text search.
- [`app/integrations/fx`](app/integrations/fx.py) — NBU rate fetcher with
  per-day cache and weekend/holiday lookback.
- [`app/database/models`](app/database/models.py) — full schema reference.
