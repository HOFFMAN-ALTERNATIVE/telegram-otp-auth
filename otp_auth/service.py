"""Core OTP login logic. Transport-agnostic: used by the web API and the Telegram bot."""

import logging
from dataclasses import dataclass
from enum import StrEnum

from redis.asyncio import Redis

from otp_auth.codes import codes_match, digest_code, generate_code, new_token
from otp_auth.config import Settings

log = logging.getLogger("otp_auth")

# Atomic "verify-and-consume": deletes the challenge only if it is still in the expected state.
# Guarantees single use even under concurrent verification requests.
_CONSUME = """
local d = redis.call('HGET', KEYS[1], 'digest')
if d and d == ARGV[1] then
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
"""


class Outcome(StrEnum):
    OK = "ok"
    INVALID = "invalid"  # wrong code (attempts remain)
    EXPIRED = "expired"  # unknown / expired / exhausted challenge
    LOCKED = "locked"  # account temporarily locked
    RATE_LIMITED = "rate_limited"
    PENDING = "pending"  # challenge exists but no code delivered yet


@dataclass(frozen=True)
class Challenge:
    id: str
    expires_in: int


@dataclass(frozen=True)
class VerifyResult:
    outcome: Outcome
    user_id: int | None = None
    session: str | None = None
    attempts_left: int | None = None
    retry_after: int | None = None


class OTPService:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.r = redis
        self.s = settings
        self._secret = settings.secret_key.get_secret_value().encode()
        self._consume = self.r.register_script(_CONSUME)

    # ---------- keys ----------
    @staticmethod
    def _ch(cid: str) -> str:
        return f"otp:ch:{cid}"

    @staticmethod
    def _lock(uid: int) -> str:
        return f"otp:lock:{uid}"

    @staticmethod
    def _fails(uid: int) -> str:
        return f"otp:fails:{uid}"

    @staticmethod
    def _session(token: str) -> str:
        return f"otp:sess:{token}"

    async def _incr(self, key: str, window: int) -> tuple[int, int]:
        """Fixed-window counter: returns (count, seconds_until_reset)."""
        async with self.r.pipeline(transaction=True) as p:
            p.incr(key)
            p.expire(key, window, nx=True)
            p.ttl(key)
            count, _, ttl = await p.execute()
        return int(count), max(int(ttl), 1)

    async def _hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        count, ttl = await self._incr(key, window)
        return count <= limit, ttl

    # ---------- step 1: website starts a challenge ----------
    async def start(self, client_ip: str) -> Challenge | VerifyResult:
        ok, retry = await self._hit(f"otp:rl:start:{client_ip}", self.s.start_per_ip_per_minute, 60)
        if not ok:
            return VerifyResult(Outcome.RATE_LIMITED, retry_after=retry)
        cid = new_token(24)
        await self.r.hset(self._ch(cid), mapping={"state": "pending", "codes": 0, "attempts": 0})
        await self.r.expire(self._ch(cid), self.s.challenge_ttl_seconds)
        log.info("challenge.started")
        return Challenge(cid, self.s.challenge_ttl_seconds)

    # ---------- step 2: bot binds challenge to a Telegram user and issues a code ----------
    async def issue_code(self, challenge_id: str, user_id: int) -> tuple[Outcome, str | None, int]:
        """Returns (outcome, code, retry_after). The code is returned once, for delivery, never stored."""
        key = self._ch(challenge_id)
        data = await self.r.hgetall(key)
        if not data:
            return Outcome.EXPIRED, None, 0
        if (ttl := await self.r.ttl(self._lock(user_id))) > 0:
            return Outcome.LOCKED, None, ttl
        bound = data.get("user")
        if bound is not None and int(bound) != user_id:
            # a challenge can only ever belong to the first account that claimed it
            return Outcome.EXPIRED, None, 0
        if int(data.get("codes", 0)) >= self.s.max_codes_per_challenge:
            return Outcome.RATE_LIMITED, None, max(await self.r.ttl(key), 1)
        ok, retry = await self._hit(f"otp:rl:codes:{user_id}", self.s.codes_per_user_per_hour, 3600)
        if not ok:
            return Outcome.RATE_LIMITED, None, retry

        code = generate_code(self.s.code_length)
        ttl_left = await self.r.ttl(key)
        async with self.r.pipeline(transaction=True) as p:
            p.hset(
                key,
                mapping={
                    "state": "issued",
                    "user": user_id,
                    "digest": digest_code(self._secret, challenge_id, code),
                    "attempts": 0,
                },
            )
            p.hincrby(key, "codes", 1)
            # the code expires earlier than the overall challenge
            p.expire(key, min(self.s.code_ttl_seconds, max(ttl_left, 1)))
            await p.execute()
        log.info("code.issued")
        return Outcome.OK, code, 0

    # ---------- step 3: website verifies the code ----------
    async def verify(self, challenge_id: str, code: str, client_ip: str) -> VerifyResult:
        ok, retry = await self._hit(f"otp:rl:verify:{client_ip}", self.s.verify_per_ip_per_minute, 60)
        if not ok:
            return VerifyResult(Outcome.RATE_LIMITED, retry_after=retry)

        key = self._ch(challenge_id)
        data = await self.r.hgetall(key)
        if not data:
            return VerifyResult(Outcome.EXPIRED)
        if data.get("state") != "issued":
            return VerifyResult(Outcome.PENDING)
        uid = int(data["user"])
        if (ttl := await self.r.ttl(self._lock(uid))) > 0:
            return VerifyResult(Outcome.LOCKED, retry_after=ttl)

        normalized = code.strip().replace(" ", "")
        well_formed = normalized.isdigit() and len(normalized) == self.s.code_length
        if well_formed and codes_match(str(data["digest"]), self._secret, challenge_id, normalized):
            if await self._consume(keys=[key], args=[data["digest"]]) == 1:
                await self.r.delete(self._fails(uid))
                token = new_token(32)
                await self.r.set(self._session(token), uid, ex=self.s.session_ttl_seconds)
                log.info("login.success")
                return VerifyResult(Outcome.OK, user_id=uid, session=token)
            return VerifyResult(Outcome.EXPIRED)  # lost a race: already consumed

        # wrong code
        attempts = await self.r.hincrby(key, "attempts", 1)
        fail_count, _ = await self._incr(self._fails(uid), self.s.lockout_window_seconds)
        log.info("login.failed")
        if fail_count >= self.s.lockout_threshold:
            await self.r.set(self._lock(uid), 1, ex=self.s.lockout_seconds)
            await self.r.delete(key)
            log.warning("account.locked")
            return VerifyResult(Outcome.LOCKED, retry_after=self.s.lockout_seconds)
        left = self.s.max_verify_attempts - int(attempts)
        if left <= 0:
            await self.r.delete(key)  # challenge burned; user must start over
            return VerifyResult(Outcome.EXPIRED)
        return VerifyResult(Outcome.INVALID, attempts_left=left)

    # ---------- sessions ----------
    async def session_user(self, token: str | None) -> int | None:
        if not token:
            return None
        uid = await self.r.get(self._session(token))
        return int(uid) if uid is not None else None

    async def logout(self, token: str) -> None:
        await self.r.delete(self._session(token))
