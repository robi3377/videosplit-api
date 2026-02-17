from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateAPIKeyRequest(BaseModel):
    name: str = Field(max_length=100, description="A friendly label for this key")


class APIKeyResponse(BaseModel):
    """Returned when listing keys. Never exposes the plaintext key."""
    id: int
    name: str
    created_at: datetime
    last_used: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class CreateAPIKeyResponse(BaseModel):
    """Returned only at creation time — includes the plaintext key once."""
    id: int
    name: str
    key: str = Field(description="Store this now — it will not be shown again")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
