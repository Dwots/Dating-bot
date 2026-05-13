import os
import logging
import requests
from celery import Task
from celery_app import app
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

# Настройки БД
DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.environ.get('DB_USER', 'postgres')}:"
    f"{os.environ.get('DB_PASSWORD', 'postgres')}@"
    f"{os.environ.get('DB_HOST', 'postgres')}:"
    f"{os.environ.get('DB_PORT', '5432')}/"
    f"{os.environ.get('DB_NAME', 'dating_bot')}"
)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
TELEGRAM_PROXY = os.environ.get("TELEGRAM_PROXY") or None

# Celery задачи синхронные — используем обычный psycopg2
# (не asyncpg как в боте)
# Создаём engine один раз при старте воркера
engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    return SessionLocal()


# Пересчёт рейтингов 

@app.task(name="tasks.recalculate_ratings")
def recalculate_ratings():
    """
    Запускается каждые 30 минут через Celery Beat.
    
    Алгоритм для каждого пользователя:
    
    Уровень 1 — первичный (данные профиля):
      completeness  — насколько заполнена анкета (0.0 - 1.0)
      photo_score   — есть ли фото (max 5 фото = 1.0)
      → primary_score = completeness * 0.4 + photo_score * 0.3 + 0.3
        (0.3 — базовый балл за существование анкеты)
    
    Уровень 2 — поведенческий (взаимодействия других с анкетой):
      like_ratio    — лайки / (лайки + пропуски)
      match_rate    — матчи / лайки
      activity      — был активен последние 24ч?
      → behavioral_score = like_ratio*0.35 + match_rate*0.35 + activity*0.30
    
    Уровень 3 — комбинированный:
      referral_bonus — количество приглашённых друзей
      → combined = primary*0.4 + behavioral*0.4 + referral_bonus*0.2
    """
    logger.info("Starting ratings recalculation...")
    session = get_session()

    try:
        # Берём всех незабаненных пользователей у которых есть профиль
        users = session.execute(text("""
            SELECT 
                u.id,
                u.last_active_at,
                p.completeness,
                p.photo_count
            FROM users u
            JOIN profiles p ON p.user_id = u.id
            WHERE u.is_banned = false
        """)).fetchall()

        logger.info(f"Recalculating ratings for {len(users)} users")

        for user in users:
            user_id = user.id
            score = _calculate_user_rating(session, user_id, user)

            # Upsert — обновляем если есть, вставляем если нет
            session.execute(text("""
                INSERT INTO ratings (user_id, primary_score, behavioral_score, combined_score, updated_at)
                VALUES (:user_id, :primary, :behavioral, :combined, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    primary_score    = EXCLUDED.primary_score,
                    behavioral_score = EXCLUDED.behavioral_score,
                    combined_score   = EXCLUDED.combined_score,
                    updated_at       = NOW()
            """), {
                "user_id": user_id,
                "primary": score["primary"],
                "behavioral": score["behavioral"],
                "combined": score["combined"],
            })

        session.commit()
        logger.info("Ratings recalculation complete")
        return f"Recalculated {len(users)} ratings"

    except Exception as e:
        session.rollback()
        logger.error(f"Error recalculating ratings: {e}")
        raise
    finally:
        session.close()


