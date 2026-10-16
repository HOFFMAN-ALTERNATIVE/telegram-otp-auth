from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from otp_auth.config import Settings, get_settings
from otp_auth.service import Challenge, OTPService, Outcome

STATIC = Path(__file__).parent / "static"
COOKIE = "session"


class StartResponse(BaseModel):
    challenge_id: str
    deep_link: str
    expires_in: int


class VerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=10, max_length=64)
    code: str = Field(min_length=4, max_length=16)


def client_ip(request: Request, settings: Settings) -> str:
    """Honour X-Forwarded-For only for the configured number of trusted proxy hops."""
    if settings.trusted_proxy_count > 0:
        chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(chain) >= settings.trusted_proxy_count:
            return chain[-settings.trusted_proxy_count]
    return request.client.host if request.client else "unknown"


def create_app(settings: Settings | None = None, redis: Redis | None = None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        r = redis or Redis.from_url(s.redis_url, decode_responses=True)
        app.state.otp = OTPService(r, s)
        yield
        if redis is None:
            await r.aclose()

    app = FastAPI(title="Telegram OTP login", version="1.0.0", lifespan=lifespan)

    def otp(request: Request) -> OTPService:
        svc: OTPService = request.app.state.otp
        return svc

    Svc = Annotated[OTPService, Depends(otp)]

    def too_many(retry: int | None) -> HTTPException:
        return HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests",
            headers={"Retry-After": str(retry or 60)},
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        resp: Response = await call_next(request)
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/auth/telegram/start", response_model=StartResponse)
    async def start(request: Request, svc: Svc) -> StartResponse:
        res = await svc.start(client_ip(request, s))
        if not isinstance(res, Challenge):
            raise too_many(res.retry_after)
        return StartResponse(
            challenge_id=res.id,
            deep_link=f"https://t.me/{s.bot_username}?start={res.id}",
            expires_in=res.expires_in,
        )

    @app.post("/auth/telegram/verify")
    async def verify(
        body: VerifyRequest, request: Request, response: Response, svc: Svc
    ) -> dict[str, object]:
        res = await svc.verify(body.challenge_id, body.code, client_ip(request, s))
        match res.outcome:
            case Outcome.OK:
                assert res.session
                response.set_cookie(
                    COOKIE,
                    res.session,
                    max_age=s.session_ttl_seconds,
                    httponly=True,
                    secure=s.cookie_secure,
                    samesite="strict",
                )
                return {"status": "ok"}
            case Outcome.INVALID:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    {"error": "invalid_code", "attempts_left": res.attempts_left},
                )
            case Outcome.PENDING:
                raise HTTPException(status.HTTP_409_CONFLICT, {"error": "code_not_sent_yet"})
            case Outcome.LOCKED:
                raise HTTPException(
                    status.HTTP_423_LOCKED,
                    {"error": "locked"},
                    headers={"Retry-After": str(res.retry_after or 60)},
                )
            case Outcome.RATE_LIMITED:
                raise too_many(res.retry_after)
            case _:
                raise HTTPException(status.HTTP_410_GONE, {"error": "expired"})

    @app.get("/auth/me")
    async def me(svc: Svc, session: Annotated[str | None, Cookie(alias=COOKIE)] = None) -> dict[str, int]:
        uid = await svc.session_user(session)
        if uid is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
        return {"telegram_user_id": uid}

    @app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        response: Response, svc: Svc, session: Annotated[str | None, Cookie(alias=COOKIE)] = None
    ) -> None:
        if session:
            await svc.logout(session)
        response.delete_cookie(COOKIE)

    @app.get("/healthz")
    async def healthz(svc: Svc) -> dict[str, str]:
        await svc.r.ping()
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app
