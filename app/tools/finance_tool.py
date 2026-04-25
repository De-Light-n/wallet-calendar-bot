"""Finance tool – records expense entries for a user."""
from __future__ import annotations

import datetime
import os
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import Expense, User


def _resolve_user(
    db: Session,
    *,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> User | None:
    """Resolve a user by internal ID or legacy telegram ID."""
    if user_id is not None:
        return db.query(User).filter(User.id == user_id).first()
    if telegram_id is not None:
        return db.query(User).filter(User.telegram_id == telegram_id).first()
    return None


async def add_expense(
    db: Session,
    amount: float,
    currency: str = "UAH",
    category: str | None = None,
    description: str | None = None,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> dict[str, Any]:
    """Record a new expense for the given user.

    Args:
        user_id:      Internal user ID.
        db:           Database session.
        amount:       Monetary amount.
        currency:     Currency code (default: UAH).
        category:     Expense category.
        description:  Short description of the expense.

    Returns:
        Dict with ``status`` and ``expense_id`` on success, or ``error`` on failure.
    """
    user = _resolve_user(db, user_id=user_id, telegram_id=telegram_id)
    if not user:
        return {
            "status": "error",
            "error": "User not found. Please start the bot with /start first.",
        }

    expense = Expense(
        user_id=user.id,
        amount=amount,
        currency=currency.upper(),
        category=category or "other",
        description=description,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)

    return {
        "status": "ok",
        "expense_id": expense.id,
        "amount": expense.amount,
        "currency": expense.currency,
        "category": expense.category,
        "description": expense.description,
    }


async def get_expenses(
    db: Session,
    limit: int = 10,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> dict[str, Any]:
    """Retrieve the most recent expenses for a user.

    Args:
        user_id:     Internal user ID.
        db:          Database session.
        limit:       Maximum number of records to return (default: 10).

    Returns:
        Dict with ``status`` and ``expenses`` list on success.
    """
    user = _resolve_user(db, user_id=user_id, telegram_id=telegram_id)
    if not user:
        return {"status": "error", "error": "User not found."}

    records = (
        db.query(Expense)
        .filter(Expense.user_id == user.id)
        .order_by(Expense.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "status": "ok",
        "expenses": [
            {
                "id": e.id,
                "amount": e.amount,
                "currency": e.currency,
                "category": e.category,
                "description": e.description,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in records
        ],
    }
