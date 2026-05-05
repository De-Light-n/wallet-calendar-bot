"""Tests for the NBU FX client + per-day exchange-rate cache."""
from __future__ import annotations

import asyncio
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.integrations.fx as fx
from app.database.models import ExchangeRate, User
from app.database.session import Base


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _patch_nbu(monkeypatch, rates_by_date_currency):
    """Replace _fetch_nbu_rate with a stub that reads from a dict.

    `rates_by_date_currency` maps (currency, date) -> (rate, actual_date).
    Calls for keys not in the dict raise FxError to simulate "no rate".
    """
    calls: list[tuple[str, datetime.date]] = []

    async def fake(currency: str, on_date: datetime.date):
        calls.append((currency, on_date))
        key = (currency, on_date)
        if key not in rates_by_date_currency:
            raise fx.FxError(f"stub: no rate for {key}")
        return rates_by_date_currency[key]

    monkeypatch.setattr(fx, "_fetch_nbu_rate", fake)
    return calls


# ---------------------------------------------------------------------------
# User model: base_currency default
# ---------------------------------------------------------------------------


def test_user_default_base_currency_is_uah(db_session):
    user = User(telegram_id=1)
    db_session.add(user)
    db_session.commit()
    assert user.base_currency == "UAH"


# ---------------------------------------------------------------------------
# UAH fast-path: no DB, no network
# ---------------------------------------------------------------------------


def test_get_rate_uah_short_circuits(db_session, monkeypatch):
    calls = _patch_nbu(monkeypatch, {})

    rate = asyncio.run(
        fx.get_or_fetch_rate(db_session, currency="UAH", on_date=datetime.date(2026, 5, 2))
    )

    assert rate == 1.0
    assert calls == []  # Never even tried to hit NBU.
    assert db_session.query(ExchangeRate).count() == 0


# ---------------------------------------------------------------------------
# Cache hit: rate already in DB → no network
# ---------------------------------------------------------------------------


def test_get_rate_uses_cache_when_present(db_session, monkeypatch):
    on_date = datetime.date(2026, 5, 2)
    db_session.add(
        ExchangeRate(base="USD", quote="UAH", rate=40.7, as_of_date=on_date)
    )
    db_session.commit()
    calls = _patch_nbu(monkeypatch, {})  # If called, will fail.

    rate = asyncio.run(
        fx.get_or_fetch_rate(db_session, currency="USD", on_date=on_date)
    )

    assert rate == 40.7
    assert calls == []


# ---------------------------------------------------------------------------
# Cache miss: NBU is hit, result is cached for both requested + actual date
# ---------------------------------------------------------------------------


def test_get_rate_fetches_and_caches_on_miss(db_session, monkeypatch):
    on_date = datetime.date(2026, 5, 2)
    _patch_nbu(monkeypatch, {("USD", on_date): (40.5, on_date)})

    rate = asyncio.run(
        fx.get_or_fetch_rate(db_session, currency="USD", on_date=on_date)
    )

    assert rate == 40.5
    cached = (
        db_session.query(ExchangeRate)
        .filter_by(base="USD", quote="UAH", as_of_date=on_date)
        .first()
    )
    assert cached is not None
    assert cached.rate == 40.5


def test_second_call_uses_cache_after_first_fetch(db_session, monkeypatch):
    on_date = datetime.date(2026, 5, 2)
    calls = _patch_nbu(monkeypatch, {("USD", on_date): (40.5, on_date)})

    asyncio.run(fx.get_or_fetch_rate(db_session, currency="USD", on_date=on_date))
    asyncio.run(fx.get_or_fetch_rate(db_session, currency="USD", on_date=on_date))
    asyncio.run(fx.get_or_fetch_rate(db_session, currency="USD", on_date=on_date))

    # Three logical calls → exactly one network call.
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Lookback: NBU has no Sunday rate → falls back to Friday
# ---------------------------------------------------------------------------


