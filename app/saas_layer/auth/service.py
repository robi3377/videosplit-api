import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.core.security import hash_password, verify_password
from app.saas_layer.db.models import OAuthAccount, OAuthProvider, PlanTier, User

logger = logging.getLogger(__name__)


async def register_user(
    email: str,
    password: str,
    full_name: Optional[str],
    db: AsyncSession,
) -> User:
    """
    Register a new user with email/password.
    Raises ValueError if email is already taken.
    """
    # Check for existing account
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing:
        raise ValueError("Email already registered")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        plan_tier=PlanTier.FREE,
        monthly_minutes_limit=100,
        monthly_minutes_used=0,
        last_usage_reset=datetime.now(timezone.utc),
        is_active=True,
        email_verified=False,
    )
    db.add(user)
    await db.flush()  # Assign ID without committing
    return user


async def authenticate_user(
    email: str,
    password: str,
    db: AsyncSession,
) -> Optional[User]:
    """
    Validate email + password. Updates last_login on success.
    Returns None if credentials are invalid.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password:
        return None
    if not verify_password(password, user.hashed_password):
        return None

    user.last_login = datetime.now(timezone.utc)
    return user


async def get_user_by_email(email: str, db: AsyncSession) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(user_id: int, db: AsyncSession) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_or_create_oauth_user(
    provider: str,
    provider_user_id: str,
    email: str,
    full_name: Optional[str],
    avatar_url: Optional[str],
    access_token: str,
    db: AsyncSession,
) -> User:
    """
    Find-or-create a user from an OAuth provider callback.
    Three cases:
    1. OAuthAccount exists → refresh tokens, return user
    2. User with email exists (no OAuth) → attach OAuth account
    3. Neither → create User + OAuthAccount
    """
    provider_enum = OAuthProvider(provider)

    # 1. Check for existing OAuth account
    result = await db.execute(
        select(OAuthAccount)
        .where(
            OAuthAccount.provider == provider_enum,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    oauth_account = result.scalar_one_or_none()

    if oauth_account:
        # Update token and return attached user
        oauth_account.access_token = access_token
        oauth_account.updated_at = datetime.now(timezone.utc)
        result2 = await db.execute(select(User).where(User.id == oauth_account.user_id))
        user = result2.scalar_one()
        user.last_login = datetime.now(timezone.utc)
        if avatar_url and not user.avatar_url:
            user.avatar_url = avatar_url
        return user

    # 2. Check for existing user with same email
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        # 3. Create new user (OAuth-only, no password, email pre-verified)
        user = User(
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
            plan_tier=PlanTier.FREE,
            monthly_minutes_limit=100,
            monthly_minutes_used=0,
            last_usage_reset=datetime.now(timezone.utc),
            is_active=True,
            email_verified=True,
        )
        db.add(user)
        await db.flush()

    # Attach OAuth account (covers case 2 and 3)
    new_oauth = OAuthAccount(
        user_id=user.id,
        provider=provider_enum,
        provider_user_id=provider_user_id,
        access_token=access_token,
    )
    db.add(new_oauth)
    await db.flush()

    user.last_login = datetime.now(timezone.utc)
    return user


async def reset_monthly_usage_if_needed(user: User, db: AsyncSession) -> User:
    """
    Lazily reset monthly_minutes_used if the last reset was in a prior calendar month.
    Called at the start of every split request.
    """
    now = datetime.now(timezone.utc)
    last_reset = user.last_usage_reset

    # Make last_reset timezone-aware if it isn't
    if last_reset.tzinfo is None:
        last_reset = last_reset.replace(tzinfo=timezone.utc)

    if last_reset.year < now.year or last_reset.month < now.month:
        logger.info(
            "Resetting monthly usage for user %d (last reset: %s)",
            user.id,
            last_reset,
        )
        user.monthly_minutes_used = 0
        user.last_usage_reset = now

    return user
