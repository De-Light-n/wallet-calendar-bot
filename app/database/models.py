"""SQLAlchemy ORM models: User, OAuthToken, Expense."""
import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database.session import Base


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class User(Base):
    """Telegram user registered in the system."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String(64), nullable=True)
    full_name = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    oauth_token = relationship("OAuthToken", back_populates="user", uselist=False)
    expenses = relationship("Expense", back_populates="user")


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
