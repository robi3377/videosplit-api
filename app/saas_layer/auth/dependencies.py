import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.core.security import decode_token, hash_api_key
from app.saas_layer.db.base import get_db
from app.saas_layer.db.models import APIKey, User

logger = logging.getLogger(__name__)


async def _validate_jwt(token: str, db: AsyncSession) -> User:
    """Validate a JWT Bearer token and return the associated User."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        if not user_id or token_type != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


async def _validate_api_key(key: str, db: AsyncSession) -> User:
    """Validate an API key and return the associated User. Updates last_used."""
    key_hash = hash_api_key(key)

    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )

    # Update last_used timestamp
    api_key.last_used = datetime.now(timezone.utc)

    result2 = await db.execute(select(User).where(User.id == api_key.user_id))
    user = result2.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key owner not found",
        )
    return user


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Extract and validate auth from the Authorization header.
    Accepts:
    - API key:  Authorization: vs_live_<key>
    - JWT:      Authorization: Bearer <token>
    Raises 401 if missing or invalid.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if authorization.startswith("vs_live_"):
        return await _validate_api_key(authorization, db)

    # Strip "Bearer " prefix if present
    token = authorization.removeprefix("Bearer ").strip()
    return await _validate_jwt(token, db)


async def get_current_user_jwt_only(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Same as get_current_user but only accepts JWT (not API keys).
    Used for sensitive account-management endpoints.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if authorization.startswith("vs_live_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key not allowed for this endpoint; use a JWT token",
        )

    token = authorization.removeprefix("Bearer ").strip()
    return await _validate_jwt(token, db)


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Raises 403 if the user account has been deactivated."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Raises 403 if the user is not an admin."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_optional_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Returns the authenticated user if a valid Authorization header is present,
    otherwise returns None (for endpoints that work both authenticated and not).
    """
    if not authorization:
        return None
    try:
        return await get_current_user(authorization, db)
    except HTTPException:
        return None
