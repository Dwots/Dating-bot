import asyncio
import json
import logging
import os
import aio_pika
from tasks import notify_match, process_like, process_skip

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")


async def main():
    logger.info("Starting consumer...")

    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()

    # Слушаем все три очереди одновременно
    match_queue = await channel.declare_queue("match", durable=True)
    like_queue  = await channel.declare_queue("like",  durable=True)
    skip_queue  = await channel.declare_queue("skip",  durable=True)

    async def on_match(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                data = json.loads(message.body.decode())
                logger.info(f"Match event: {data}")
                notify_match.delay(
                    user1_telegram_id=data["user1_telegram_id"],
                    user2_telegram_id=data["user2_telegram_id"],
                    user1_name=data.get("user1_name", "Пользователь"),
                )
            except Exception as e:
                logger.error(f"Error processing match: {e}")

    async def on_like(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                data = json.loads(message.body.decode())
                logger.info(f"Like event: {data}")
                process_like.delay(
                    from_user_id=data["from_user_id"],
                    to_user_id=data["to_user_id"],
                )
            except Exception as e:
                logger.error(f"Error processing like: {e}")

    async def on_skip(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                data = json.loads(message.body.decode())
                logger.info(f"Skip event: {data}")
                process_skip.delay(
                    from_user_id=data["from_user_id"],
                    to_user_id=data["to_user_id"],
                )
            except Exception as e:
                logger.error(f"Error processing skip: {e}")

    # Подписываемся на все очереди
    await match_queue.consume(on_match)
    await like_queue.consume(on_like)
    await skip_queue.consume(on_skip)

    logger.info("Waiting for events (match, like, skip)...")

    # Держим consumer живым
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())