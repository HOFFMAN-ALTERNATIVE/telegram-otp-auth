import asyncio
import logging

from aiogram import Bot, Dispatcher
from redis.asyncio import Redis

from otp_auth.bot.handlers import router
from otp_auth.config import get_settings
from otp_auth.service import OTPService


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    if s.bot_token is None:
        raise SystemExit("BOT_TOKEN is required")
    redis = Redis.from_url(s.redis_url, decode_responses=True)
    bot = Bot(s.bot_token.get_secret_value())
    dp = Dispatcher(otp=OTPService(redis, s))
    dp.include_router(router)
    try:
        await dp.start_polling(bot, allowed_updates=["message"])
    finally:
        await redis.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
