from collections.abc import AsyncIterator

import pytest
from fakeredis import FakeAsyncRedis

from otp_auth.config import Settings
from otp_auth.service import OTPService

SECRET = "x" * 48


def make_settings(**kw: object) -> Settings:
    base: dict[str, object] = {"secret_key": SECRET, "cookie_secure": False, "bot_username": "demo_bot"}
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    r = FakeAsyncRedis(decode_responses=True)
    yield r
    await r.flushall()
    await r.aclose()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def svc(redis: FakeAsyncRedis, settings: Settings) -> OTPService:
    return OTPService(redis, settings)
