"""
Скрипт для заполнения БД тестовыми данными.
Запускать: python seed.py
"""
import asyncio
import random
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database import Base, User, Profile, Preference, Rating, Gender
import os

DATABASE_URL = (
    f"postgresql+asyncpg://"
    f"{os.environ.get('DB_USER', 'postgres')}:"
    f"{os.environ.get('DB_PASSWORD', 'postgres')}@"
    f"{os.environ.get('DB_HOST', 'localhost')}:"
    f"{os.environ.get('DB_PORT', '5433')}/"  # 5433 — внешний порт
    f"{os.environ.get('DB_NAME', 'dating_bot')}"
)

MALE_NAMES = ["Александр", "Дмитрий", "Максим", "Иван", "Артём", "Никита", "Михаил", "Андрей", "Кирилл", "Сергей"]
FEMALE_NAMES = ["Анастасия", "Мария", "Екатерина", "Дарья", "Анна", "Елена", "Ольга", "Валерия", "Полина", "Юлия"]
CITIES = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Краснодар"]
DESCRIPTIONS = [
    "Люблю путешествия и новые знакомства",
    "Ищу интересного собеседника",
    "Обожаю спорт и активный отдых",
    "Люблю готовить и принимать гостей",
    "Увлекаюсь фотографией и музыкой",
    "Работаю в IT, люблю кино и книги",
    "Ценю юмор и искренность в людях",
    "Занимаюсь йогой и медитацией",
]
INTERESTS = [
    "спорт, путешествия, музыка",
    "кино, книги, кулинария",
    "фотография, искусство, танцы",
    "IT, игры, аниме",
    "фитнес, здоровый образ жизни",
    "музыка, концерты, театр",
]


async def seed():
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        print("Создаём тестовых пользователей...")

        created = 0
        # Начинаем telegram_id с большого числа чтобы не пересекаться с реальными
        start_id = 9000000000

        for i in range(200):
            telegram_id = start_id + i
            gender = random.choice([Gender.MALE, Gender.FEMALE])
            name = random.choice(MALE_NAMES if gender == Gender.MALE else FEMALE_NAMES)
            age = random.randint(18, 35)
            city = random.choice(CITIES)

            # Создаём пользователя
            user = User(
                telegram_id=telegram_id,
                username=f"test_user_{i}",
            )
            session.add(user)
            await session.flush()  # flush чтобы получить user.id

            # Создаём профиль
            profile = Profile(
                user_id=user.id,
                name=name,
                age=age,
                gender=gender,
                city=city,
                description=random.choice(DESCRIPTIONS),
                interests=random.choice(INTERESTS),
                photo_count=0,
                # completeness считаем вручную
                # заполнены: name, age, gender, city, description, interests = 6/7
                completeness=6/7,
            )
            session.add(profile)

            # Создаём preferences
            pref = Preference(
                user_id=user.id,
                preferred_gender=None,  # ищут всех
                min_age=18,
                max_age=40,
                preferred_city=None,
            )
            session.add(pref)

            # Создаём рейтинг
            # Считаем как в tasks.py
            completeness = 6/7
            photo_score = 0.0
            primary = completeness * 0.4 + photo_score * 0.3 + 0.3
            behavioral = 0.5 * 0.30  # только activity bonus (0.5 — не активен)
            combined = primary * 0.4 + behavioral * 0.4 + 0.0

            rating = Rating(
                user_id=user.id,
                primary_score=round(primary, 4),
                behavioral_score=round(behavioral, 4),
                combined_score=round(combined, 4),
            )
            session.add(rating)
            created += 1

        await session.commit()
        print(f"✅ Создано {created} тестовых пользователей")

        # Проверяем
        from sqlalchemy import text
        result = await session.execute(text(
            "SELECT COUNT(*) FROM users"
        ))
        total = result.scalar()
        print(f"Всего пользователей в БД: {total}")


if __name__ == "__main__":
    asyncio.run(seed())