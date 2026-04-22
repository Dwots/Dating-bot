from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
import redis.asyncio as aioredis

# Лимит: не более 30 запросов за 60 секунд с одного пользователя
RATE_LIMIT = 30
RATE_WINDOW = 60  # секунд


class RateLimitMiddleware(BaseMiddleware):
    """
    Как работает:
    
    Каждый апдейт от пользователя:
      1. Берём telegram_id
      2. Делаем INCR user:{id}:requests в Redis
         INCR атомарно увеличивает счётчик на 1 и возвращает новое значение
         Если ключа не было — создаёт его со значением 1
      3. Если счётчик == 1 (первый запрос) — ставим EXPIRE 60 сек
         Через 60 сек ключ сам удалится и счётчик обнулится
      4. Если счётчик > 30 — игнорируем апдейт (не передаём дальше)
    """

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:

        # Достаём telegram_id из апдейта
        # event — это Update объект aiogram
        user_id = None
        if isinstance(event, Update):
            if event.message:
                user_id = event.message.from_user.id
            elif event.callback_query:
                user_id = event.callback_query.from_user.id

        # Если не смогли определить пользователя — пропускаем без ограничений
        if not user_id:
            return await handler(event, data)

        key = f"user:{user_id}:requests"

        # INCR — атомарная операция, возвращает новое значение счётчика
        count = await self.redis.incr(key)

        if count == 1:
            # Первый запрос в окне — ставим таймер на 60 секунд
            # После этого ключ сам исчезнет и счётчик обнулится
            await self.redis.expire(key, RATE_WINDOW)

        if count > RATE_LIMIT:
            # Превысили лимит — отвечаем пользователю и НЕ вызываем handler
            if isinstance(event, Update) and event.message:
                await event.message.answer(
                    "⚠️ Слишком много запросов. Подождите немного."
                )
            elif isinstance(event, Update) and event.callback_query:
                await event.callback_query.answer(
                    "⚠️ Слишком много запросов. Подождите немного.",
                    show_alert=True,
                )
            return  # ← выходим, handler не вызывается

        # Всё ок — передаём апдейт дальше по цепочке
        return await handler(event, data)