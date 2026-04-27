"""FastAPI dependencies for session-authenticated routes."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database.models import User
from app.database.session import get_db


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the logged-in user from the session cookie."""
    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user = db.get(User, user_id)
    if not user:
        # Session points to a deleted user — clear it to prevent loops.
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
