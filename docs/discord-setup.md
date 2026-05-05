# Discord — як отримати credentials

> **Важливо:** на відміну від Telegram/Slack, Discord **не пушить повідомлення через HTTPS-webhook**. Бот має постійно тримати **WebSocket-з'єднання (Gateway)** до Discord. Поточний код у [app/channels/discord.py](../app/channels/discord.py) — це базовий адаптер; повноцінна Gateway-інтеграція ще не реалізована (тут лежить у [TODO.md](../TODO.md) майбутнім пунктом). Цей документ — про те, як підготувати credentials наперед, щоб коли реалізація буде готова, вже все було під рукою.

## Що тобі знадобиться

- Discord-сервер, де ти **owner** або маєш `Manage Server` permission (щоб запросити бота)
- Discord-аккаунт

В кінці ти отримаєш дві змінні в `.env`:
```
DISCORD_BOT_TOKEN=...
DISCORD_APPLICATION_ID=...   # для slash-команд (опційно)
```

---

## Крок 1. Створити Discord Application

1. Відкрий https://discord.com/developers/applications → **New Application**
2. Назва: `Wallet Calendar Bot` (або як хочеш)
3. Прийми Developer Terms → **Create**

На сторінці додатка скопіюй **Application ID** (зверху, поряд з логотипом).
📋 Це твій `DISCORD_APPLICATION_ID` (потрібен пізніше для slash-команд).

---

## Крок 2. Створити Bot User

1. У лівому меню обери **Bot**
2. Натисни **Reset Token** → **Yes, do it!** → з'явиться токен (показується **тільки один раз!**)
3. 📋 **Скопіюй його негайно** — це твій `DISCORD_BOT_TOKEN`
4. Прокрути вниз до **Privileged Gateway Intents**, увімкни:
   - ✅ **Message Content Intent** — без цього бот не буде бачити текст повідомлень
   - ✅ **Server Members Intent** — для нормального доступу до користувачів
5. **Save Changes** внизу

> ⚠️ Якщо випадково побачив токен пізніше і не скопіював — треба `Reset Token` ще раз. Старий токен інвалідується.

---

## Крок 3. Налаштувати OAuth2 для запрошення бота на сервер

1. У лівому меню обери **OAuth2** → **URL Generator**
2. **Scopes** → постав галочки:
   - ✅ `bot`
   - ✅ `applications.commands` (для slash-команд у майбутньому)
3. **Bot Permissions** → постав галочки:
   - ✅ `Send Messages`
   - ✅ `Send Messages in Threads`
   - ✅ `Read Message History`
   - ✅ `View Channels`
   - ✅ `Use Slash Commands`
4. Внизу скопіюй **Generated URL** — він виглядає як:
   ```
   https://discord.com/api/oauth2/authorize?client_id=...&permissions=...&scope=bot+applications.commands
   ```

---

## Крок 4. Запросити бота на свій сервер

1. Відкрий той `Generated URL` у браузері
2. Обери сервер (де ти owner) → **Authorize** → пройди captcha
3. Бот з'явиться у списку учасників сервера (offline до запуску бекенду)

---

## Крок 5. Заповнити .env

```bash
DISCORD_BOT_TOKEN=MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.XxXxXx.YyYyYyYyYy
DISCORD_APPLICATION_ID=1234567890123456789
ENABLED_CHANNELS=telegram,slack,discord
```

> Поле `DISCORD_APPLICATION_ID` ще не використовується в коді — додано для майбутньої реалізації slash-команд.
> Поле `DISCORD_WEBHOOK_SECRET` у .env.example — це для поточного тимчасового webhook-stub'а. Можеш ігнорувати, поки не зроблений Gateway-клієнт.

---

## Крок 6. Запустити бот

Discord gateway-клієнт інтегрований у [app/main.py](../app/main.py) і стартує
разом з рештою сервісів. Окремого runner-скрипта немає.

```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

В логах має з'явитись:
```
INFO  app.channels.discord_bot: Discord bot starting…
INFO  app.channels.discord_bot: Discord bot connected | id=... name=Wallet Calendar Bot guilds=1
```

На сервері бот стане **online** (зелений індикатор). Пиши в DM або тегай
`@bot` у каналі куди він запрошений — отримаєш відповідь.

---

## Безпека

- `DISCORD_BOT_TOKEN` дає **повний** контроль над ботом — він може писати в усі канали де є, читати повідомлення, видаляти і т.д.
- **Не комітити в git** (`.env` у `.gitignore`).
- Якщо витік — на developer portal **Bot → Reset Token** негайно.
- На production варто rotate'ити токен раз на 6 міс.

---

## Альтернатива: тільки slash-команди

Якщо не хочеться повноцінного бота, Discord підтримує **HTTP Interactions Endpoint** — Discord буде POST'ити slash-команди (типу `/wallet добавити-витрату`) на твій webhook. Це працює без Gateway, але **обмежує** UX: тільки команди з префіксом `/`, без природного DM-тексту.

Налаштування:
1. **General Information** → **Interactions Endpoint URL** → `https://your-host.com/api/channels/discord/interactions`
2. Discord верифікує URL Ed25519-підписом — бекенд має правильно відповідати на ping'и
3. Реєстрація команд через REST API (`POST /applications/{app_id}/commands`)

Цей шлях простіший, але Discord-юзери звикли писати природним текстом, а не команди — тому довгостроково Gateway все ж кращий.
