import json
from datetime import datetime
import aio_pika
from logger import setup_logging
from metrics import RABBITMQ_PUBLISHED

logger = setup_logging("rabbitmq")


class RabbitMQClient:
    def __init__(self, url: str):
        self.url = url
        self.connection = None
        self.channel = None
        self.exchange = None

    async def connect(self):
        self.connection = await aio_pika.connect_robust(self.url)
        self.channel = await self.connection.channel()
        self.exchange = await self.channel.declare_exchange(
            "dating_events",
            aio_pika.ExchangeType.DIRECT,
            durable=True,
        )

        for queue_name in ["like", "skip", "match"]:
            queue = await self.channel.declare_queue(queue_name, durable=True)
            await queue.bind(self.exchange, routing_key=queue_name)

        logger.info("rabbitmq_connected")

    async def publish(self, routing_key: str, data: dict):
        if not self.exchange:
            logger.warning("rabbitmq_not_connected", routing_key=routing_key)
            return

        data["timestamp"] = datetime.utcnow().isoformat()

        message = aio_pika.Message(
            body=json.dumps(data).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        )

        await self.exchange.publish(message, routing_key=routing_key)
        
        # Инкрементим метрику
        RABBITMQ_PUBLISHED.labels(routing_key=routing_key).inc()
        
        logger.info("event_published", routing_key=routing_key, data=data)

    async def close(self):
        if self.connection:
            await self.connection.close()