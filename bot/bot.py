import asyncio
import logging
from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.client.bot import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message
from app.config import settings

logging.basicConfig(level=logging.INFO)

bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
bot_router = Router()


@bot_router.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет! Открой мини‑приложение через кнопку в меню бота.")


dp.include_router(bot_router)


async def main():
    # ← подключаем роутер
    await bot.delete_webhook(drop_pending_updates=True)  # ← снимаем вебхук
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
