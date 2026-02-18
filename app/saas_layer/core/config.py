import os
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://videosplit:password@localhost:5432/videosplit"
    )

    # JWT
    JWT_SECRET_KEY: str = Field(default="change-me-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Google OAuth (leave blank locally — routes return 503 if blank)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_KEY_PREFIX: str = "videosplit"

    # Stripe (leave STRIPE_WEBHOOK_SECRET blank locally)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_PRICE_ID_STARTER: str = ""
    STRIPE_PRICE_ID_PRO: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # App
    APP_BASE_URL: str = "http://localhost:8000"

    # Email / SMTP (leave blank to disable email sending)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = "noreply@videosplit.com"
    ALERT_EMAIL: str = ""  # Admin alert recipient

    # Plan minute limits (-1 = unlimited stored as 999999 in DB)
    PLAN_LIMITS: dict = {
        "free": 100,
        "starter": 1000,
        "pro": 999999,
        "enterprise": 999999,
    }

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def google_oauth_enabled(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.STRIPE_SECRET_KEY)

    @property
    def stripe_webhooks_enabled(self) -> bool:
        return bool(self.STRIPE_WEBHOOK_SECRET)

    @property
    def email_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_USER and self.SMTP_PASSWORD)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
