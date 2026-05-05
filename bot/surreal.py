from surrealdb import Surreal
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class SurrealClient:
    """
    Клиент для работы с SurrealDB как графовой БД.
    
    Структура графа:
      Узлы (nodes):  user:{telegram_id}
      Рёбра (edges): liked, skipped, viewed
    
    Пример:
      user:123 -[liked]-> user:456   (timestamp)
      user:123 -[viewed]-> user:789  (timestamp)
    
    SurrealDB умеет эффективно обходить такие связи через оператор ->
    """

    def __init__(self, url: str, username: str, password: str):
        self.url = url
        self.username = username
        self.password = password
        self.db = None

    async def connect(self):
        """
        Подключаемся к SurrealDB и выбираем namespace + database
        
        namespace — это как схема в PostgreSQL
        database  — база внутри namespace
        """
        self.db = Surreal(self.url)
        await self.db.connect()
        await self.db.signin({"user": self.username, "pass": self.password})
        await self.db.use("dating", "interactions")
        logger.info("SurrealDB connected")

    async def close(self):
        if self.db:
            await self.db.close()

    async def add_interaction(
        self,
        from_user_id: int,
        to_user_id: int,
        action: str,  # "like" / "skip" / "view"
    ):
        """
        Создаём ребро графа:
          user:{from_id} -[{action}]-> user:{to_id}
        
        RELATE — оператор SurrealDB для создания связей в графе
        
        Если связь уже есть — обновляем timestamp
        """
        query = f"""
        RELATE user:{from_user_id}->{action}->user:{to_user_id}
        SET timestamp = time::now()
        """
        await self.db.query(query)
        logger.debug(f"Graph edge created: {from_user_id} -{action}-> {to_user_id}")

    async def get_interacted_users(self, user_id: int) -> set[int]:
        """
        Возвращает все user_id с которыми пользователь взаимодействовал
        (просмотрел, лайкнул, пропустил)
        
        -> — оператор обхода графа в SurrealDB
        ->liked->user   означает "пройди по рёбрам liked и достань целевые узлы user"
        ->viewed->user  аналогично
        ->skipped->user аналогично
        """
        query = f"""
        SELECT 
            ->liked->user AS liked,
            ->viewed->user AS viewed,
            ->skipped->user AS skipped
        FROM user:{user_id}
        """
        result = await self.db.query(query)

        # Результат SurrealDB: [{"result": [{"liked": [...], "viewed": [...], "skipped": [...]}]}]
        interacted = set()

        if result and len(result) > 0 and "result" in result[0]:
            data = result[0]["result"]
            if len(data) > 0:
                for key in ["liked", "viewed", "skipped"]:
                    if key in data[0] and data[0][key]:
                        for user in data[0][key]:
                            # user выглядит как "user:123"
                            # извлекаем id
                            if isinstance(user, str) and user.startswith("user:"):
                                uid = int(user.split(":")[1])
                                interacted.add(uid)

        return interacted

    async def check_mutual_like(self, user1_id: int, user2_id: int) -> bool:
        """
        Проверяем взаимный лайк через граф:
        есть ли ребро user:{user2_id} -[liked]-> user:{user1_id} ?
        
        Быстрее чем SELECT в PostgreSQL потому что граф индексирует связи
        """
        query = f"""
        SELECT * FROM liked
        WHERE in = user:{user2_id} AND out = user:{user1_id}
        """
        result = await self.db.query(query)

        # Если есть хотя бы одна запись — взаимный лайк
        return result and len(result) > 0 and "result" in result[0] and len(result[0]["result"]) > 0

    async def delete_interactions_between(self, user1_id: int, user2_id: int):
        """
        Удаляем графовые связи между двумя пользователями в обе стороны.
        Это нужно при удалении мэтча, чтобы пара могла встретиться заново.
        """
        query = f"""
        DELETE liked WHERE (out = user:{user1_id} AND in = user:{user2_id})
            OR (out = user:{user2_id} AND in = user:{user1_id});
        DELETE skipped WHERE (out = user:{user1_id} AND in = user:{user2_id})
            OR (out = user:{user2_id} AND in = user:{user1_id});
        DELETE viewed WHERE (out = user:{user1_id} AND in = user:{user2_id})
            OR (out = user:{user2_id} AND in = user:{user1_id});
        """
        await self.db.query(query)
        logger.debug(f"Graph edges deleted between {user1_id} and {user2_id}")
