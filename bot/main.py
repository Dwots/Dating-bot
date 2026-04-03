import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from config import load_config
from database import Database
from handlers import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    config = load_config()
    
    if not config.bot_token:
        logger.error("BOT_TOKEN not set!")
        return
    
    db = Database(config.database_url)
    await db.create_tables()
    logger.info("Database tables created")
    
    bot = Bot(token=config.bot_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    dp.include_router(router)
    
    @dp.update.middleware()
    async def db_middleware(handler, event, data):
        async with db.session_factory() as session:
            data["session"] = session
            return await handler(event, data)
    
    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
