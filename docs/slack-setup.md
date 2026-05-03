# Slack — як отримати credentials

Покрокова інструкція щоб бот працював у Slack: DM-повідомлення і `@mention` у каналах.

## Що тобі знадобиться

- Slack workspace, де ти **admin** (інакше не зможеш встановити app)
- Публічна HTTPS-адреса твого бекенду (про хостинг — у [hosting.md](hosting.md); локально для тестів — `ngrok http 8000`)

В кінці ти отримаєш дві змінні в `.env`:
```
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
```

---

## Крок 1. Створити Slack-додаток

1. Відкрий https://api.slack.com/apps → **Create New App**
2. Обери **From scratch**
3. **App Name**: `Wallet Calendar Bot` (або як хочеш)
4. **Pick a workspace**: твій робочий простір
5. **Create App**

---

## Крок 2. Налаштувати Bot Token Scopes

У лівому меню: **OAuth & Permissions** → прокрути до **Scopes** → **Bot Token Scopes** → **Add an OAuth Scope** → додай по черзі:

| Scope | Навіщо |
|-------|--------|
| `chat:write` | Відправляти повідомлення-відповіді |
| `im:history` | Читати DM (юзер пише прямо боту) |
| `im:write` | Бот може відкривати DM з юзером |
| `app_mentions:read` | Реагувати на `@bot` в каналах |
| `users:read` | Підтягнути ім'я юзера для відображення |

> User Token Scopes (нижче) — **не треба**, не додавай нічого туди.

---

## Крок 3. Встановити app у workspace

На тій же сторінці **OAuth & Permissions** прокрути до самого верху → **Install to Workspace** → **Allow**.

Тепер з'явилось значення **Bot User OAuth Token**, що починається з `xoxb-...`.

📋 **Скопіюй його** — це твій `SLACK_BOT_TOKEN`.

---

## Крок 4. Скопіювати Signing Secret

У лівому меню: **Basic Information** → прокрути до **App Credentials** → знайди **Signing Secret** → клацни **Show** → скопіюй.

📋 Це твій `SLACK_SIGNING_SECRET`. Ним перевіряється що webhook-запит реально від Slack, а не від рандомного зловмисника.

---

## Крок 5. Підписатися на події (Event Subscriptions)

У лівому меню: **Event Subscriptions** → перемкни **Enable Events** на **On**.

### 5.1. Request URL

Введи свою публічну HTTPS-адресу + `/api/channels/slack/webhook`:

```
https://your-public-host.com/api/channels/slack/webhook
```

> Локально для тестів: запусти `ngrok http 8000` (в окремому терміналі) і використай його HTTPS-URL, наприклад `https://abc123.ngrok-free.app/api/channels/slack/webhook`.

Slack одразу пошле тестовий запит на цей URL з `type: "url_verification"`. Бекенд правильно відповість, і поле зеленіє галочкою **Verified ✓**.

> Якщо червоніє — бекенд недоступний / відповідає не 200 / неправильно обробляє challenge. Перевір логи: повинен бути рядок `Slack URL verification handshake received`.

### 5.2. Subscribe to bot events

Прокрути нижче до **Subscribe to bot events** → **Add Bot User Event** → додай по черзі:

| Event | Що це |
|-------|-------|
| `message.im` | Юзер написав боту в DM |
| `app_mention` | Юзер тегнув `@bot` у каналі |

Натисни **Save Changes** внизу.

> Якщо ти змінюєш scopes після першої установки, Slack попросить **reinstall** додатка — натисни на банер угорі і дай `Allow` ще раз.

---

## Крок 6. Заповнити .env

```bash
SLACK_BOT_TOKEN=xoxb-1234567890-1234567890-абвгде
SLACK_SIGNING_SECRET=a1b2c3d4e5f6g7h8i9j0
ENABLED_CHANNELS=telegram,slack
```

---

## Крок 7. Прив'язати акаунт

1. Зайди на свій web-фронтенд → ввійди через Google → отримай дашборд → згенеруй link-код (`Підключити Telegram` поки що єдина кнопка, але код підходить будь-якому каналу).
2. Знайди свій бот у Slack: **Apps** → клацни на нього → відкриється DM.
3. Напиши боту в DM: `/link ABCD1234` (де `ABCD1234` — твій код)
4. Маєш отримати `✅ Slack підключено до акаунта твого профілю.`

Потім будь-яке повідомлення в DM або `@bot щось` у каналі — бот відповідає.

---

## Перевірка

```bash
# Запускає весь стек: HTTP API, Telegram (polling/webhook), Slack webhook, Discord gateway.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

В Slack DM напиши: `Витратив 40 на каву` → бачиш у логах:

```
INFO  app.channels.routes: Slack message | user=U... channel=D... text_len=...
INFO  app.tools.finance_tool: record_transaction called | ...
INFO  app.channels.slack_client: Slack chat.postMessage ok | channel=... ts=... text_len=...
```

І в Slack — відповідь від бота.

---

## Поширені проблеми

**`Slack signature rejected: stale timestamp`**
→ Час на твоїй машині сильно розходиться з реальним. Синхронізуй системний годинник.

**`Slack signature rejected: invalid signature`**
→ `SLACK_SIGNING_SECRET` неправильний або з пробілами по краях. Скопіюй ще раз.

**Bot не реагує в каналі**
→ Запроси його в канал: у каналі напиши `/invite @your_bot_name`. У DM запрошувати не треба.

**Slack Event Subscriptions показує `Your URL didn't respond with the value of the challenge parameter`**
→ Бекенд видає 401 на cтартовому запиті. Найчастіше: `SLACK_SIGNING_SECRET` уже виставлений в .env, але SLACK_BOT_TOKEN ще ні → перевірка підпису проходить нормально, але **не для url_verification** (там підпис теж треба перевіряти). Перевір логи; якщо `Slack signature rejected` — secret неправильний; якщо немає такого рядка взагалі — Slack не дійшов до бекенду.

**Дублі повідомлень**
→ Бекенд відповідав довго (>3с), Slack ретраїв. У коді вже є `X-Slack-Retry-Num` детекція — ретраї дропаються. Якщо все одно є дублі — глянь чи правильно мониторишь логи (можливо запущено два процеси).

---

## Безпека

- `SLACK_BOT_TOKEN` дає повний контроль над ботом у workspace — **не комітить в git, не паблішти**.
- `.env` має бути в `.gitignore` (вже там).
- Якщо токен витік — у Slack-додатку **OAuth & Permissions** → **Revoke** і встанови знову.
