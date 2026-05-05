"""Channel-agnostic message orchestrator."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.agent.llm_client import run_agent
from app.core.context import AgentRequestContext
from app.database.models import ChannelAccount, User

logger = logging.getLogger(__name__)


def get_or_create_user_for_channel(
    db: Session,
    *,
    channel: str,
    external_user_id: str,
    username: str | None = None,
    full_name: str | None = None,
) -> User:
    """Resolve a user by linked channel account or create one."""
    account = (
        db.query(ChannelAccount)
        .filter(
            ChannelAccount.channel == channel,
            ChannelAccount.external_user_id == external_user_id,
        )
        .first()
    )
    if account:
        logger.debug(
            "Resolved existing user id=%s via channel=%s external_user_id=%s",
            account.user_id,
            channel,
            external_user_id,
        )
        return account.user

    logger.info(
        "Creating new user for channel=%s external_user_id=%s username=%s",
        channel,
        external_user_id,
        username,
    )
    user = User(username=username, full_name=full_name)
    if channel == "telegram":
        try:
            user.telegram_id = int(external_user_id)
        except ValueError:
            user.telegram_id = None

    db.add(user)
    db.flush()

    account = ChannelAccount(
        user_id=user.id,
        channel=channel,
        external_user_id=external_user_id,
        username=username,
        display_name=full_name,
    )
    db.add(account)
    db.commit()
    db.refresh(user)
    logger.info(
        "Created user id=%s linked to channel=%s external_user_id=%s",
        user.id,
        channel,
        external_user_id,
    )
    return user


async def process_user_message(
    *,
    db: Session,
    context: AgentRequestContext,
    user_message: str,
) -> str:
    """Run the assistant pipeline for a normalized message."""
    user = get_or_create_user_for_channel(
        db,
        channel=context.channel,
        external_user_id=context.external_user_id,
    )
    # Prefer the user's saved timezone over the channel default ("UTC").
    if getattr(user, "timezone", None):
        context.timezone = user.timezone

    logger.info(
        "process_user_message: user_id=%s channel=%s tz=%s correlation_id=%s "
        "message_len=%s has_oauth_token=%s has_spreadsheet=%s",
        user.id,
        context.channel,
        context.timezone,
        context.correlation_id,
        len(user_message),
        bool(user.oauth_token),
        bool(user.google_spreadsheet_id),
    )

    return await run_agent(
        user_message=user_message,
        user_id=user.id,
        db_session=db,
        context=context,
    )
