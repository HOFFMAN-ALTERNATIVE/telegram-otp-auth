from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All security parameters are explicit and tunable."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: SecretStr = Field(min_length=32)  # HMAC key for code digests
    redis_url: str = "redis://localhost:6379/0"

    bot_token: SecretStr | None = None
    bot_username: str = "your_login_bot"

    code_length: int = Field(default=6, ge=6, le=10)
    challenge_ttl_seconds: int = Field(default=300, ge=30)  # whole login window
    code_ttl_seconds: int = Field(default=120, ge=30)  # validity of a delivered code
    max_verify_attempts: int = Field(default=5, ge=1)  # wrong codes per challenge
    max_codes_per_challenge: int = Field(default=3, ge=1)  # re-sends per challenge

    # Brute-force lockout per Telegram account
    lockout_threshold: int = Field(default=10, ge=1)  # failed attempts in window
    lockout_window_seconds: int = 3600
    lockout_seconds: int = 900

    # Rate limits (fixed window)
    start_per_ip_per_minute: int = 10
    verify_per_ip_per_minute: int = 20
    codes_per_user_per_hour: int = 10

    session_ttl_seconds: int = 7 * 24 * 3600
    cookie_secure: bool = True
    trusted_proxy_count: int = 0  # how many X-Forwarded-For hops to trust


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
