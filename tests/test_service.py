import asyncio

from fakeredis import FakeAsyncRedis

from otp_auth.codes import token_digest
from otp_auth.service import Challenge, OTPService, Outcome
from tests.conftest import make_settings

IP = "203.0.113.7"
USER = 4242


async def started(svc: OTPService) -> str:
    ch = await svc.start(IP)
    assert isinstance(ch, Challenge)
    return ch.id


async def test_happy_path(svc: OTPService, redis: FakeAsyncRedis) -> None:
    cid = await started(svc)
    outcome, code, _ = await svc.issue_code(cid, USER)
    assert outcome is Outcome.OK
    assert code
    # code is never stored in clear
    stored = await redis.hgetall(f"otp:ch:{cid}")
    assert code not in str(stored)
    res = await svc.verify(cid, code, IP)
    assert res.outcome is Outcome.OK
    assert res.user_id == USER
    assert await svc.session_user(res.session) == USER


async def test_code_is_single_use(svc: OTPService) -> None:
    cid = await started(svc)
    _, code, _ = await svc.issue_code(cid, USER)
    assert code
    assert (await svc.verify(cid, code, IP)).outcome is Outcome.OK
    assert (await svc.verify(cid, code, IP)).outcome is Outcome.EXPIRED


async def test_concurrent_verification_only_one_wins(svc: OTPService) -> None:
    cid = await started(svc)
    _, code, _ = await svc.issue_code(cid, USER)
    assert code
    results = await asyncio.gather(*(svc.verify(cid, code, IP) for _ in range(5)))
    assert sum(r.outcome is Outcome.OK for r in results) == 1


async def test_code_accepts_spaces(svc: OTPService) -> None:
    cid = await started(svc)
    _, code, _ = await svc.issue_code(cid, USER)
    assert code
    assert (await svc.verify(cid, f"{code[:3]} {code[3:]}", IP)).outcome is Outcome.OK


async def test_verify_before_code_is_pending(svc: OTPService) -> None:
    cid = await started(svc)
    assert (await svc.verify(cid, "000000", IP)).outcome is Outcome.PENDING


async def test_unknown_challenge(svc: OTPService) -> None:
    assert (await svc.verify("nope" * 4, "123456", IP)).outcome is Outcome.EXPIRED
    assert (await svc.issue_code("nope" * 4, USER))[0] is Outcome.EXPIRED


async def test_attempts_exhaust_challenge(svc: OTPService) -> None:
    cid = await started(svc)
    _, code, _ = await svc.issue_code(cid, USER)
    assert code
    wrong = "000000" if code != "000000" else "111111"
    lefts = [(await svc.verify(cid, wrong, IP)).attempts_left for _ in range(4)]
    assert lefts == [4, 3, 2, 1]
    assert (await svc.verify(cid, wrong, IP)).outcome is Outcome.EXPIRED
    # even the right code is useless now
    assert (await svc.verify(cid, code, IP)).outcome is Outcome.EXPIRED


async def test_malformed_codes_count_as_failures(svc: OTPService) -> None:
    cid = await started(svc)
    await svc.issue_code(cid, USER)
    for bad in ("abcdef", "12345", "1234567", ""):
        assert (await svc.verify(cid, bad, IP)).outcome is Outcome.INVALID


async def test_code_expires(redis: FakeAsyncRedis) -> None:
    svc = OTPService(redis, make_settings(code_ttl_seconds=30))
    cid = await started(svc)
    _, code, _ = await svc.issue_code(cid, USER)
    assert code
    await redis.expire(f"otp:ch:{cid}", 1)  # fast-forward
    await asyncio.sleep(1.1)
    assert (await svc.verify(cid, code, IP)).outcome is Outcome.EXPIRED


async def test_challenge_cannot_be_hijacked_by_another_account(svc: OTPService) -> None:
    cid = await started(svc)
    assert (await svc.issue_code(cid, USER))[0] is Outcome.OK
    assert (await svc.issue_code(cid, 9999))[0] is Outcome.EXPIRED


async def test_resend_limit_and_new_code_invalidates_old(svc: OTPService) -> None:
    cid = await started(svc)
    _, first, _ = await svc.issue_code(cid, USER)
    _, second, _ = await svc.issue_code(cid, USER)
    assert (await svc.issue_code(cid, USER))[0] is Outcome.OK
    assert (await svc.issue_code(cid, USER))[0] is Outcome.RATE_LIMITED
    if first != second:
        assert first
        assert (await svc.verify(cid, first, IP)).outcome is Outcome.INVALID


async def test_bruteforce_lockout_across_challenges(redis: FakeAsyncRedis) -> None:
    svc = OTPService(
        redis, make_settings(lockout_threshold=6, max_verify_attempts=5, verify_per_ip_per_minute=1000)
    )
    outcomes = []
    for _ in range(2):
        cid = await started(svc)
        _, code, _ = await svc.issue_code(cid, USER)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            outcomes.append((await svc.verify(cid, wrong, IP)).outcome)
            if outcomes[-1] in (Outcome.EXPIRED, Outcome.LOCKED):
                break
    assert Outcome.LOCKED in outcomes
    cid = await started(svc)
    outcome, code, retry = await svc.issue_code(cid, USER)
    assert outcome is Outcome.LOCKED
    assert code is None
    assert retry > 0


async def test_rate_limit_start_per_ip(redis: FakeAsyncRedis) -> None:
    svc = OTPService(redis, make_settings(start_per_ip_per_minute=2))
    assert isinstance(await svc.start(IP), Challenge)
    assert isinstance(await svc.start(IP), Challenge)
    res = await svc.start(IP)
    assert not isinstance(res, Challenge)
    assert res.outcome is Outcome.RATE_LIMITED
    assert isinstance(await svc.start("198.51.100.1"), Challenge)


async def test_rate_limit_verify_per_ip(redis: FakeAsyncRedis) -> None:
    svc = OTPService(redis, make_settings(verify_per_ip_per_minute=3))
    cid = await started(svc)
    await svc.issue_code(cid, USER)
    out = [(await svc.verify(cid, "000000", IP)).outcome for _ in range(4)]
    assert out[-1] is Outcome.RATE_LIMITED


async def test_rate_limit_codes_per_user(redis: FakeAsyncRedis) -> None:
    svc = OTPService(redis, make_settings(codes_per_user_per_hour=2))
    res = []
    for _ in range(3):
        cid = await started(svc)
        res.append((await svc.issue_code(cid, USER))[0])
    assert res == [Outcome.OK, Outcome.OK, Outcome.RATE_LIMITED]


async def test_logout(svc: OTPService) -> None:
    cid = await started(svc)
    _, code, _ = await svc.issue_code(cid, USER)
    assert code
    token = (await svc.verify(cid, code, IP)).session
    assert token
    await svc.logout(token)
    assert await svc.session_user(token) is None


async def test_session_token_is_stored_only_as_digest(svc: OTPService, redis: FakeAsyncRedis) -> None:
    cid = await started(svc)
    _, code, _ = await svc.issue_code(cid, USER)
    assert code
    token = (await svc.verify(cid, code, IP)).session
    assert token
    keys = [k.decode() if isinstance(k, bytes) else k async for k in redis.scan_iter("otp:sess:*")]
    assert keys == [f"otp:sess:{token_digest(token)}"]
    assert all(token not in k for k in keys)
    # a leaked key from a Redis dump is not a usable cookie
    assert await svc.session_user(token_digest(token)) is None
    assert await svc.session_user(token) == USER
