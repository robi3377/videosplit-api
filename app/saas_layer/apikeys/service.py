from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.core.security import generate_api_key
from app.saas_layer.db.models import APIKey, User


async def create_api_key(
    user: User,
    name: str,
    db: AsyncSession,
) -> tuple[APIKey, str]:
    """
    Generate and persist a new API key for the given user.
    Returns (APIKey ORM object, plaintext_key).
    The plaintext key is shown ONCE — only the hash is stored.
    """
    plaintext, key_hash = generate_api_key()
    api_key = APIKey(
        user_id=user.id,
        key_hash=key_hash,
        name=name,
        is_active=True,
    )
    db.add(api_key)
    await db.flush()
    return api_key, plaintext


async def list_api_keys(user: User, db: AsyncSession) -> list[APIKey]:
    """Return all active API keys for the given user."""
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == user.id, APIKey.is_active == True)
        .order_by(APIKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(
    key_id: int,
    user: User,
    db: AsyncSession,
) -> bool:
    """
    Soft-delete an API key by ID.
    Returns True if found and revoked, False if not found / not owned by user.
    """
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        return False
    api_key.is_active = False
    return True


async def get_active_key_count(user: User, db: AsyncSession) -> int:
    """Return the number of active API keys for the user."""
    result = await db.execute(
        select(APIKey).where(APIKey.user_id == user.id, APIKey.is_active == True)
    )
    return len(result.scalars().all())
