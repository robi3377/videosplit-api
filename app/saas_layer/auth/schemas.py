from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, ConfigDict


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="Minimum 8 characters")
    full_name: Optional[str] = Field(default=None, max_length=255)


class RegistrationPendingResponse(BaseModel):
    status: str = "verify_required"
    email: str
    message: str = "Check your email for a 6-digit verification code"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class RefreshRequest(BaseModel):
    refresh_token: str


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    avatar_url: Optional[str]
    plan_tier: str
    is_admin: bool
    is_active: bool
    email_verified: bool
    monthly_minutes_limit: int
    monthly_minutes_used: int
    subscription_status: Optional[str]
    created_at: datetime
    last_login: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
