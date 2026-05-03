"""Foreign exchange rates: lazy-fetch from NBU + per-day DB cache.

Why NBU over Frankfurter/ECB:
- Native UAH support — Frankfurter only has ECB rates which exclude UAH.
- Free, no API key, no documented rate limit.
- Official Ukrainian National Bank — same numbers banks publish.

Rate semantics: NBU quotes "1 unit of <currency> = <rate> UAH". The cache
always stores rates with quote="UAH"; cross conversions go through UAH.

Example: USD-to-UAH rate of 40.7 means `100 USD = 4070 UAH`.
"""
from __future__ import annotations

import datetime
import logging

import httpx
from sqlalchemy.orm import Session

from app.database.models import ExchangeRate

logger = logging.getLogger(__name__)

_NBU_URL = "https://bank.gov.ua/NBU_Exchange/exchange_site"
_HTTP_TIMEOUT_SECONDS = 8.0
# How many days back to look if NBU has no rate for the requested date — covers
# weekends/holidays when NBU doesn't publish.
_MAX_LOOKBACK_DAYS = 5

# Currencies we accept as a base. UAH is native; the rest are NBU-quoted majors
# we've verified are stable and useful for Ukrainian users. Add more as the
# need arises — NBU itself supports ~50.
SUPPORTED_BASE_CURRENCIES = (
    "UAH",
    "USD",
    "EUR",
    "GBP",
    "PLN",
    "CHF",
    "CAD",
    "JPY",
    "CNY",
)


def is_supported_base_currency(code: str) -> bool:
    return (code or "").upper().strip() in SUPPORTED_BASE_CURRENCIES


class FxError(Exception):
    """Raised when an exchange rate can't be fetched and isn't in cache."""


async def _fetch_nbu_rate(
    currency: str,
    on_date: datetime.date,
) -> tuple[float, datetime.date]:
    """Call NBU API for `currency`/UAH on the given date.

    Returns ``(rate, actual_date)`` — actual_date may differ from `on_date` if
    NBU has no quote on that day (weekend/holiday) and returns the closest
    prior one. Raises FxError on network failure or unknown currency.
    """
    params = {
        "valcode": currency,
        "date": on_date.strftime("%Y%m%d"),
        "json": "",  # NBU's idiosyncratic flag — must be present, value ignored.
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(_NBU_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("NBU FX fetch failed | %s on %s: %s", currency, on_date, exc)
        raise FxError(f"NBU API request failed: {exc}") from exc

    if not data or not isinstance(data, list):
        raise FxError(f"NBU returned no rate for {currency} on {on_date}")

    row = data[0]
    rate = row.get("rate")
    actual_date_str = row.get("exchangedate")
    if rate is None:
        raise FxError(f"NBU response missing rate field: {row}")

    actual_date = on_date
    if isinstance(actual_date_str, str):
        # NBU returns DD.MM.YYYY format.
        try:
            d, m, y = actual_date_str.split(".")
            actual_date = datetime.date(int(y), int(m), int(d))
        except (ValueError, AttributeError):
            pass

    return float(rate), actual_date


async def get_or_fetch_rate(
    db: Session,
    *,
    currency: str,
    on_date: datetime.date,
) -> float:
    """Return UAH-per-unit rate for `currency`, cached per day.

    Fast paths:
    - UAH itself → 1.0 (no DB, no network).
    - Cache hit on (currency, "UAH", on_date) → no network call.

    Slow path (cache miss): hit NBU API. NBU may return the rate for an
    earlier date (weekends/holidays) — we cache it under both the requested
    date AND the actual returned date so future lookups in either direction
    find it.
    """
    currency = currency.upper().strip()
    if currency in ("UAH", ""):
        return 1.0

    cached = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.base == currency,
            ExchangeRate.quote == "UAH",
            ExchangeRate.as_of_date == on_date,
        )
        .first()
    )
    if cached is not None:
        return cached.rate

    last_error: Exception | None = None
    for offset in range(_MAX_LOOKBACK_DAYS + 1):
        try_date = on_date - datetime.timedelta(days=offset)
        try:
            rate, actual_date = await _fetch_nbu_rate(currency, try_date)
        except FxError as exc:
            last_error = exc
            continue

        # Cache under both the requested date and the actual published date,
        # so future queries for either get a cache hit. UNIQUE constraint
        # protects against duplicate rows across concurrent transactions.
        for cache_date in {on_date, actual_date}:
            existing = (
                db.query(ExchangeRate)
                .filter(
                    ExchangeRate.base == currency,
                    ExchangeRate.quote == "UAH",
                    ExchangeRate.as_of_date == cache_date,
                )
                .first()
            )
            if existing is None:
                db.add(
                    ExchangeRate(
                        base=currency,
                        quote="UAH",
                        rate=rate,
                        as_of_date=cache_date,
                    )
                )
        db.commit()
        logger.info(
            "FX rate cached | %s/UAH = %.4f for %s (NBU returned %s)",
            currency,
            rate,
            on_date,
            actual_date,
        )
        return rate

    raise FxError(
        f"No FX rate for {currency} within {_MAX_LOOKBACK_DAYS} days back from "
        f"{on_date}: {last_error}"
    )


async def convert(
    db: Session,
    *,
    amount: float,
    from_currency: str,
    to_currency: str,
    on_date: datetime.date | None = None,
) -> float:
    """Convert `amount` between currencies using cached NBU rates.

    Cross conversions go through UAH (NBU's only quote currency). Both legs
    use the same `on_date` so the result is internally consistent.

    Returns ``amount`` unchanged when from == to (no DB or network access).
    """
    if on_date is None:
        on_date = datetime.date.today()

    from_currency = from_currency.upper().strip()
    to_currency = to_currency.upper().strip()
    if from_currency == to_currency:
        return amount

    # Step 1: source → UAH.
    if from_currency == "UAH":
        amount_in_uah = amount
    else:
        rate_from = await get_or_fetch_rate(db, currency=from_currency, on_date=on_date)
        amount_in_uah = amount * rate_from

    # Step 2: UAH → target.
    if to_currency == "UAH":
        return amount_in_uah
    rate_to = await get_or_fetch_rate(db, currency=to_currency, on_date=on_date)
    return amount_in_uah / rate_to
