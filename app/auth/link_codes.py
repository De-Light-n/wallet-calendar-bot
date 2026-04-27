"""Generation and consumption of short-lived channel-link codes."""
from __future__ import annotations

import datetime
import secrets

from sqlalchemy.orm import Session

from app.database.models import ChannelAccount, LinkCode, OAuthToken, User

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # avoid confusable chars (0/O, 1/I)
_DEFAULT_TTL_MINUTES = 10


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _generate_code(length: int = 8) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def generate_link_code(
    db: Session,
    user: User,
    *,
    ttl_minutes: int = _DEFAULT_TTL_MINUTES,
) -> LinkCode:
    """Create and persist a new short-lived link code for the given user."""
    expires_at = _utcnow() + datetime.timedelta(minutes=ttl_minutes)
    for _ in range(8):
        candidate = _generate_code()
        existing = db.query(LinkCode).filter(LinkCode.code == candidate).first()
        if existing is None:
            link = LinkCode(code=candidate, user_id=user.id, expires_at=expires_at)
            db.add(link)
            db.commit()
            db.refresh(link)
            return link
    raise RuntimeError("Failed to generate a unique link code")


class LinkCodeError(Exception):
    """Raised when a link code is invalid, expired, or already used."""


def consume_link_code(
    db: Session,
    *,
    code: str,
    channel: str,
    external_user_id: str,
    username: str | None = None,
    display_name: str | None = None,
) -> User:
    """Bind the given external account to the user the link code belongs to.

    Effects:
    - Marks the LinkCode as used.
    - Reassigns or creates the ChannelAccount(channel, external_user_id) so it points
      to the link code's owner.
    - Deletes any orphan anonymous user that is left with no channels and no OAuth.
    """
    link = db.query(LinkCode).filter(LinkCode.code == code.strip().upper()).first()
    if link is None:
        raise LinkCodeError("Код не знайдено. Перевір, чи правильно ввів.")
    if link.used_at is not None:
        raise LinkCodeError("Цей код уже використано. Згенеруй новий на сайті.")
    now = _utcnow()
    expires_at = link.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
    if expires_at < now:
        raise LinkCodeError("Код прострочено. Згенеруй новий на сайті.")

    target_user = db.get(User, link.user_id)
    if target_user is None:
        raise LinkCodeError("Користувача-власника коду більше не існує.")

    existing_account = (
        db.query(ChannelAccount)
        .filter(
            ChannelAccount.channel == channel,
            ChannelAccount.external_user_id == external_user_id,
        )
        .first()
    )

    orphan_user_id: int | None = None
    if existing_account is not None:
        if existing_account.user_id != target_user.id:
            orphan_user_id = existing_account.user_id
            existing_account.user_id = target_user.id
        if username:
            existing_account.username = username
        if display_name:
            existing_account.display_name = display_name
    else:
        existing_account = ChannelAccount(
            user_id=target_user.id,
            channel=channel,
            external_user_id=external_user_id,
            username=username,
            display_name=display_name,
        )
        db.add(existing_account)

    if channel == "telegram":
        try:
            telegram_id = int(external_user_id)
        except (TypeError, ValueError):
            telegram_id = None

        if telegram_id is not None:
            # Re-linking can move Telegram identity from an anonymous user to a
            # web-authenticated user. Clear the previous owner first so the
            # unique users.telegram_id constraint is not violated.
            conflicting_user = (
                db.query(User)
                .filter(User.telegram_id == telegram_id, User.id != target_user.id)
                .first()
            )
            if conflicting_user is not None:
                conflicting_user.telegram_id = None
                db.flush()

            target_user.telegram_id = telegram_id

    link.used_at = now
    link.used_by_channel = channel
    link.used_by_external_id = external_user_id

    db.flush()

    # Delete the previous anonymous owner if it now has no channels and no OAuth.
    if orphan_user_id and orphan_user_id != target_user.id:
        orphan = db.get(User, orphan_user_id)
        if orphan is not None and orphan.email is None and orphan.oauth_token is None:
            remaining_accounts = (
                db.query(ChannelAccount).filter(ChannelAccount.user_id == orphan.id).count()
            )
            if remaining_accounts == 0:
                db.delete(orphan)

    db.commit()
    db.refresh(target_user)
    return target_user
