# Hosting — де розгорнути все безкоштовно

## Що треба захостити

| Компонент | Що це | Вимоги |
|-----------|-------|--------|
| **Backend** (FastAPI + AI agent + bot) | Python 3.13, постійний процес, HTTPS | завжди-онлайн, ~256MB RAM, публічний HTTPS-домен |
| **Postgres** | БД для юзерів, OAuth-токенів, link-кодів | ~100MB вистачить надовго |
| **Frontend** (React) | Статичний build для дашборду | будь-який static-host |

> Telegram-bot можна запускати у двох режимах:
> - **Webhook** (через FastAPI, в `app/main.py`) — кращий для production, інтегровано з backend.
> - **Long polling** (через `bot.py`) — окремий процес, для локального dev.
> Для хостингу **використовуй webhook-режим** — один процес замість двох, і Telegram сам "стукає" коли є нові повідомлення.

---

## Рекомендований стек (безкоштовний на старті)

| Сервіс | Що хостить | Free tier | Чому саме він |
|--------|------------|-----------|---------------|
| **Fly.io** | Backend | 3 машини × 256MB, 3GB volume | завжди-онлайн (не "засинає"), HTTPS з коробки |
| **Neon** | Postgres | 0.5GB storage, 1 проект | завжди-онлайн, нативно сумісний з Postgres |
| **Cloudflare Pages** | Frontend | необмежено для static | швидкий CDN, простий deploy з GitHub |

Цей стек — те, що я б порадив для першого продакшну: **0 USD** на старті, без сюрпризів типу "сервіс заснув і Telegram не доходить".

Альтернатива якщо ліньки — все на **Render**, але там сервіси засинають через 15 хвилин неактивності → Telegram-webhooks втрачаються.

---

## Варіант 1 (рекомендований): Fly.io + Neon + Cloudflare Pages

### A. Postgres на Neon

1. Зареєструйся → https://neon.tech (через GitHub або email)
2. **Create Project** → виставлено за замовчуванням **Postgres 16**
3. **Project name**: `wallet-calendar`
4. **Region**: найближчий (для Європи — `eu-central-1` Frankfurt)
5. Натисни **Create Project**
6. Скопіюй **Connection string** з вкладки **Dashboard → Connection Details** → формат:
   ```
   postgresql://user:pass@ep-xxxxx.eu-central-1.aws.neon.tech/neondb
   ```
7. **Важливо**: бекенд використовує `psycopg2`, який очікує `postgresql+psycopg2://` префікс, а не просто `postgresql://`. Заміни:
   ```
   postgresql+psycopg2://user:pass@ep-xxxxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

### B. Backend на Fly.io

#### B.1. Встановити Fly CLI

**Windows (PowerShell):**
```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

**macOS/Linux:**
```bash
curl -L https://fly.io/install.sh | sh
```

Перезапусти термінал. Перевір: `fly version`.

#### B.2. Авторизуватись

```bash
fly auth signup    # перший раз — зареєструватись
# або
fly auth login     # якщо вже є аккаунт
```

#### B.3. Створити Dockerfile у корені репо

Файл `Dockerfile`:
```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Postgres client libs (psycopg2 потребує)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fly виставляє PORT, ми його шанобливо використовуємо
ENV PORT=8000
EXPOSE 8000

CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

(Якщо вже є — пропусти.)

#### B.4. Ініціалізувати Fly app

```bash
fly launch --no-deploy
```

Інтерактив:
- App name: `wallet-calendar-bot` (буде доступний як `https://wallet-calendar-bot.fly.dev`)
- Region: найближчий (`fra` для Frankfurt, `waw` для Warsaw)
- Postgres: **No** (ми вже маємо Neon)
- Redis: **No**
- Deploy зараз: **No**

Створиться `fly.toml`. Перевір що там є:
```toml
[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = false   # ← ВАЖЛИВО, інакше засне
  auto_start_machines = true
  min_machines_running = 1
```

> Якщо `auto_stop_machines = "stop"` — машина буде засинати. Постав `false` або видали рядок взагалі. На free tier ти платиш не за час роботи, а за кількість машин і RAM.

