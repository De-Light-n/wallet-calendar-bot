"""Tests for the FastAPI web routes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base, get_db
from app.web.routes import router

# Build a minimal FastAPI app just with the web router so we don't need
# a Telegram token or running bot
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

test_app = FastAPI()
test_app.include_router(router)


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_engine):
    TestingSession = sessionmaker(bind=db_engine)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as c:
        yield c
    test_app.dependency_overrides.clear()


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Wallet Calendar Bot" in resp.text


def test_login_page(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Google" in resp.text


def test_auth_google_redirect(client):
    resp = client.get("/auth/google", follow_redirects=False)
    assert resp.status_code in (302, 307)
    location = resp.headers.get("location", "")
    assert location.startswith("https://accounts.google.com/o/oauth2/")


def test_auth_google_with_state(client):
    resp = client.get("/auth/google?telegram_id=123456", follow_redirects=False)
    assert resp.status_code in (302, 307)
    location = resp.headers.get("location", "")
    assert location.startswith("https://accounts.google.com/")
    assert "state=123456" in location


def test_dashboard_no_user(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Дашборд" in resp.text


def test_auth_callback_missing_code(client):
    resp = client.get("/auth/google/callback")
    assert resp.status_code == 400


def test_auth_callback_with_error(client):
    resp = client.get("/auth/google/callback?error=access_denied")
    assert resp.status_code == 400