def test_lookback_fallback_when_nbu_returns_earlier_date(db_session, monkeypatch):
    # Simulate a Sunday with no NBU rate; Friday's rate is what NBU would
    # return when asked for Sunday. We make Sunday explicitly missing and only
    # let the Friday call succeed.
    sunday = datetime.date(2026, 5, 3)
    saturday = datetime.date(2026, 5, 2)
    friday = datetime.date(2026, 5, 1)
    _patch_nbu(
        monkeypatch,
        {
            # sunday and saturday absent from the mapping → raises FxError.
            ("USD", friday): (40.4, friday),
        },
    )

    rate = asyncio.run(
        fx.get_or_fetch_rate(db_session, currency="USD", on_date=sunday)
    )
    assert rate == 40.4

    # Both Sunday (requested) and Friday (actual) cached so future Sunday
    # queries hit cache without retrying lookback.
    sunday_row = (
        db_session.query(ExchangeRate).filter_by(base="USD", as_of_date=sunday).first()
    )
    friday_row = (
        db_session.query(ExchangeRate).filter_by(base="USD", as_of_date=friday).first()
    )
    assert sunday_row is not None and sunday_row.rate == 40.4
    assert friday_row is not None and friday_row.rate == 40.4
    # Saturday should NOT be cached (we only cache requested + actual).
    saturday_row = (
        db_session.query(ExchangeRate).filter_by(base="USD", as_of_date=saturday).first()
    )
    assert saturday_row is None


# ---------------------------------------------------------------------------
# Convert: same currency → exact, UAH↔X, cross via UAH
# ---------------------------------------------------------------------------


def test_convert_same_currency_returns_input(db_session, monkeypatch):
    calls = _patch_nbu(monkeypatch, {})
    out = asyncio.run(
        fx.convert(
            db_session,
            amount=100.0,
            from_currency="USD",
            to_currency="USD",
            on_date=datetime.date(2026, 5, 2),
        )
    )
    assert out == 100.0
    assert calls == []  # No FX work needed.


def test_convert_foreign_to_uah(db_session, monkeypatch):
    on_date = datetime.date(2026, 5, 2)
    _patch_nbu(monkeypatch, {("USD", on_date): (40.0, on_date)})

    out = asyncio.run(
        fx.convert(
            db_session,
            amount=100.0,
            from_currency="USD",
            to_currency="UAH",
            on_date=on_date,
        )
    )
    assert out == pytest.approx(4000.0)


def test_convert_uah_to_foreign(db_session, monkeypatch):
    on_date = datetime.date(2026, 5, 2)
    _patch_nbu(monkeypatch, {("USD", on_date): (40.0, on_date)})

    out = asyncio.run(
        fx.convert(
            db_session,
            amount=4000.0,
            from_currency="UAH",
            to_currency="USD",
            on_date=on_date,
        )
    )
    assert out == pytest.approx(100.0)


def test_convert_cross_via_uah(db_session, monkeypatch):
    on_date = datetime.date(2026, 5, 2)
    _patch_nbu(
        monkeypatch,
        {
            ("USD", on_date): (40.0, on_date),
            ("EUR", on_date): (44.0, on_date),
        },
    )

    # 100 USD = 4000 UAH → 4000 / 44 EUR ≈ 90.91 EUR
    out = asyncio.run(
        fx.convert(
            db_session,
            amount=100.0,
            from_currency="USD",
            to_currency="EUR",
            on_date=on_date,
        )
    )
    assert out == pytest.approx(4000.0 / 44.0)


# ---------------------------------------------------------------------------
# FxError when nothing is reachable
# ---------------------------------------------------------------------------


def test_get_rate_raises_when_no_lookback_succeeds(db_session, monkeypatch):
    on_date = datetime.date(2026, 5, 2)
    _patch_nbu(monkeypatch, {})  # Every date raises.

    with pytest.raises(fx.FxError):
        asyncio.run(
            fx.get_or_fetch_rate(db_session, currency="USD", on_date=on_date)
        )
