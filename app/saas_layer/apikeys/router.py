from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.apikeys import service as apikey_service
from app.saas_layer.apikeys.schemas import (
    APIKeyResponse,
    CreateAPIKeyRequest,
    CreateAPIKeyResponse,
)
from app.saas_layer.auth.dependencies import get_current_active_user, get_current_user_jwt_only
from app.saas_layer.db.base import get_db
from app.saas_layer.db.models import User

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=CreateAPIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: CreateAPIKeyRequest,
    current_user: User = Depends(get_current_user_jwt_only),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new API key. Requires JWT authentication.
    The key plaintext is returned ONCE — store it securely.
    """
    api_key, plaintext = await apikey_service.create_api_key(
        user=current_user,
        name=body.name,
        db=db,
    )
    return CreateAPIKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key=plaintext,
        created_at=api_key.created_at,
    )


@router.get("", response_model=list[APIKeyResponse])
async def list_keys(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active API keys for the current user."""
    keys = await apikey_service.list_api_keys(user=current_user, db=db)
    return keys


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: int,
    current_user: User = Depends(get_current_user_jwt_only),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key by ID. Requires JWT authentication."""
    revoked = await apikey_service.revoke_api_key(
        key_id=key_id,
        user=current_user,
        db=db,
    )
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
