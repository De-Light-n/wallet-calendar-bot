# TODO

Запланована робота, яку ще не зроблено. Кожен пункт — що робити, чому, і як.

---

## 1. Multi-currency support із зведенням до базової валюти користувача

### Що хочемо

- Кожна транзакція пишеться у валюті як зараз (`Amount`, `Currency`).
- У юзера є **базова валюта** (наприклад, UAH або USD) — те, в чому він хоче бачити підсумки в Dashboard / Monthly / Categories.
- Сервіс раз на день тягне курси валют з зовнішнього API і кешує їх у БД.
- Кожна нова транзакція додатково записує **сконвертовану суму на момент запису** (за курсом, що був дійсний у цей день).
- Старі транзакції лишаються з курсом, що був на день їхнього запису — тобто історичний баланс не "плаває" при зміні поточних курсів.

### Чому "сконвертована сума" зберігається в кожному рядку, а не рахується формулою

Якщо тримати тільки сирий `Amount` + `Currency` і конвертувати у формулі через свіжий курс — кожне відкриття таблиці буде показувати інше число для тієї ж покупки в минулому. Це проблема для бюджету: ти не можеш сказати "я витратив у березні X у своїй базовій валюті", бо X залежить від сьогоднішнього курсу. Тому курс фіксується **у момент запису** і вже не змінюється.

### Дизайн

#### Джерело курсів (вибір)

| API | Безкоштовно | Реєстрація | Дані | Примітка |
|-----|-------------|------------|------|----------|
| **Frankfurter.app** | так, без обмежень | не треба | ECB (євроцентральні) | рекомендований — простий, без ключа, стабільний |
| ExchangeRate-API | 1500 запитів/міс | треба ключ | агрегований | overkill для нас |
| Open Exchange Rates | 1000 запитів/міс | треба ключ | хороший вибір валют | overkill |

**Рекомендація:** Frankfurter — `https://api.frankfurter.app/latest?from=UAH&to=USD,EUR,GBP,...`. Один HTTP-запит, без ключа, ECB-якість.

UAH немає прямої котировки в ECB → тягни щодо EUR/USD, потім крос-курс. Або використай НБУ-API: `https://bank.gov.ua/NBU_Exchange/exchange_site?valcode=USD&date=20260427&json` — офіційний курс НБУ, ідеально для українських юзерів.

#### Зміни в БД

Додати таблицю:

```python
class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("base", "quote", "as_of_date", name="uq_rate_per_day"),
    )

    id = Column(Integer, primary_key=True)
    base = Column(String(8), nullable=False)        # e.g. "UAH"
    quote = Column(String(8), nullable=False)       # e.g. "USD"
    rate = Column(Float, nullable=False)            # 1 base = `rate` quote
    as_of_date = Column(Date, nullable=False)       # день, для якого курс
    fetched_at = Column(DateTime(timezone=True))    # коли підтягнули
```

Додати поле в `User`:

```python
base_currency = Column(String(8), nullable=False, default="UAH", server_default="UAH")
```

#### Фоновий sync

Варіанти:
- **APScheduler** в тому ж процесі що FastAPI — найпростіше, але не запускається з `python bot.py` (бот окремо).
- **Окремий тригер `python -m app.scripts.sync_rates`** + cron / systemd-timer / GitHub Actions — для production-хостингу.
- **Lazy на запит**: при `record_transaction` перевіряти, чи є курс на сьогодні; якщо нема — тягнути синхронно. Найпростіше для початку, без додаткової інфраструктури.

**Рекомендація:** lazy-on-demand спочатку (без планувальника). Якщо стане бутилочним горлом — додавай scheduler.

#### Зміни в `record_transaction`

```python
# Псевдокод
amount = ...
currency = ...
base_currency = user.base_currency  # "UAH"
today = now_utc.date()

if currency == base_currency:
    rate = 1.0
    base_amount = amount
else:
    rate = get_or_fetch_rate(db, base=base_currency, quote=currency, as_of=today)
    base_amount = amount / rate  # 1 base = rate quote → quote/rate = base
```

#### Зміни в Google Sheets

Розширити `Transactions` з 7 колонок до 9:

| A | B | C | D | E | F | G | H | I |
|---|---|---|---|---|---|---|---|---|
| Date | Time | Type | Amount | Currency | Category | Description | Base Amount | Base Currency |

`Base Amount` — фіксоване число (не формула), щоб історія не плавала.

Усі формули в Dashboard / Monthly / Categories переключити з `Amount (D)` на `Base Amount (H)`. Тоді всі підсумки будуть у базовій валюті юзера автоматично.

#### Команди боту