#### B.5. Виставити секрети

```bash
fly secrets set TELEGRAM_BOT_TOKEN=123:abc
fly secrets set GEMINI_API_KEY=AIzaSy...
fly secrets set GROQ_API_KEY=gsk_...
fly secrets set GOOGLE_CLIENT_ID=...
fly secrets set GOOGLE_CLIENT_SECRET=...
fly secrets set GOOGLE_PROJECT_ID=...
fly secrets set GOOGLE_REDIRECT_URI=https://wallet-calendar-bot.fly.dev/auth/google/callback
fly secrets set SECRET_KEY=$(openssl rand -hex 32)   # або згенеруй вручну
fly secrets set DATABASE_URL="postgresql+psycopg2://user:pass@ep-xxxxx.eu-central-1.aws.neon.tech/neondb?sslmode=require"
fly secrets set WEBHOOK_URL=https://wallet-calendar-bot.fly.dev
fly secrets set WEB_APP_URL=https://wallet-calendar.pages.dev   # або твій кастомний домен
fly secrets set ENABLED_CHANNELS=telegram,slack,web
fly secrets set OPENAI_MODEL=gemini-2.5-flash
fly secrets set FINANCE_STUB_MODE=false

# Slack (опційно — заповнюй коли налаштуєш Slack app)
fly secrets set SLACK_BOT_TOKEN=xoxb-...
fly secrets set SLACK_SIGNING_SECRET=...
```

Подивитися перелік:
```bash
fly secrets list
```

#### B.6. Оновити Google OAuth Redirect URI

