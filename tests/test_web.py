from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fakeredis import FakeAsyncRedis

from otp_auth.config import Settings
from otp_auth.web.app import client_ip, create_app
from tests.conftest import make_settings


@pytest.fixture
async def ctx(redis: FakeAsyncRedis) -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    app = create_app(make_settings(), redis=redis)
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c, app


async def test_full_login_flow(ctx: tuple[httpx.AsyncClient, object]) -> None:
    c, app = ctx
    r = await c.post("/auth/telegram/start")
    assert r.status_code == 200
    data = r.json()
    assert data["deep_link"] == f"https://t.me/demo_bot?start={data['challenge_id']}"

    # what the bot does when the user presses Start
    _, code, _ = await app.state.otp.issue_code(data["challenge_id"], 777)  # type: ignore[attr-defined]

    bad = await c.post(
        "/auth/telegram/verify",
        json={"challenge_id": data["challenge_id"], "code": "999999" if code != "999999" else "000000"},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["attempts_left"] == 4

    ok = await c.post("/auth/telegram/verify", json={"challenge_id": data["challenge_id"], "code": code})
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie

    assert (await c.get("/auth/me")).json() == {"telegram_user_id": 777}
    assert (await c.post("/auth/logout")).status_code == 204
    assert (await c.get("/auth/me")).status_code == 401


async def test_status_codes(ctx: tuple[httpx.AsyncClient, object]) -> None:
    c, _ = ctx
    cid = (await c.post("/auth/telegram/start")).json()["challenge_id"]
    r = await c.post("/auth/telegram/verify", json={"challenge_id": cid, "code": "123456"})
    assert r.status_code == 409
    r = await c.post("/auth/telegram/verify", json={"challenge_id": "x" * 20, "code": "123456"})
    assert r.status_code == 410


async def test_security_headers_and_demo_page(ctx: tuple[httpx.AsyncClient, object]) -> None:
    c, _ = ctx
    r = await c.get("/")
    assert r.status_code == 200
    assert "Log in with Telegram" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert (await c.get("/healthz")).json() == {"status": "ok"}


async def test_start_rate_limited(redis: FakeAsyncRedis) -> None:
    app = create_app(make_settings(start_per_ip_per_minute=1), redis=redis)
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        assert (await c.post("/auth/telegram/start")).status_code == 200
        r = await c.post("/auth/telegram/start")
        assert r.status_code == 429
        assert "retry-after" in r.headers


class _Req:
    def __init__(self, xff: str, host: str = "10.0.0.2") -> None:
        self.headers = {"x-forwarded-for": xff}
        self.client = type("C", (), {"host": host})()


def test_client_ip_ignores_spoofed_xff_by_default() -> None:
    s: Settings = make_settings()
    assert client_ip(_Req("1.2.3.4"), s) == "10.0.0.2"  # type: ignore[arg-type]


def test_client_ip_trusts_configured_hops() -> None:
    s = make_settings(trusted_proxy_count=1)
    assert client_ip(_Req("6.6.6.6, 1.2.3.4"), s) == "1.2.3.4"  # type: ignore[arg-type]