- `/currency USD` — змінити базову валюту. Викликає попередження: "нові транзакції конвертуватимуться в USD; старі залишаться як є".
- (опціонально) `/recalculate` — перерахувати `Base Amount` для всіх історичних рядків за курсом сьогодні. Корисно якщо юзер прийшов із купою старих рядків без курсу. Ризик: переписує історичні дані.

#### Міграція існуючих юзерів

Транзакції, написані ДО цієї фічі, не мають `Base Amount`. Опції:
1. Залишити пустим, формули `IFERROR(H/0; D)` фолбекнуть на `Amount` — точність кульгає, але не падає.
2. Прогнати скрипт `app/scripts/backfill_base_amount.py`, який пройде по `Transactions` кожного юзера, забере курс на дату рядка через API, перепише колонку H. Один раз — нормально.

**Рекомендація:** опція 2, але запускати тільки коли буде time для тестування на 1 юзері.

### Етапи (по порядку)

1. **БД**: alembic міграція — `users.base_currency` + `exchange_rates` таблиця.
2. **FX-клієнт**: `app/integrations/fx.py` — `fetch_rate(base, quote, as_of_date)` з фолбеком (ECB → НБУ → готова кеш-копія).
3. **Інтеграція в `record_transaction`**: підраховувати `base_amount` перед append, додати колонки H, I.
4. **Перебудувати схему spreadsheet**: оновити `_TRANSACTIONS_HEADER`, `_dashboard_values`, `_monthly_values`, `_categories_values` щоб формули рахували по колонці H.
5. **Bump `spreadsheet_schema_version`** (треба ще ввести цю константу) → `_ensure_user_spreadsheet` побачить версію в коді > версії в БД → авто-`/new_sheet`.
6. **Команда `/currency`** — простий текстовий валідатор + UPDATE в БД.
7. **Lazy fetch + кеш**: при відсутності курсу на день викликати API, кешувати в `exchange_rates`.
8. **(опц.)** Backfill-скрипт для існуючих рядків.
9. **(опц.)** Background scheduler для проактивного оновлення.

### Що сильно полегшує цю фічу

- `record_transaction` уже централізовано записує — одне місце для додавання `base_amount`.
- Формули вже в коді (`_dashboard_values` etc.) — не треба лазити по Sheets, просто підправити Python-функції.
- `/new_sheet` уже існує — апгрейд структури безболісний для юзера.
- Auto-recovery при 404 уже є — якщо щось піде не так, юзер може просто перестворити.

### Декомпозиція по PR

1. PR1: модель + міграція + FX-клієнт із тестами (без інтеграції в transactions).
2. PR2: інтеграція в `record_transaction` + новий формат таблиці + bump schema_version.
3. PR3: команда `/currency` в боті + UI на frontend (якщо буде).
4. PR4: backfill-скрипт.

---

## 2. Update / Delete подій у календарі

### Що хочемо

- `update_event` — перенести час, перейменувати, поміняти локацію без переходу в Google Calendar UI.
- `delete_event` — відмінити подію.

### Чому це окремий пункт, а не зразу

LLM має **знайти подію** перед update/delete. Зараз `list_upcoming_events` уже зареєстрований як tool, тому це базово можливо: LLM спочатку викликає list, отримує `event_id`, потім update/delete. Але є нюанси по UX і ризику.

### Дизайн

#### `update_event(event_id, **fields)`

