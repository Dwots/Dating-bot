import asyncio
import redis.asyncio as aioredis
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_config
from database import Database
from handlers import router
from middleware import RateLimitMiddleware
from minio_client import MinioClient
from rabbitmq import RabbitMQClient
from surreal import SurrealClient
from logger import setup_logging
from metrics import start_metrics_server

logger = setup_logging("bot")


async def main():
    config = load_config()

    if not config.bot_token:
        logger.error("bot_token_missing")
        return

    # Просто вызываем функцию — она сама запускает поток
    start_metrics_server(port=8001)

    db = Database(config.database_url)
    await db.create_tables()
    logger.info("database_initialized")

    redis_client = aioredis.from_url(config.redis_url, decode_responses=True)
    await redis_client.ping()
    logger.info("redis_connected")

    minio = MinioClient(
        endpoint=config.minio_endpoint,
        access_key=config.minio_access_key,
        secret_key=config.minio_secret_key,
        bucket=config.minio_bucket,
    )
    logger.info("minio_connected")

    rabbitmq = RabbitMQClient(config.rabbitmq_url)
    await rabbitmq.connect()

    surreal = SurrealClient(
        url=config.surreal_url,
        username=config.surreal_user,
        password=config.surreal_pass,
    )
    await surreal.connect()

    bot = Bot(token=config.bot_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.include_router(router)

    @dp.update.middleware()
    async def db_middleware(handler, event, data):
        async with db.session_factory() as session:
            data["session"] = session
            return await handler(event, data)

    @dp.update.middleware()
    async def minio_middleware(handler, event, data):
        data["minio"] = minio
        return await handler(event, data)

    @dp.update.middleware()
    async def rabbitmq_middleware(handler, event, data):
        data["rabbitmq"] = rabbitmq
        return await handler(event, data)

    @dp.update.middleware()
    async def redis_middleware(handler, event, data):
        data["redis"] = redis_client
        return await handler(event, data)

    @dp.update.middleware()
    async def surreal_middleware(handler, event, data):
        data["surreal"] = surreal
        return await handler(event, data)

    dp.update.middleware(RateLimitMiddleware(redis_client))

    logger.info("bot_starting")
    try:
        await dp.start_polling(bot)
    finally:
        await rabbitmq.close()
        await surreal.close()


if __name__ == "__main__":
    asyncio.run(main())