import asyncio
import logging
import os
import time

import jwt
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from .config import TELEGRAM_BOT_TOKEN, WEBAPP_URL, ensure_config

load_dotenv = __import__("dotenv").load_dotenv
load_dotenv()
AUTH_SECRET = os.getenv("AUTH_SECRET", "").strip() or os.getenv("ADMIN_SECRET", "").strip()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    """
    Simple Telegram bot that only opens the WebApp.
    Вся генерация ответов происходит в самом веб-приложении через OpenAI API.
    """
    ensure_config()

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()

    def _make_app_url() -> str:
        """Без токена — для совместимости."""
        return WEBAPP_URL.rstrip("/")

    @dp.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        user = message.from_user
        app_url = _make_app_url()
        if AUTH_SECRET and user:
            payload = {
                "telegram_id": user.id,
                "first_name": user.first_name or "",
                "username": user.username or "",
                "exp": int(time.time()) + 86400,
            }
            token = jwt.encode(payload, AUTH_SECRET, algorithm="HS256")
            if isinstance(token, bytes):
                token = token.decode()
            app_url = f"{app_url}?tg_auth={token}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📚 Открыть TestAI",
                        web_app=WebAppInfo(url=app_url),
                    )
                ]
            ]
        )
        welcome_text = (
            "Привет! 👋\n\n"
            "Это умное мини‑приложение для решения задач, тестов и примеров. "
            "Нажми кнопку ниже, чтобы загрузить текст или фото задания "
            "и получить аккуратное решение с оформленными формулами."
        )
        await message.answer(welcome_text, reply_markup=keyboard)

    @dp.message(Command("auth"))
    async def cmd_auth(message: Message) -> None:
        """Выдаёт ссылку с JWT для входа в приложение (обход initData)."""
        if not AUTH_SECRET:
            await message.answer("Ошибка: AUTH_SECRET не настроен.")
            return
        user = message.from_user
        if not user:
            await message.answer("Не удалось определить пользователя.")
            return
        payload = {
            "telegram_id": user.id,
            "first_name": user.first_name or "",
            "username": user.username or "",
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, AUTH_SECRET, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode()
        url = f"{WEBAPP_URL.rstrip('/')}/?tg_auth={token}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔐 Войти в приложение", url=url)]
            ]
        )
        await message.answer(
            "Нажми кнопку ниже, чтобы войти в приложение и привязать счётчик запросов к аккаунту.",
            reply_markup=kb,
        )

    logger.info("Starting Telegram bot polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())