Параметри: `event_id` (обов'язковий, отриманий з `list_upcoming_events`) + ті ж поля, що і в `create_calendar_event`, але всі опціональні. Patch-семантика — оновлюються тільки передані поля.

API: `service.events().patch(calendarId="primary", eventId=event_id, body={...})`. Повертає оновлений event.

LLM workflow для "перенеси зустріч з Сашею на 16:00":
1. `list_upcoming_events(query="Саша", time_min=today)` → отримує список
2. Якщо знайдено 1 → `update_event(event_id=..., start_datetime="...", end_datetime="...")`.
3. Якщо знайдено кілька → відповідь юзеру з вибором.
4. Якщо нічого → відповідь "не знайшов".

**Ризик низький:** помилка в update легко виправляється новим повідомленням; Google зберігає історію змін.

#### `delete_event(event_id)`

API: `service.events().delete(calendarId="primary", eventId=event_id)` → подія йде в **Trash** Google Calendar (30 днів автовідновлення). Це рятує від випадкового видалення.

**Ризики:**
- Голосові повідомлення через Whisper можуть розпізнати "віддали" як "видали" → випадкове видалення.
- LLM може знайти не ту подію при кількох схожих.
- Юзер не одразу побачить що подія в trash.

**Mitigation:**
- Soft-confirmation flow: бот відповідає "Підтверди: видалити подію 'X' на завтра о 14:00? Напиши 'так' або 'ні'." Тільки на "так" — реальний виклик API.
- Це додає **stateful conversation** — треба зберігати "очікую підтвердження видалення event_id=X" між повідомленнями. Складніше імплементувати.
- Альтернатива: покладатися на 30-денний trash + лог в Telegram — юзер бачить "Видалив подію X. Якщо помилково — `/restore_event` за 30 днів".

### Етапи

1. **PR1: `update_event`** — як новий tool. Без stateful confirmation. Тестувати що patch правильно ставить `timeZone` (так само як create).
2. **PR2: `delete_event` без confirmation** + повідомлення з event_id для відновлення. Trash-fallback зробить ризик прийнятним.
3. **(опц.) PR3: stateful confirmation** для delete — якщо стане ясно що випадкові видалення трапляються.
4. **(опц.) PR4: `restore_event(event_id)`** — повертає з trash. API: `events.get` з `?showDeleted=true` + `events.update` з `status="confirmed"`.

### Що сильно полегшує

- `list_upcoming_events` вже tool — LLM може шукати події по `query`/`time_min`/`time_max`.
- `execute_with_retry` обгортає всі Calendar виклики — мережевих помилок не боїмось.
- Логування кожного tool-виклику в `llm_client.py` — буде видно "LLM запросив delete event_id=X" в логах при post-mortem.

---

## 3. Розділення відповідальностей між `bot.py` і `app/main.py` (Discord double-start)

### Проблема

Discord gateway зараз стартує **в обох** entry-point'ах:
- [bot.py:34](bot.py) — `await start_discord_bot()` поряд з Telegram polling.
- [app/main.py:112](app/main.py) — `await start_discord_bot()` у FastAPI startup-event.

Якщо локально запустити одночасно `python bot.py` (для Telegram polling) **і** `uvicorn app.main:app` (для Slack webhook + frontend API) — отримуємо два Discord-клієнти, що конектяться **одним токеном**. Discord розриває одну з сесій з `WebSocketClosure` / IDENTIFY rate limit. На проді конфлікт менш помітний (один процес), але архітектурний дубль залишається і блокує будь-який чистий деплой типу "uvicorn окремо, gateway окремо".

### Рішення (після того як протестуємо що Discord взагалі працює)

Розподіл відповідальностей:

| Файл | Що тримає | Коли запускати |
|------|-----------|----------------|
| `app/main.py` (uvicorn) | HTTP-only: Telegram webhook (prod), Slack webhook, frontend API | Завжди (prod + local) |
| `bot.py` | Persistent connections: Telegram polling (dev), Discord gateway | Local-dev окремо; prod — окремий процес/контейнер |

### Зміни в коді

1. У [app/main.py](app/main.py) **видалити**:
   - рядок `from app.channels.discord_bot import start_discord_bot, stop_discord_bot`
   - виклик `await start_discord_bot()` у `on_startup`
   - виклик `await stop_discord_bot()` у `on_shutdown`
2. [bot.py](bot.py) залишити як є — він уже стартує і Telegram polling, і Discord gateway.
3. Оновити `docs/hosting.md` (коли буде): на проді запускати `uvicorn app.main:app` як HTTP-сервіс + `python bot.py` як окремий worker (systemd unit / Fly.io processes / Docker compose service).

### Чому *після* тестування

Зараз треба підтвердити що Discord-runner у `bot.py` справді ловить повідомлення і працює `/link`-флоу. Якщо викинути зараз з `main.py` — і виявиться що в `bot.py` десь баг, то Discord відмерне, і важче відлажити що зламалось саме від видалення vs від існуючої проблеми. Спочатку доводимо обидва варіанти до зеленого стану, потім "обрізаємо".

### Майбутнє масштабування (NOT NOW)

Поки одного процесу uvicorn (для HTTP) + одного `bot.py` (для gateway) досить до ~10к юзерів. Реальний bottleneck — LLM-API rate limits, не FastAPI. Розділяти на 4 окремі сервіси (один на канал) — **не треба**, це підриває можливість безкоштовного хостингу і не дає виграшу при цьому навантаженні.

Коли реально перевалить за 10к активних — тоді робиться:
- HTTP layer (uvicorn) ← N replicas за load balancer
- Discord gateway ← 1 instance (gateway не масштабується горизонтально)
- LLM-job queue (Celery/RQ + Redis) ← N workers, щоб HTTP-handler'и не блокувались на 2-5с виклику моделі

Поки про це не думати.

### Етапи

1. Дотестувати поточний стан (Discord працює в DM + у каналі по mention; `/link` приймає код).
2. PR: видалити Discord start/stop з `app/main.py`.
3. (Опц.) `docs/hosting.md` — оновити секцію про процеси на проді: окремий gateway-worker.

---
