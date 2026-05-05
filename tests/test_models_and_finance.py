"""Tests for database models and the finance tool."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.link_codes import consume_link_code, generate_link_code
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
    assert found.google_spreadsheet_id is None


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


def test_consume_link_code_relinks_existing_telegram_id_without_unique_violation(db_session):
    telegram_external_id = "1408810076"
    telegram_id = int(telegram_external_id)

    # User from web OAuth flow.
    web_user = User(email="web@example.com", full_name="Web User")
    # Anonymous user auto-created earlier by Telegram channel.
    telegram_user = User(telegram_id=telegram_id, username="tg_user")
    db_session.add_all([web_user, telegram_user])
    db_session.flush()

    db_session.add(
        ChannelAccount(
            user_id=telegram_user.id,
            channel="telegram",
            external_user_id=telegram_external_id,
            username="old_username",
            display_name="Old Name",
        )
    )
    db_session.commit()

    link = generate_link_code(db_session, web_user)
    linked_user = consume_link_code(
        db_session,
        code=link.code,
        channel="telegram",
        external_user_id=telegram_external_id,
        username="new_username",
        display_name="New Name",
    )

    assert linked_user.id == web_user.id
    assert linked_user.telegram_id == telegram_id

    linked_account = (
        db_session.query(ChannelAccount)
        .filter_by(channel="telegram", external_user_id=telegram_external_id)
        .first()
    )
    assert linked_account is not None
    assert linked_account.user_id == web_user.id

    # Old anonymous telegram user should be removed after reassignment.
    assert db_session.get(User, telegram_user.id) is None


# ---------------------------------------------------------------------------
# Finance tool tests
# ---------------------------------------------------------------------------

import asyncio
from types import SimpleNamespace

import app.tools.finance_tool as finance_tool
from app.tools.finance_tool import record_transaction


def test_record_transaction_user_not_found(db_session):
    result = asyncio.run(
        record_transaction(
            telegram_id=999999999,
            db=db_session,
            transaction_type="Expense",
            amount=50.0,
            category="Food & Dining",
            description="кава",
        )
    )
    assert result["status"] == "error"
    assert "not found" in result["error"]


def test_record_transaction_missing_google_connection(db_session):
    user = User(telegram_id=444555666)
    db_session.add(user)
    db_session.commit()

    result = asyncio.run(
        record_transaction(
            telegram_id=444555666,
            db=db_session,
            transaction_type="Expense",
            amount=200.0,
            currency="UAH",
            category="Food & Dining",
            description="Обід",
        )
    )
    assert result["status"] == "error"
    assert "Google account is not connected" in result["error"]


def test_record_transaction_invalid_category(db_session, monkeypatch):
    user = User(telegram_id=777888999)
    db_session.add(user)
    db_session.commit()

    monkeypatch.setattr(finance_tool, "_get_google_credentials", lambda *_, **__: object())

    result = asyncio.run(
        record_transaction(
            user_id=user.id,
            db=db_session,
            transaction_type="Income",
            amount=99.5,
            currency="usd",
            category="Other",
            description="test",
        )
    )
    assert result["status"] == "error"
    assert "Invalid category" in result["error"]


def test_record_transaction_success_creates_sheet_and_appends_row(db_session, monkeypatch):
    user = User(telegram_id=555666777)
    db_session.add(user)
    db_session.flush()
    db_session.add(
        OAuthToken(
            user_id=user.id,
            access_token="access_abc",
            refresh_token="refresh_xyz",
            scopes=(
                "https://www.googleapis.com/auth/spreadsheets "
                "https://www.googleapis.com/auth/drive.file"
            ),
        )
    )
    db_session.commit()

    monkeypatch.setattr(finance_tool, "_get_google_credentials", lambda *_, **__: object())
    monkeypatch.setattr(
        finance_tool,
        "settings",
        SimpleNamespace(google_template_spreadsheet_id="template-123"),
    )

    state: dict[str, object] = {}

    class _DriveCopyRequest:
        def execute(self):
            return {"id": "sheet-xyz"}

    class _DriveFilesApi:
        def copy(self, **kwargs):
            state["drive_copy_kwargs"] = kwargs
            return _DriveCopyRequest()

    class _DriveService:
        def files(self):
            return _DriveFilesApi()

    class _SheetsAppendRequest:
        def execute(self):
            return {"updates": {"updatedRange": "Transactions!A2:G2"}}

    class _SheetsValuesApi:
        def append(self, **kwargs):
            state["sheets_append_kwargs"] = kwargs
            return _SheetsAppendRequest()

    class _SheetsSpreadsheetsApi:
        def values(self):
            return _SheetsValuesApi()

    class _SheetsService:
        def spreadsheets(self):
            return _SheetsSpreadsheetsApi()

    def _fake_build(service_name, version, credentials=None, cache_discovery=False):
        if service_name == "drive":
            return _DriveService()
        if service_name == "sheets":
            return _SheetsService()
        raise AssertionError(f"Unexpected service requested: {service_name} {version}")

    monkeypatch.setattr(finance_tool, "build", _fake_build)

    result = asyncio.run(
        record_transaction(
            telegram_id=555666777,
            db=db_session,
            transaction_type="Expense",
            amount=350.0,
            currency="uah",
            category="Transportation",
            description="таксі",
        )
    )

    assert result["status"] == "ok"
    assert result["spreadsheet_id"] == "sheet-xyz"
    assert result["transaction_type"] == "Expense"
    assert result["amount"] == 350.0
    assert result["currency"] == "UAH"
    assert result["category"] == "Transportation"
    assert result["updated_range"] == "Transactions!A2:G2"

    saved_user = db_session.query(User).filter_by(id=user.id).first()
    assert saved_user is not None
    assert saved_user.google_spreadsheet_id == "sheet-xyz"

    assert state["drive_copy_kwargs"] == {
        "fileId": "template-123",
        "body": {"name": f"Wallet Ledger - user-{user.id}"},
        "fields": "id",
    }

    append_kwargs = state["sheets_append_kwargs"]
    assert append_kwargs["spreadsheetId"] == "sheet-xyz"
    assert append_kwargs["range"] == "Transactions!A:G"
    assert append_kwargs["valueInputOption"] == "USER_ENTERED"
    assert append_kwargs["insertDataOption"] == "INSERT_ROWS"
    assert len(append_kwargs["body"]["values"]) == 1
    appended_row = append_kwargs["body"]["values"][0]
    assert len(appended_row) == 7
    assert appended_row[2] == "Expense"
    assert appended_row[3] == 350.0
    assert appended_row[4] == "UAH"
    assert appended_row[5] == "Transportation"
    assert appended_row[6] == "таксі"
