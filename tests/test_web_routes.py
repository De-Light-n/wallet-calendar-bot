"""Tests for multi-channel ingress routes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base, get_db
from fastapi import FastAPI

import app.channels.routes as channels_routes
from app.channels.routes import router as channels_router

app_for_tests = FastAPI()
app_for_tests.include_router(channels_router)


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

    app_for_tests.dependency_overrides[get_db] = override_get_db
    with TestClient(app_for_tests) as c:
        yield c
    app_for_tests.dependency_overrides.clear()


def test_slack_webhook_url_verification(client):
    resp = client.post(
        "/api/channels/slack/webhook",
        json={"type": "url_verification", "challenge": "abc123"},
    )
    assert resp.status_code == 200
    assert resp.json()["challenge"] == "abc123"


def test_webchat_message_success(client, monkeypatch):
    async def _fake_process_user_message(*, db, context, user_message):
        return f"echo:{user_message}"

    monkeypatch.setattr(channels_routes, "process_user_message", _fake_process_user_message)

    resp = client.post(
        "/api/channels/webchat/message",
        json={
            "external_user_id": "web-1",
            "text": "buy coffee 100 uah",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["response"].startswith("echo:")


def test_discord_webhook_success(client, monkeypatch):
    async def _fake_process_user_message(*, db, context, user_message):
        return "ok"

    monkeypatch.setattr(channels_routes, "process_user_message", _fake_process_user_message)

    resp = client.post(
        "/api/channels/discord/webhook",
        json={
            "id": "m1",
            "content": "remind me tomorrow at 9",
            "author": {"id": "d-user-1"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
