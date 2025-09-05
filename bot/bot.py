import asyncio
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from app.config import settings
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode

bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


from aiogram import Router
from aiogram.types import Message

router = Router()

@router.message(CommandStart())
async def start(message: Message):
    # Никаких клавиатур — просто текст
    await message.answer("Привет! Открой мини‑приложение через кнопку в меню бота.")



def main():
    asyncio.run(dp.start_polling(bot))


if __name__ == "__main__":
    main()
