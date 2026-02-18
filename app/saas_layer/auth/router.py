import logging
import os
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.auth import service as auth_service
from app.saas_layer.auth.dependencies import (
    get_current_active_user,
    get_current_user_jwt_only,
)
from app.saas_layer.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegistrationPendingResponse,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.saas_layer.core.config import settings
from app.saas_layer.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
    hash_password,
)
from app.saas_layer.db.base import get_db
from app.saas_layer.db.models import EmailVerification, PasswordReset, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _build_token_response(user: User) -> TokenResponse:
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# Email / Password
# ---------------------------------------------------------------------------

@router.post("/register", response_model=RegistrationPendingResponse, status_code=status.HTTP_202_ACCEPTED)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new account. Email verification is required before the account is usable."""
    try:
        user = await auth_service.register_user(
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    # Send verification code immediately
    now = datetime.now(timezone.utc)
    code = f"{random.randint(0, 999999):06d}"
    ev = EmailVerification(
        user_id=user.id,
        code=code,
        expires_at=now + timedelta(minutes=15),
        verified=False,
    )
    db.add(ev)

    from app.services.email_service import send_verification_email
    await send_verification_email(user.email, code)

    return RegistrationPendingResponse(email=user.email)


class CompleteRegistrationRequest(BaseModel):
    email: str
    code: str


@router.post("/complete-registration", response_model=TokenResponse)
async def complete_registration(
    body: CompleteRegistrationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit the 6-digit code sent after registration to activate the account and get tokens."""
    user = await auth_service.get_user_by_email(body.email.lower().strip(), db)
    if not user or user.email_verified:
        raise HTTPException(status_code=400, detail="Invalid email or already verified")

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.verified == False,  # noqa: E712
            EmailVerification.expires_at > now,
        ).order_by(EmailVerification.created_at.desc()).limit(1)
    )
    verification = result.scalar_one_or_none()

    if not verification or verification.code != body.code.strip():
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    verification.verified = True
    user.email_verified = True
    return _build_token_response(user)


class ResendRegistrationCodeRequest(BaseModel):
    email: str


@router.post("/resend-registration-code", status_code=status.HTTP_200_OK)
async def resend_registration_code(
    body: ResendRegistrationCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resend verification code for unverified accounts (no auth required). Rate-limited to 1/min."""
    user = await auth_service.get_user_by_email(body.email.lower().strip(), db)
    if not user or user.email_verified:
        # Return success to avoid user enumeration
        return {"message": "If that email exists and is unverified, a code has been sent"}

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.created_at > now - timedelta(minutes=1),
        ).limit(1)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=429, detail="Please wait 1 minute before requesting another code")

    code = f"{random.randint(0, 999999):06d}"
    ev = EmailVerification(
        user_id=user.id,
        code=code,
        expires_at=now + timedelta(minutes=15),
        verified=False,
    )
    db.add(ev)

    from app.services.email_service import send_verification_email
    await send_verification_email(user.email, code)

    return {"message": "Verification code sent"}


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Log in with email and password."""
    user = await auth_service.authenticate_user(
        email=body.email,
        password=body.password,
        db=db,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )
    return _build_token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a refresh token for a new access token."""
    from jose import JWTError

    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=400, detail="Invalid token type")
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = await auth_service.get_user_by_id(user_id, db)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    # Issue a new access token; keep the same refresh token
    access_token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=access_token,
        refresh_token=body.refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_active_user)):
    """Return the current user's profile."""
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_me(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's profile (full_name)."""
    if body.full_name is not None:
        current_user.full_name = body.full_name
    return current_user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user_jwt_only),
    db: AsyncSession = Depends(get_db),
):
    """Change password. Requires JWT authentication (not API key)."""
    if not current_user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account uses OAuth login; no password to change",
        )
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.hashed_password = hash_password(body.new_password)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    current_user: User = Depends(get_current_user_jwt_only),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete the current account and all associated data."""
    await db.delete(current_user)


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

@router.get("/google/login")
async def google_login():
    """Redirect the browser to Google's authorization page."""
    if not settings.google_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server",
        )

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url=f"{GOOGLE_AUTHORIZE_URL}?{query_string}")


