import logging

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from otp_auth.service import OTPService, Outcome

router = Router(name="otp")
log = logging.getLogger("otp_auth.bot")

MESSAGES = {
    Outcome.EXPIRED: "This login link has expired. Please start again on the website.",
    Outcome.LOCKED: "Too many failed attempts. Try again in {mins} min.",
    Outcome.RATE_LIMITED: "Too many codes requested. Try again in {mins} min.",
}


def render_code(code: str, ttl: int) -> str:
    spaced = " ".join(code[i : i + 3] for i in range(0, len(code), 3))
    return (
        f"🔐 Your login code: <code>{spaced}</code>\n\n"
        f"Valid for {ttl // 60} min. Never share it — we will never ask you for it."
    )


@router.message(CommandStart(deep_link=True))
async def start_with_challenge(message: Message, command: CommandObject, otp: OTPService) -> None:
    if message.from_user is None or not command.args:
        return
    outcome, code, retry = await otp.issue_code(command.args, message.from_user.id)
    if outcome is Outcome.OK and code:
        await message.answer(render_code(code, otp.s.code_ttl_seconds), parse_mode="HTML")
        return
    text = MESSAGES.get(outcome, MESSAGES[Outcome.EXPIRED])
    await message.answer(text.format(mins=max(1, retry // 60)))


@router.message(CommandStart())
async def plain_start(message: Message) -> None:
    await message.answer("👋 Use the “Log in with Telegram” button on the website to receive a code.")
