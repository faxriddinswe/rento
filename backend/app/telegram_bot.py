"""Telegram bot process (long polling): links a chat to an account via /start <signed-token>.

Run: python -m app.telegram_bot   (needs TELEGRAM_BOT_TOKEN, see docs/BLOCKERS.md)"""

import asyncio

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker
from app.errors import AppError
from app.logging import configure_logging, get_logger
from app.services.telegram import link_chat

router = Router()


@router.message(CommandStart())
async def on_start(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(
            "Salom! Hisobingizni ulash uchun Rento ilovasidagi «Telegramni ulash» tugmasidan foydalaning."
        )
        return
    try:
        async with get_sessionmaker()() as session:
            user = await link_chat(session, command.args, message.chat.id)
            await session.commit()
            name = user.full_name
    except AppError as exc:
        await message.answer(f"Ulab bo'lmadi: {exc.message}")
        return
    await message.answer(f"✅ {name}, Telegram hisobingiz Rento'ga ulandi.")


async def main() -> None:
    configure_logging()
    token = get_settings().telegram_bot_token
    if not token:
        get_logger().error("TELEGRAM_BOT_TOKEN is empty; bot not started (see docs/BLOCKERS.md)")
        return
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
