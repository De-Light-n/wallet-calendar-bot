# wallet-calendar-bot

Personal AI assistant that manages **Google Calendar events** and a **personal expense wallet** via Telegram — using text or voice messages.

## 🏛 Architecture

```
wallet-calendar-bot/
│
├── app/
│   ├── main.py                 # FastAPI entry point + Telegram webhook
│   │
│   ├── bot/                    # Telegram bot
│   │   ├── handlers.py         # Text & voice message handlers
│   │   └── utils.py            # Audio download helpers
│   │
│   ├── agent/                  # AI layer
│   │   ├── llm_client.py       # OpenAI GPT-4o function-calling agent
│   │   ├── system_prompts.py   # Agent system prompt
│   │   └── stt.py              # Speech-to-Text via OpenAI Whisper
│   │
│   ├── tools/                  # Agent tools
│   │   ├── calendar_tool.py    # Google Calendar API
│   │   └── finance_tool.py     # Expense recording (DB)
│   │
│   ├── web/                    # Registration & OAuth web UI
│   │   ├── routes.py           # /login, /auth/google, /dashboard
│   │   └── templates/          # Jinja2 HTML templates
│   │
│   └── database/               # Persistence
│       ├── models.py           # SQLAlchemy models: User, OAuthToken, Expense
│       └── session.py          # DB engine & session factory
│
├── tests/                      # Pytest test suite
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/De-Light-n/wallet-calendar-bot
cd wallet-calendar-bot
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in all required values in .env
```

Required variables:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from [@BotFather](https://t.me/BotFather) |
| `OPENAI_API_KEY` | OpenAI API key (for GPT-4o & Whisper) |
| `GOOGLE_CLIENT_ID` | Google OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 client secret |
| `GOOGLE_REDIRECT_URI` | e.g. `https://yourdomain.com/auth/google/callback` |
| `WEBHOOK_URL` | Public HTTPS URL of your server |
| `DATABASE_URL` | SQLite (default) or PostgreSQL connection string |

### 3. Run locally

```bash
uvicorn app.main:app --reload
```

### 4. Docker Compose

```bash
docker-compose up -d
```

## 📱 Usage Flow

1. Open Telegram, find your bot and send `/start`
2. Visit the link the bot provides → sign in with Google → authorize Calendar access
3. Send any message or voice note:
   - *"Запиши завтра на 15:00 зустріч з Максом"* → creates a Google Calendar event
   - *"Записати 150 грн за каву"* → adds an expense entry
   - *"Завтра о 18:00 зустріч і запиши 300 грн за вечерю"* → does **both** at once!

## 🧪 Tests

```bash
pytest tests/ -v
```

## 🔐 Google API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → enable **Google Calendar API**
3. Create OAuth2 credentials (Web Application type)
4. Add your `GOOGLE_REDIRECT_URI` to the allowed redirect URIs
5. Copy Client ID and Client Secret to `.env`