def _calculate_user_rating(session: Session, user_id: int, user_row) -> dict:
    """
    Считаем три уровня рейтинга для одного пользователя
    """

    # Первичный рейтинг 

    completeness = float(user_row.completeness or 0)
    photo_count = int(user_row.photo_count or 0)

    # photo_score: 0 фото = 0.0, 1 фото = 0.2, 5+ фото = 1.0
    photo_score = min(photo_count / 5, 1.0)

    primary_score = (
        completeness * 0.4 +   # насколько заполнена анкета
        photo_score  * 0.3 +   # наличие фото
        0.3                    # базовый балл
    )

    # Поведенческий рейтинг 

    # Считаем лайки и пропуски полученные этим пользователем
    interactions = session.execute(text("""
        SELECT action, COUNT(*) as cnt
        FROM interactions
        WHERE to_user_id = :user_id
          AND action IN ('like', 'skip')
        GROUP BY action
    """), {"user_id": user_id}).fetchall()

    likes_received = 0
    skips_received = 0
    for row in interactions:
        if row.action == "like":
            likes_received = row.cnt
        elif row.action == "skip":
            skips_received = row.cnt

    # Количество матчей пользователя
    matches_count = session.execute(text("""
        SELECT COUNT(*) as cnt FROM matches
        WHERE (user1_id = :uid OR user2_id = :uid)
          AND is_active = true
    """), {"uid": user_id}).scalar()

    # like_ratio: какой процент людей лайкнул анкету
    total_reactions = likes_received + skips_received
    like_ratio = likes_received / total_reactions if total_reactions > 0 else 0.0

    # match_rate: какой процент лайков привёл к матчу
    match_rate = matches_count / likes_received if likes_received > 0 else 0.0
    match_rate = min(match_rate, 1.0)  # не больше 1.0

    # activity_bonus: был активен последние 24 часа?
    is_active = session.execute(text("""
        SELECT 1 FROM users
        WHERE id = :uid
          AND last_active_at > NOW() - INTERVAL '24 hours'
    """), {"uid": user_id}).fetchone()
    activity_bonus = 1.0 if is_active else 0.5

    behavioral_score = (
        like_ratio     * 0.35 +
        match_rate     * 0.35 +
        activity_bonus * 0.30
    )

    # Комбинированный рейтинг 

    # Считаем сколько друзей пригласил пользователь
    referrals_count = session.execute(text("""
        SELECT COUNT(*) FROM referrals WHERE referrer_id = :uid
    """), {"uid": user_id}).scalar()

    # Каждый приглашённый друг даёт +0.05 к бонусу, максимум 0.2
    referral_bonus = min(referrals_count * 0.05, 0.2)

    combined_score = (
        primary_score    * 0.4 +
        behavioral_score * 0.4 +
        referral_bonus   * 0.2
    )

    logger.debug(
        f"User {user_id}: primary={primary_score:.3f}, "
        f"behavioral={behavioral_score:.3f}, combined={combined_score:.3f}"
    )

    return {
        "primary": round(primary_score, 4),
        "behavioral": round(behavioral_score, 4),
        "combined": round(combined_score, 4),
    }


# Уведомление о матче 

@app.task(name="tasks.notify_match")
def notify_match(user1_telegram_id: int, user2_telegram_id: int, user1_name: str):
    """
    Получает данные матча и отправляет push-уведомление второму пользователю.
    Первый пользователь уже получает сообщение прямо в карточке, где нажал лайк.

    Вызывается из consumer который слушает очередь "match" в RabbitMQ.
    
    Используем requests (синхронный HTTP) потому что Celery задачи синхронные.
    Bot API endpoint: POST https://api.telegram.org/bot{TOKEN}/sendMessage
    """
    logger.info(f"Sending match notification to {user2_telegram_id}")

    session = get_session()
    try:
        # Получаем контакт первого пользователя для уведомления второму
        user1_profile = session.execute(text("""
            SELECT u.username FROM users u
            WHERE u.telegram_id = :tg_id
        """), {"tg_id": user1_telegram_id}).fetchone()

        user1_contact = f"@{user1_profile.username}" if user1_profile and user1_profile.username else "тег не указан"

        # Отправляем уведомление второму пользователю
        _send_telegram_message(
            user2_telegram_id,
            f"🎉 У вас новый мэтч с {user1_name}!\n\nКуда писать: {user1_contact}",
            reply_markup=main_menu_reply_markup(),
        )

        logger.info("Match notification sent successfully")

    except Exception as e:
        logger.error(f"Error sending match notification: {e}")
        raise
    finally:
        session.close()


def main_menu_reply_markup() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "👤 Моя анкета", "callback_data": "my_profile"}],
            [{"text": "💕 Смотреть анкеты", "callback_data": "view_profiles"}],
            [{"text": "❤️ Мои мэтчи", "callback_data": "my_matches"}],
            [{"text": "⚙️ Настройки поиска", "callback_data": "search_settings"}],
            [{"text": "👥 Пригласить друга", "callback_data": "referral"}],
        ]
    }


def _send_telegram_message(telegram_id: int, text: str, reply_markup: dict | None = None):
    """
    Отправляем сообщение через Telegram Bot API напрямую (HTTP запрос)
    Не используем aiogram — он асинхронный, а мы в синхронном Celery
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    proxies = None
    if TELEGRAM_PROXY:
        proxies = {
            "http": TELEGRAM_PROXY,
            "https": TELEGRAM_PROXY,
        }

    payload = {
        "chat_id": telegram_id,
        "text": text,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    response = requests.post(url, json=payload, timeout=10, proxies=proxies)

    if not response.ok:
        logger.error(f"Telegram API error: {response.text}")


@app.task(name="tasks.process_like")
def process_like(from_user_id: int, to_user_id: int):
    """
    Обрабатываем событие лайка.
    Сейчас просто логируем — рейтинг пересчитается через Beat.
    В будущем можно делать инкрементальный пересчёт.
    """
    logger.info(f"Like event: {from_user_id} → {to_user_id}")


@app.task(name="tasks.process_skip")
def process_skip(from_user_id: int, to_user_id: int):
    logger.info(f"Skip event: {from_user_id} → {to_user_id}")
