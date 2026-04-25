"""Channel-agnostic message orchestrator."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent.llm_client import run_agent
from app.core.context import AgentRequestContext
from app.database.models import ChannelAccount, User


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
        return account.user

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
    return await run_agent(
        user_message=user_message,
        user_id=user.id,
        db_session=db,
        context=context,
    )