В [Google Cloud Console](https://console.cloud.google.com) → твій проект → **APIs & Services** → **Credentials** → твій OAuth 2.0 Client → **Authorized redirect URIs** → додай:
```
https://wallet-calendar-bot.fly.dev/auth/google/callback
```

Збережи. Без цього кроку Google буде відмовляти на callback.

#### B.7. Deploy

```bash
fly deploy
```

Чекай 2-5 хвилин на перший білд. Маєш побачити `Successful deploy`.

#### B.8. Перевірка

```bash
# Логи в реальному часі
fly logs

# Перевірити що Telegram webhook зареєстровано:
curl https://api.telegram.org/bot<твій_токен>/getWebhookInfo
# у відповіді має бути url=https://wallet-calendar-bot.fly.dev/webhook/<токен>
```

Напиши боту в Telegram — повинна бути відповідь.

### C. Frontend на Cloudflare Pages

#### C.1. Підготовка

У `frontend/` має бути `package.json` зі скриптом `build`. Уже є.

#### C.2. Connect to Git

1. Відкрий https://dash.cloudflare.com → ввійди (зареєструйся через email)
2. Лівий sidebar → **Workers & Pages** → **Create application** → **Pages** → **Connect to Git**
3. Підключи свій GitHub-аккаунт → дай доступ до репо `wallet-calendar-bot`
4. **Set up builds and deployments**:
   - **Project name**: `wallet-calendar`
   - **Production branch**: `main`
   - **Framework preset**: `Vite`
   - **Build command**: `npm install && npm run build`
   - **Build output directory**: `frontend/dist`
   - **Root directory**: `frontend`
5. **Environment variables**:
   - `VITE_API_BASE_URL` = `https://wallet-calendar-bot.fly.dev` (твій Fly backend)
6. **Save and Deploy**

Перший білд ~3 хвилини. Маєш URL `https://wallet-calendar.pages.dev`.

#### C.3. Оновити CORS на бекенді

В [app/main.py](../app/main.py) `WEB_APP_URL` тепер має бути `https://wallet-calendar.pages.dev`. Уже виставлено через `fly secrets set WEB_APP_URL=...` (крок B.5). При деплої з нового пуша — підхопиться.

---

## Варіант 2 (найшвидший): все на Render

⚠️ **Caveat**: Render Free Web Services **засинають через 15 хв неактивності** і прокидаються 30-60 секунд при першому запиті. Telegram чекає 60 секунд на webhook → інколи повідомлення прокидаються повільно. Для production раджу варіант 1.

### Render setup

1. https://render.com → Sign up через GitHub
2. **New +** → **PostgreSQL** → free плана (500MB, термін 90 днів, потім видаляється) → **Create Database**
3. Скопіюй **Internal Database URL**
4. **New +** → **Web Service** → підключи репо
5. Settings:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: **Free**
6. **Environment Variables** → додай ті ж самі що для Fly (крок B.5), але:
   - `DATABASE_URL` = Internal Database URL з кроку 3, перетвори в `postgresql+psycopg2://...`
   - `WEBHOOK_URL` = `https://your-app.onrender.com`
7. **Create Web Service** → чекай ~5 хвилин
8. Frontend на Render: **New +** → **Static Site** → той самий репо → **Build**: `cd frontend && npm install && npm run build`, **Publish dir**: `frontend/dist`

---

## Постійні витрати

### Варіант 1 (Fly.io + Neon + CF Pages)
| Ресурс | Free tier | Коли стане платно |
|--------|-----------|-------------------|
| Fly.io | 3 машини × 256MB free | Якщо треба більше RAM/процесорного часу |
| Neon | 0.5GB БД, **завжди-онлайн** | Якщо БД виросте >0.5GB (станеться через сотні тисяч транзакцій) |
| Cloudflare Pages | необмежено для статики | Майже ніколи |

→ **0 USD** для особистого використання навіть на місяць+ безперервно.

### Варіант 2 (Render)
| Ресурс | Free tier | Коли стане платно |
|--------|-----------|-------------------|
| Render Web | sleep після 15 хв | $7/міс щоб always-on |
| Render Postgres | 500MB, **видаляється через 90 днів** | $7/міс щоб permanent |

→ Через 90 днів треба буде або повернути дані вручну, або перейти на план $7-14/міс.

---

## Чек-лист "що ще зробити для production"

- [ ] Замінити `SECRET_KEY` у .env на справжню довгу рандомну строку: `openssl rand -hex 32`
- [ ] Додати домен у **Authorized JavaScript origins** в Google OAuth credentials (для frontend)
- [ ] Якщо домен кастомний (не `*.fly.dev` / `*.pages.dev`) — додати DNS-записи у Cloudflare/реєстраторі
- [ ] Налаштувати **Sentry** або **Logtail** для збору помилок (free tier є)
- [ ] Переконатись що `FINANCE_STUB_MODE=false` на проді
- [ ] Telegram bot link в `/start` повинен показувати правильний `WEB_APP_URL` (онови якщо змінився)
- [ ] (опційно) Налаштувати GitHub Actions для автодеплою на push в `main`

---

## Корисні команди (Fly.io)

```bash
fly logs                            # потокові логи
fly status                          # статус машин
fly ssh console                     # ssh у машину
fly machines list                   # перелік machine'ів
fly deploy                          # передеплоїти
fly secrets list                    # перелік секретів (без значень)
fly secrets unset GROQ_API_KEY      # видалити секрет
fly scale memory 512                # підняти RAM до 512MB (платно)
```

---

## Що робити коли щось зламається

1. **Bot не відповідає** → `fly logs` → шукай помилки. Найчастіше:
   - `psycopg2.OperationalError` → DB-URL неправильний або мережа до Neon впала
   - `Telegram API error 401` → `TELEGRAM_BOT_TOKEN` неправильний
   - `Slack signature rejected` → `SLACK_SIGNING_SECRET` неправильний

2. **Frontend показує "Не вдалось увійти"** → `VITE_API_BASE_URL` на CF Pages не вказує на твій Fly backend.

3. **Google OAuth → "redirect_uri_mismatch"** → у Google Cloud Console redirect URI не співпадає з `GOOGLE_REDIRECT_URI` на бекенді.

4. **Telegram webhook конфліктує з polling** → `getWebhookInfo` показує URL, а ти запускаєш `bot.py` (polling). Це **взаємовиключні** режими. Або deleteWebhook + polling, або webhook + не запускати bot.py.
