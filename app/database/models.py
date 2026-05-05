"""SQLAlchemy ORM models: user identity, auth tokens, and expenses."""
import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database.session import Base


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class User(Base):
    """Core user profile shared across multiple channels."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=True)
    username = Column(String(64), nullable=True)
    full_name = Column(String(128), nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    picture_url = Column(Text, nullable=True)
    timezone = Column(String(64), nullable=False, default="UTC", server_default="UTC")
    base_currency = Column(
        String(8), nullable=False, default="UAH", server_default="UAH"
    )
    google_spreadsheet_id = Column(String(128), nullable=True)
    # Tracks the layout of the user's spreadsheet so old 7-column ledgers keep
    # working while new ones are provisioned with the 9-column multi-currency
    # schema. Bumped whenever _TRANSACTIONS_HEADER / dashboard formulas change.
    spreadsheet_schema_version = Column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    oauth_token = relationship("OAuthToken", back_populates="user", uselist=False)
    expenses = relationship("Expense", back_populates="user")
    channel_accounts = relationship("ChannelAccount", back_populates="user")


class ChannelAccount(Base):
    """External account mapping for a specific messaging channel."""

    __tablename__ = "channel_accounts"
    __table_args__ = (
        UniqueConstraint("channel", "external_user_id", name="uq_channel_external_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    channel = Column(String(32), index=True, nullable=False)
    external_user_id = Column(String(255), index=True, nullable=False)
    username = Column(String(128), nullable=True)
    display_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User", back_populates="channel_accounts")


class OAuthToken(Base):
    """Stores Google OAuth2 tokens for a user."""

    __tablename__ = "oauth_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime(timezone=True), nullable=True)
    scopes = Column(Text, nullable=True)

    user = relationship("User", back_populates="oauth_token")


class Expense(Base):
    """Individual expense entry linked to a user."""

    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="UAH")
    category = Column(String(64), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User", back_populates="expenses")


class ExchangeRate(Base):
    """Per-day cache of FX rates fetched from NBU.

    NBU quotes everything as "1 unit of <base> = <rate> UAH", so for our
    purposes ``quote`` is always "UAH". We still store it as a column so the
    schema can evolve to non-NBU sources later without a migration.
    """

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("base", "quote", "as_of_date", name="uq_rate_per_day"),
    )

    id = Column(Integer, primary_key=True)
    base = Column(String(8), nullable=False, index=True)
    quote = Column(String(8), nullable=False, default="UAH")
    rate = Column(Float, nullable=False)
    as_of_date = Column(Date, nullable=False, index=True)
    fetched_at = Column(DateTime(timezone=True), default=_utcnow)


class LinkCode(Base):
    """Short-lived code used to attach a messaging channel to a registered user."""

    __tablename__ = "link_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    used_by_channel = Column(String(32), nullable=True)
    used_by_external_id = Column(String(255), nullable=True)

    user = relationship("User")
