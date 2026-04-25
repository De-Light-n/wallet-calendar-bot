"""Tests for database models and the finance tool."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import ChannelAccount, Expense, OAuthToken, User
from app.database.session import Base


@pytest.fixture()
def db_session():
    """Provide an in-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

def test_create_user(db_session):
    user = User(telegram_id=111222333, username="testuser", full_name="Test User")
    db_session.add(user)
    db_session.commit()

    found = db_session.query(User).filter_by(telegram_id=111222333).first()
    assert found is not None
    assert found.username == "testuser"
    assert found.full_name == "Test User"


def test_create_oauth_token(db_session):
    user = User(telegram_id=222333444)
    db_session.add(user)
    db_session.flush()

    token = OAuthToken(
        user_id=user.id,
        access_token="access_abc",
        refresh_token="refresh_xyz",
        scopes="https://www.googleapis.com/auth/calendar",
    )
    db_session.add(token)
    db_session.commit()

    found_user = db_session.query(User).filter_by(telegram_id=222333444).first()
    assert found_user.oauth_token is not None
    assert found_user.oauth_token.access_token == "access_abc"


def test_create_expense(db_session):
    user = User(telegram_id=333444555)
    db_session.add(user)
    db_session.flush()

    expense = Expense(
        user_id=user.id,
        amount=150.0,
        currency="UAH",
        category="food",
        description="Кава",
    )
    db_session.add(expense)
    db_session.commit()

    found = db_session.query(Expense).filter_by(user_id=user.id).first()
    assert found.amount == 150.0
    assert found.currency == "UAH"
    assert found.category == "food"


def test_create_channel_account(db_session):
    user = User(username="multi")
    db_session.add(user)
    db_session.flush()

    account = ChannelAccount(
        user_id=user.id,
        channel="telegram",
        external_user_id="123456",
        username="multi_user",
    )
    db_session.add(account)
    db_session.commit()

    found = (
        db_session.query(ChannelAccount)
        .filter_by(channel="telegram", external_user_id="123456")
        .first()
    )
    assert found is not None
    assert found.user_id == user.id


# ---------------------------------------------------------------------------
# Finance tool tests
# ---------------------------------------------------------------------------

import asyncio

from app.tools.finance_tool import add_expense, get_expenses


def test_add_expense_user_not_found(db_session):
    result = asyncio.run(
        add_expense(telegram_id=999999999, db=db_session, amount=50.0)
    )
    assert result["status"] == "error"
    assert "not found" in result["error"]


def test_add_expense_success(db_session):
    user = User(telegram_id=444555666)
    db_session.add(user)
    db_session.commit()

    result = asyncio.run(
        add_expense(
            telegram_id=444555666,
            db=db_session,
            amount=200.0,
            currency="UAH",
            category="food",
            description="Обід",
        )
    )
    assert result["status"] == "ok"
    assert result["amount"] == 200.0
    assert result["currency"] == "UAH"
    assert result["category"] == "food"


def test_add_expense_success_with_user_id(db_session):
    user = User(telegram_id=777888999)
    db_session.add(user)
    db_session.commit()

    result = asyncio.run(
        add_expense(
            user_id=user.id,
            db=db_session,
            amount=99.5,
            currency="usd",
            category="other",
            description="test",
        )
    )
    assert result["status"] == "ok"
    assert result["currency"] == "USD"


def test_get_expenses_success(db_session):
    user = User(telegram_id=555666777)
    db_session.add(user)
    db_session.flush()

    for i in range(3):
        db_session.add(Expense(user_id=user.id, amount=float(i * 10), currency="UAH"))
    db_session.commit()

    result = asyncio.run(
        get_expenses(telegram_id=555666777, db=db_session)
    )
    assert result["status"] == "ok"
    assert len(result["expenses"]) == 3


def test_get_expenses_user_not_found(db_session):
    result = asyncio.run(
        get_expenses(telegram_id=888888888, db=db_session)
    )
    assert result["status"] == "error"