@router.get("/google/callback")
async def google_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback. Issues JWT and redirects to frontend."""
    if not settings.google_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server",
        )

    if error or not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google OAuth error: {error or 'no code received'}",
        )

    async with httpx.AsyncClient() as client:
        # Exchange authorization code for tokens
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code with Google",
            )
        token_data = token_response.json()
        google_access_token = token_data.get("access_token")

        # Fetch user info from Google
        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_access_token}"},
        )
        if userinfo_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to fetch user info from Google",
            )
        userinfo = userinfo_response.json()

    provider_user_id = userinfo.get("sub")
    email = userinfo.get("email")
    full_name = userinfo.get("name")
    avatar_url = userinfo.get("picture")

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account does not have an email address",
        )

    user = await auth_service.get_or_create_oauth_user(
        provider="google",
        provider_user_id=provider_user_id,
        email=email,
        full_name=full_name,
        avatar_url=avatar_url,
        access_token=google_access_token,
        db=db,
    )

    token_resp = _build_token_response(user)
    redirect_url = (
        f"{settings.APP_BASE_URL}/static/index.html"
        f"?access_token={token_resp.access_token}"
        f"&refresh_token={token_resp.refresh_token}"
    )
    return RedirectResponse(url=redirect_url)


# ---------------------------------------------------------------------------
# Email Verification
# ---------------------------------------------------------------------------

class VerifyEmailRequest(BaseModel):
    code: str


class ResendVerificationRequest(BaseModel):
    pass  # uses current auth token


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(
    body: VerifyEmailRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a 6-digit verification code to verify the user's email."""
    if current_user.email_verified:
        return {"message": "Email already verified"}

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(EmailVerification).where(
            EmailVerification.user_id == current_user.id,
            EmailVerification.verified == False,  # noqa: E712
            EmailVerification.expires_at > now,
        ).order_by(EmailVerification.created_at.desc()).limit(1)
    )
    verification = result.scalar_one_or_none()

    if not verification or verification.code != body.code.strip():
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    verification.verified = True
    current_user.email_verified = True
    return {"message": "Email verified successfully"}


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
async def resend_verification(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a new verification code. Rate-limited to once per minute."""
    if current_user.email_verified:
        return {"message": "Email already verified"}

    now = datetime.now(timezone.utc)
    # Rate limit: one resend per minute
    result = await db.execute(
        select(EmailVerification).where(
            EmailVerification.user_id == current_user.id,
            EmailVerification.created_at > now - timedelta(minutes=1),
        ).limit(1)
    )
    recent = result.scalar_one_or_none()
    if recent:
        raise HTTPException(status_code=429, detail="Please wait 1 minute before requesting another code")

    code = f"{random.randint(0, 999999):06d}"
    ev = EmailVerification(
        user_id=current_user.id,
        code=code,
        expires_at=now + timedelta(minutes=15),
        verified=False,
    )
    db.add(ev)

    from app.services.email_service import send_verification_email
    await send_verification_email(current_user.email, code)

    return {"message": "Verification code sent"}


# ---------------------------------------------------------------------------
# Password Reset
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset link. Always returns 200 to avoid email enumeration."""
    # Rate limit check (3 per hour per email) — using DB count
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(PasswordReset).where(
            PasswordReset.email == body.email.lower().strip(),
            PasswordReset.created_at > now - timedelta(hours=1),
        )
    )
    recent_count = len(result.scalars().all())
    if recent_count >= 3:
        # Silently return success to avoid timing attacks
        return {"message": "If that email exists, a reset link has been sent"}

    user = await auth_service.get_user_by_email(body.email.lower().strip(), db)
    if user and user.hashed_password:  # Only email/password accounts can reset
        token = secrets.token_urlsafe(32)
        token_hash = hash_password(token)  # reuse bcrypt hasher
        reset = PasswordReset(
            user_id=user.id,
            email=user.email,
            token_hash=token_hash,
            expires_at=now + timedelta(hours=1),
            used=False,
        )
        db.add(reset)
        reset_url = f"{settings.APP_BASE_URL}/static/reset-password.html?token={token}"
        from app.services.email_service import send_password_reset_email
        await send_password_reset_email(user.email, reset_url)

    return {"message": "If that email exists, a reset link has been sent"}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit a reset token + new password to update the account password."""
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    now = datetime.now(timezone.utc)
    # Find matching, unexpired, unused reset records for the token
    result = await db.execute(
        select(PasswordReset).where(
            PasswordReset.expires_at > now,
            PasswordReset.used == False,  # noqa: E712
        )
    )
    resets = result.scalars().all()

    matched = None
    for r in resets:
        if verify_password(body.token, r.token_hash):
            matched = r
            break

    if not matched:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user_result = await db.execute(select(User).where(User.id == matched.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")

    user.hashed_password = hash_password(body.new_password)
    matched.used = True

    from app.services.email_service import send_password_changed_email
    await send_password_changed_email(user.email)

    return {"message": "Password reset successfully"}
