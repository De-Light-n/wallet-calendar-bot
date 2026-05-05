# TODO

Запланована робота, яку ще не зроблено. Кожен пункт — що робити, чому, і як.

---

## 1. Multi-currency support із зведенням до базової валюти користувача

### Що вже зроблено (PR1 + PR2)

- ✅ Модель `ExchangeRate` (`base, quote, as_of_date` UNIQUE) + поле `User.base_currency` (default `UAH`).
- ✅ Поле `User.spreadsheet_schema_version` (default 1) + runtime-міграція в `init_db()`.
- ✅ FX-клієнт [app/integrations/fx.py](app/integrations/fx.py): NBU API + lookback на вихідні + per-day кеш у БД. `convert()` робить cross-конверсію через UAH.
- ✅ 11 тестів на FX (cache hit/miss, lookback, convert all directions).
- ✅ Schema v2 у Sheets: 9 колонок (`Date | Time | Type | Amount | Currency | Category | Description | Base Amount | Base Currency`).
- ✅ Dashboard / Monthly / Categories формули перенесені на колонку H — підсумки завжди в базовій валюті юзера.
- ✅ `record_transaction` обчислює `base_amount` через FX перед append. На `FxError` пише без конвертації + повертає `fx_warning` у відповіді (graceful degradation).
- ✅ Сумісність: існуючі юзери з v1 spreadsheet (7 cols) продовжують працювати без змін. Нові юзери і ті хто запустить `/new_sheet` отримують v2 з повним мульти-валютним стеком.
- ✅ `list_recent_transactions` + `summarize_transactions` читають A:I, повертають `base_amount` / `base_currency`. Для legacy v1 рядків fallback на оригінальний `amount` (точність кульгає, але не падає).

### Що залишилось

1. **Команда `/currency USD`** для боту — UPDATE `users.base_currency`. Попередження юзеру: "нові транзакції будуть конвертуватись у USD; старі залишаться як є — натисни `/new_sheet` щоб таблиця теж переключилась". Простий handler у `app/bot/handlers.py` + аналогічно для Slack/Discord (треба подумати чи дублювати, чи через generic `/link`-стиль).
2. **Frontend**: dropdown "Базова валюта" у Settings page (`PUT /api/me/base-currency` endpoint + UI). + лейбл "₴/$" біля сум на `/finance` — щоб не було плутанини коли в базовій валюті USD, а в Sheets рядки UAH.
3. **Backfill-скрипт** `app/scripts/backfill_base_amount.py` — для юзерів які мали v1 Sheets з купою UAH-рядків і хочуть переключитись на USD/EUR base. Пройти кожен рядок, узяти курс на дату рядка через `get_or_fetch_rate`, переписати колонку H. Запускати вручну, з `--dry-run` спочатку.
4. **(опц.)** Auto-bump: при ловлі v1 spreadsheet → автоматично пропонувати `/new_sheet` через бот ("у тебе стара структура таблиці, оновити?"). Ризик: юзер може хотіти зберегти стару — тому опитування, а не магія.
5. **(опц.)** Background scheduler для проактивного оновлення курсів — не критично, lazy-fetch з кешем покриває ~всі випадки.

### Що НЕ робилося в PR1+PR2

- Назви категорій залишаються англійською (це окрема задача — i18n).
- Старі рядки в існуючих v1 Sheets не перераховуються на льоту (треба backfill).
- `record_transaction` response містить `fx_warning` коли FX не дзвонить — але LLM його не бачить як окрему гілку. Можливо варто додати в system prompt інструкцію "якщо `fx_warning` — згадай юзеру в reply".

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
- **APScheduler** в тому ж процесі що FastAPI — найпростіше, працює і на проді і локально (тепер усі канали в одному uvicorn-процесі).
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

### Що вже зроблено

- ✅ `update_event(event_id, ...)` як LLM tool — patch-семантика, всі поля окрім `event_id` опційні. Time-зміна вимагає **обидва** start+end (інакше all-day vs timed формат би переплутався). [app/tools/calendar_tool.py](app/tools/calendar_tool.py)
- ✅ `delete_event(event_id)` — використовує `events.delete()`. Подія йде в Google Calendar Trash, 30 днів автовідновлення з UI.
- ✅ Обидва зареєстровано в [app/agent/llm_client.py](app/agent/llm_client.py); system prompt оновлено з workflow ("спочатку list, питай при ambiguity, заспокой про Trash").
- ✅ Логування з `channel=` для post-mortem (раніше додано в `run_agent`).

### Що залишилось (опційно, по сигналу)

1. **Stateful confirmation flow для delete** — якщо в реальному використанні зловиш кейси випадкового видалення (Whisper "віддали" → "видали", або LLM не та подія). Треба:
   - Зберігати pending-операцію `("delete", event_id, summary)` між повідомленнями (Redis або таблиця).
   - Бот при `delete_event` спочатку питає "Видалити подію X? так/ні", виконує тільки на наступне "так".
   - Реалізувати по сигналу — поки немає, покладаємось на 30-денний Trash як safety net.
2. **`restore_event(event_id)` tool** — щоб не лазити в Calendar UI. API: `events.get` з `?showDeleted=true` → `events.update` з `status="confirmed"`. Корисний коли робитимемо stateful confirmation (юзер може сказати "повернути").
3. **Тести** на `update_event` / `delete_event` — особливо edge-кейси: half-update time (start без end), all-day vs timed mismatch, неіснуючий event_id.

---

## 3. Майбутнє масштабування channel-runners (NOT NOW)

### Поточний стан: один процес

Все стартує через `uvicorn app.main:app`:
- HTTP API + frontend
- Slack webhook
- Discord gateway (як background asyncio.Task)
- Telegram — webhook на проді (з валідним `WEBHOOK_URL`) або long-polling як background task локально

`bot.py` видалений; окремого worker-процесу немає. Раніше Discord стартував у двох місцях паралельно (uvicorn + bot.py) → race на `/link`. Колапс назад в один процес знімає проблему природно — клієнт один.

### Майбутнє масштабування (NOT NOW)

Одного процесу досить до ~10к активних юзерів. Реальний bottleneck — LLM-API rate limits, не FastAPI. Розділяти на канально-окремі сервіси — не треба, це підриває можливість безкоштовного хостингу і не дає виграшу при цьому навантаженні.

Коли реально перевалить за 10к активних — тоді робиться:
- HTTP layer (uvicorn) ← N replicas за load balancer
- Discord gateway ← винести в окремий процес з 1 інстансом (gateway не масштабується горизонтально). На цей момент знадобиться вернутись до концепції runner-скрипта, але вже свідомо.
- LLM-job queue (Celery/RQ + Redis) ← N workers, щоб HTTP-handler'и не блокувались на 2-5с виклику моделі

Поки про це не думати.

---
