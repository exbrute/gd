import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo

from .config import TELEGRAM_BOT_TOKEN, WEBAPP_URL, ensure_config


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

    @dp.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(
                        text="Открыть мини‑приложение",
                        web_app=WebAppInfo(url=WEBAPP_URL),
                    )
                ]
            ],
            resize_keyboard=True,
        )

        welcome_text = (
            "Привет! 👋\n\n"
            "Это умное мини‑приложение для решения задач, тестов и примеров. "
            "Нажми кнопку «Открыть мини‑приложение», чтобы загрузить текст или фото задания "
            "и получить аккуратное решение с оформленными формулами."
        )

        await message.answer(welcome_text, reply_markup=keyboard)

    logger.info("Starting Telegram bot polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())



