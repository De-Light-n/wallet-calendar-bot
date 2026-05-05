"""Google OAuth flow helpers built on google-auth-oauthlib."""
from __future__ import annotations

from typing import Any

import httpx
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.core.config import settings

# Identity scopes give us email/name/picture; the rest grant API access used by the agent.
SCOPES: list[str] = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def _client_config() -> dict[str, Any]:
    """Inline OAuth client config built from environment settings."""
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "project_id": settings.google_project_id,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def build_flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        state=state,
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def authorization_url(state: str) -> tuple[str, str | None]:
    flow = build_flow(state=state)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url, getattr(flow, "code_verifier", None)


def exchange_code(
    code: str,
    state: str,
    *,
    code_verifier: str | None = None,
) -> Credentials:
    flow = build_flow(state=state)

    fetch_kwargs: dict[str, str] = {"code": code}
    if code_verifier:
        fetch_kwargs["code_verifier"] = code_verifier

    flow.fetch_token(**fetch_kwargs)
    return flow.credentials


async def fetch_userinfo(creds: Credentials) -> dict[str, Any]:
    """Fetch the OpenID user profile (email, name, picture)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {creds.token}"},
        )
        resp.raise_for_status()
        return resp.json()
