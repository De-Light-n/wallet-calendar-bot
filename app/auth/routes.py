"""Web authentication endpoints: Google OAuth init/callback, /me, logout."""
from __future__ import annotations

import datetime
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user
from app.auth.google_oauth import authorization_url, exchange_code, fetch_userinfo
from app.core.config import settings
from app.database.models import OAuthToken, User
from app.database.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

_STATE_KEY = "oauth_state"
_CODE_VERIFIER_KEY = "oauth_code_verifier"


def _state_hint(value: str | None) -> str:
    if not value:
        return "<none>"
    return f"{value[:8]}..."


@router.get("/google/init")
async def google_init(request: Request) -> RedirectResponse:
    """Start the Google OAuth flow."""
    client_ip = request.client.host if request.client else "unknown"
    logger.info("OAuth init requested from ip=%s", client_ip)

    state = secrets.token_urlsafe(24)
    request.session[_STATE_KEY] = state
    auth_url, code_verifier = authorization_url(state)
    request.session[_CODE_VERIFIER_KEY] = code_verifier

    logger.info(
        "OAuth init generated state=%s redirect_uri=%s has_code_verifier=%s",
        _state_hint(state),
        settings.google_redirect_uri,
        bool(code_verifier),
    )
    return RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Exchange the authorization code for tokens and persist the user."""
    logger.info(
        "OAuth callback received state=%s has_code=%s error=%s",
        _state_hint(state),
        bool(code),
        error or "<none>",
    )

    if error:
        logger.warning("OAuth callback returned provider error=%s", error)
        return RedirectResponse(f"{settings.web_app_url}/?auth_error={error}")

    expected_state = request.session.pop(_STATE_KEY, None)
    code_verifier = request.session.pop(_CODE_VERIFIER_KEY, None)
    if not state or not expected_state or state != expected_state:
        logger.warning(
            "OAuth callback invalid state: expected=%s got=%s",
            _state_hint(expected_state),
            _state_hint(state),
        )
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    if not code:
        logger.warning("OAuth callback missing authorization code")
        raise HTTPException(status_code=400, detail="Missing authorization code")
    if not code_verifier:
        logger.warning("OAuth callback missing PKCE code_verifier in session")
        return RedirectResponse(f"{settings.web_app_url}/?auth_error=missing_code_verifier")

    logger.info("OAuth callback exchanging authorization code for tokens")
    try:
        creds = exchange_code(code=code, state=state, code_verifier=code_verifier)
    except Exception:
        logger.exception("OAuth callback failed during token exchange")
        return RedirectResponse(
            f"{settings.web_app_url}/?auth_error=oauth_token_exchange_failed"
        )

    logger.info("OAuth callback fetching Google user profile")
    userinfo = await fetch_userinfo(creds)

    email = userinfo.get("email")
    if not email:
        logger.warning("OAuth callback: Google profile has no email")
        raise HTTPException(status_code=400, detail="Google did not return an email")

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        logger.info("OAuth callback creating new user for email=%s", email)
        user = User(
            email=email,
            full_name=userinfo.get("name"),
            picture_url=userinfo.get("picture"),
        )
        db.add(user)
        db.flush()
    else:
        logger.info("OAuth callback found existing user id=%s email=%s", user.id, email)
        if userinfo.get("name") and not user.full_name:
            user.full_name = userinfo["name"]
        if userinfo.get("picture"):
            user.picture_url = userinfo["picture"]

    token_expiry = creds.expiry
    if token_expiry is not None and token_expiry.tzinfo is None:
        token_expiry = token_expiry.replace(tzinfo=datetime.timezone.utc)

    if user.oauth_token is None:
        logger.info("OAuth callback storing first OAuth token row for user_id=%s", user.id)
        token_row = OAuthToken(
            user_id=user.id,
            access_token=creds.token,
            refresh_token=creds.refresh_token,
            token_expiry=token_expiry,
            scopes=" ".join(creds.scopes or []),
        )
        db.add(token_row)
    else:
        logger.info("OAuth callback updating OAuth token row for user_id=%s", user.id)
        token_row = user.oauth_token
        token_row.access_token = creds.token
        if creds.refresh_token:
            token_row.refresh_token = creds.refresh_token
        token_row.token_expiry = token_expiry
        token_row.scopes = " ".join(creds.scopes or [])

    db.commit()
    request.session["user_id"] = user.id

    logger.info(
        "OAuth callback success user_id=%s email=%s redirect=%s",
        user.id,
        email,
        settings.web_app_url,
    )

    return RedirectResponse(f"{settings.web_app_url}/", status_code=status.HTTP_302_FOUND)


@router.get("/me")
async def auth_me(user: User = Depends(current_user)) -> dict:
    """Return the logged-in user's profile and connected channels."""
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "picture_url": user.picture_url,
        "timezone": user.timezone,
        "base_currency": user.base_currency,
        "google_spreadsheet_id": user.google_spreadsheet_id,
        "spreadsheet_schema_version": user.spreadsheet_schema_version,
        "enabled_channels": list(settings.enabled_channels),
        "channels": [
            {
                "channel": ca.channel,
                "external_user_id": ca.external_user_id,
                "username": ca.username,
                "display_name": ca.display_name,
            }
            for ca in user.channel_accounts
        ],
    }


@router.post("/logout")
async def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
