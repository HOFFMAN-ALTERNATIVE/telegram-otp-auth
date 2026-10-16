from types import SimpleNamespace
from typing import Any

from otp_auth.bot.handlers import render_code, start_with_challenge
from otp_auth.service import Challenge, OTPService


class FakeMessage:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.sent: list[str] = []

    async def answer(self, text: str, **_: Any) -> None:
        self.sent.append(text)


async def test_bot_delivers_code_that_verifies(svc: OTPService) -> None:
    ch = await svc.start("203.0.113.1")
    assert isinstance(ch, Challenge)
    msg = FakeMessage(55)
    await start_with_challenge(msg, SimpleNamespace(args=ch.id), svc)
    assert "Your login code" in msg.sent[0]
    code = msg.sent[0].split("<code>")[1].split("</code>")[0].replace(" ", "")
    res = await svc.verify(ch.id, code, "203.0.113.1")
    assert res.user_id == 55


async def test_bot_expired_link(svc: OTPService) -> None:
    msg = FakeMessage(1)
    await start_with_challenge(msg, SimpleNamespace(args="does-not-exist-123"), svc)
    assert "expired" in msg.sent[0]


def test_render_groups_digits() -> None:
    assert "<code>123 456</code>" in render_code("123456", 120)
