"""Web routes: registration, OAuth2 login with Google, dashboard."""
from __future__ import annotations

import os
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.models import OAuthToken, User
from app.database.session import get_db

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "openid",
    "email",
    "profile",
]


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Landing page."""
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Login page with Google OAuth button."""
    return templates.TemplateResponse(request=request, name="login.html")


@router.get("/auth/google")
async def auth_google(request: Request) -> RedirectResponse:
    """Redirect the user to Google's OAuth2 consent screen."""
    params = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"),
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    # Preserve telegram_id passed as query param so we can link OAuth to the user
    telegram_id = request.query_params.get("telegram_id")
    if telegram_id:
        params["state"] = telegram_id
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


@router.get("/auth/google/callback")
async def auth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Handle Google OAuth2 callback, exchange code for tokens, store them."""
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    token_data = token_resp.json()
    if "error" in token_data:
        raise HTTPException(status_code=400, detail=token_data["error"])

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    scopes = token_data.get("scope", " ".join(GOOGLE_SCOPES))

    # Fetch Google user info to identify the user
    async with httpx.AsyncClient() as client:
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    userinfo = userinfo_resp.json()

    telegram_id_str = state  # passed via OAuth state param
    if telegram_id_str:
        try:
            telegram_id = int(telegram_id_str)
        except ValueError:
            telegram_id = None
    else:
        telegram_id = None

    # Find or create user
    user: User | None = None
    if telegram_id:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        # Create a placeholder user (full Telegram registration happens via /start)
        user = User(
            telegram_id=telegram_id or 0,
            username=userinfo.get("email"),
            full_name=userinfo.get("name"),
        )
        db.add(user)
        db.flush()

    # Upsert OAuth token
    token_record = db.query(OAuthToken).filter(OAuthToken.user_id == user.id).first()
    if token_record:
        token_record.access_token = access_token
        token_record.refresh_token = refresh_token or token_record.refresh_token
        token_record.scopes = scopes
    else:
        token_record = OAuthToken(
            user_id=user.id,
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=scopes,
        )
        db.add(token_record)

    db.commit()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user_name": userinfo.get("name", ""),
            "user_email": userinfo.get("email", ""),
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    telegram_id: int | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Simple dashboard showing recent expenses."""
    expenses = []
    if telegram_id:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if user:
            from app.database.models import Expense

            expenses = (
                db.query(Expense)
                .filter(Expense.user_id == user.id)
                .order_by(Expense.created_at.desc())
                .limit(20)
                .all()
            )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "expenses": expenses,
            "user_name": "",
            "user_email": "",
        },
    )
