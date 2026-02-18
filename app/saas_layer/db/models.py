from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from typing import Optional, List
import enum
from .base import Base

class OAuthProvider(str, enum.Enum):
    GOOGLE = "google"
    # Future: GITHUB = "github", etc.

class PlanTier(str, enum.Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"

class User(Base):
    __tablename__ = "users"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Email (unique identifier across OAuth and email login)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    
    # Email login (nullable for OAuth-only users)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Profile
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Admin flag
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Plan & Subscription
    plan_tier: Mapped[PlanTier] = mapped_column(SQLEnum(PlanTier), default=PlanTier.FREE, index=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    subscription_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # active, canceled, past_due, etc.
    subscription_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Usage limits (denormalized for performance)
    monthly_minutes_limit: Mapped[int] = mapped_column(Integer, default=100)  # Free tier default
    monthly_minutes_used: Mapped[int] = mapped_column(Integer, default=0)
    last_usage_reset: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    oauth_accounts: Mapped[List["OAuthAccount"]] = relationship("OAuthAccount", back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[List["APIKey"]] = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    usage_logs: Mapped[List["UsageLog"]] = relationship("UsageLog", back_populates="user", cascade="all, delete-orphan")
    jobs: Mapped[List["Job"]] = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User {self.email}>"

class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Link to user
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # OAuth provider details
    provider: Mapped[OAuthProvider] = mapped_column(SQLEnum(OAuthProvider), nullable=False, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Google's user ID
    
    # Tokens (encrypted in production)
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Profile data from provider
    provider_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Unique constraint: one provider account per user per provider
    __table_args__ = (
        # Unique combination of provider and provider_user_id
        # (allows same Google account to connect to only one user)
        # But allows one user to have both Google and email login
    )
    
    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="oauth_accounts")
    
    def __repr__(self):
        return f"<OAuthAccount {self.provider}:{self.provider_user_id}>"

# Placeholder models (will be fully implemented in later steps)
class APIKey(Base):
    __tablename__ = "api_keys"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    user: Mapped["User"] = relationship("User", back_populates="api_keys")

class UsageLog(Base):
    __tablename__ = "usage_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    
    # Usage details
    video_duration_seconds: Mapped[float] = mapped_column(nullable=False)
    video_size_mb: Mapped[float] = mapped_column(nullable=False)
    segments_count: Mapped[int] = mapped_column(nullable=False)
    processing_time_seconds: Mapped[float] = mapped_column(nullable=False)
    
    # Source
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # "web", "api"
    api_key_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=True)
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    user: Mapped["User"] = relationship("User", back_populates="usage_logs")

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Job details
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    segment_duration: Mapped[int] = mapped_column(Integer, nullable=False)
    segments_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_duration: Mapped[float] = mapped_column(nullable=False)

    # Crop info (optional)
    aspect_ratio: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    crop_position: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # completed, failed, expired
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    user: Mapped["User"] = relationship("User", back_populates="jobs")


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user: Mapped["User"] = relationship("User")


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user: Mapped["User"] = relationship("User")