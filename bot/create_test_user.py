"""
Create one realistic test user with approved photos.

Examples:
  python create_test_user.py
  python create_test_user.py --target-telegram-id 5497326447 --action like
  python create_test_user.py --target-telegram-id 5497326447 --action match
  python create_test_user.py --gender female --photos 5 --city Москва
"""

import argparse
import asyncio
import io
import os
import random
import struct
import uuid
import zlib

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import (
    Gender,
    Interaction,
    Match,
    ModerationStatus,
    Photo,
    Preference,
    Profile,
    Rating,
    User,
)
from surreal import SurrealClient


DATABASE_URL = (
    f"postgresql+asyncpg://"
    f"{os.environ.get('DB_USER', 'postgres')}:"
    f"{os.environ.get('DB_PASSWORD', 'postgres')}@"
    f"{os.environ.get('DB_HOST', 'localhost')}:"
    f"{os.environ.get('DB_PORT', '5433')}/"
    f"{os.environ.get('DB_NAME', 'dating_bot')}"
)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "profiles")
SURREAL_URL = os.environ.get("SURREAL_URL", "ws://localhost:8000/rpc")
SURREAL_USER = os.environ.get("SURREAL_USER", "root")
SURREAL_PASS = os.environ.get("SURREAL_PASS", "root")

MALE_NAMES = ["Александр", "Дмитрий", "Максим", "Иван", "Никита", "Михаил"]
FEMALE_NAMES = ["Анастасия", "Мария", "Екатерина", "Дарья", "Анна", "Валерия"]
DESCRIPTIONS = [
    "Люблю прогулки, кофе и спокойные разговоры без спешки.",
    "Ищу человека, с которым можно сходить в кино и обсудить всё на свете.",
    "Работаю, учусь новому, по выходным выбираюсь гулять по городу.",
    "Ценю чувство юмора, честность и умение нормально общаться.",
]
INTERESTS = [
    "кино, музыка, прогулки",
    "спорт, путешествия, кофе",
    "IT, книги, настольные игры",
    "фотография, концерты, кулинария",
]
PNG_COLORS = [
    (64, 118, 255),
    (255, 116, 64),
    (77, 181, 107),
    (171, 91, 255),
    (240, 184, 64),
]


def png_bytes(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    raw_rows = []
    for _ in range(height):
        raw_rows.append(b"\x00" + bytes(color) * width)
    raw = b"".join(raw_rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=9))
        + chunk(b"IEND", b"")
    )


def create_minio_client():
    client = boto3.client(
        "s3",
        endpoint_url=f"http://{MINIO_ENDPOINT}",
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )
    try:
        client.head_bucket(Bucket=MINIO_BUCKET)
    except ClientError:
        client.create_bucket(Bucket=MINIO_BUCKET)
    return client


def upload_photo(client, telegram_id: int, photo_index: int) -> str:
    color = PNG_COLORS[photo_index % len(PNG_COLORS)]
    content = png_bytes(900, 1200, color)
    key = f"photos/{telegram_id}/seed-{uuid.uuid4().hex}.png"
    client.upload_fileobj(
        io.BytesIO(content),
        MINIO_BUCKET,
        key,
        ExtraArgs={"ContentType": "image/png"},
    )
    return key


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def create_user(args):
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    minio = create_minio_client()
    surreal = None

    async with session_factory() as session:
        telegram_id = args.telegram_id or random.randint(9_100_000_000, 9_999_999_999)
        while await get_user_by_telegram_id(session, telegram_id):
            telegram_id += 1

        gender = Gender.MALE if args.gender == "male" else Gender.FEMALE
        name_pool = MALE_NAMES if gender == Gender.MALE else FEMALE_NAMES
        name = args.name or random.choice(name_pool)

        user = User(telegram_id=telegram_id, username=args.username or f"seed_user_{telegram_id}")
        session.add(user)
        await session.flush()

        photo_count = max(1, min(args.photos, 5))
        profile = Profile(
            user_id=user.id,
            name=name,
            age=args.age,
            gender=gender,
            city=args.city,
            description=args.description or random.choice(DESCRIPTIONS),
            interests=args.interests or random.choice(INTERESTS),
            photo_count=photo_count,
            completeness=1.0,
        )
        session.add(profile)
        session.add(
            Preference(
                user_id=user.id,
                preferred_gender=None,
                min_age=18,
                max_age=100,
                preferred_city=None,
            )
        )

        for index in range(photo_count):
            s3_key = upload_photo(minio, telegram_id, index)
            session.add(
                Photo(
                    user_id=user.id,
                    s3_key=s3_key,
                    status=ModerationStatus.APPROVED,
                    is_primary=index == 0,
                )
            )

        session.add(
            Rating(
                user_id=user.id,
                primary_score=1.0,
                behavioral_score=0.5,
                combined_score=0.8,
            )
        )

        target_user = None
        if args.target_telegram_id:
            target_user = await get_user_by_telegram_id(session, args.target_telegram_id)
            if not target_user:
                raise RuntimeError(
                    f"Target user with telegram_id={args.target_telegram_id} not found. "
                    "Open /start from that account first."
                )

        if target_user and args.action != "none":
            surreal = SurrealClient(SURREAL_URL, SURREAL_USER, SURREAL_PASS)
            await surreal.connect()

        if target_user and args.action in {"like", "match"}:
            session.add(
                Interaction(
                    from_user_id=user.id,
                    to_user_id=target_user.id,
                    action="like",
                )
            )
            await surreal.add_interaction(user.id, target_user.id, "liked")

        if target_user and args.action == "skip":
            session.add(
                Interaction(
                    from_user_id=user.id,
                    to_user_id=target_user.id,
                    action="skip",
                )
            )
            await surreal.add_interaction(user.id, target_user.id, "skipped")

        if target_user and args.action == "match":
            session.add(
                Interaction(
                    from_user_id=target_user.id,
                    to_user_id=user.id,
                    action="like",
                )
            )
            await surreal.add_interaction(target_user.id, user.id, "liked")
            user1_id = min(user.id, target_user.id)
            user2_id = max(user.id, target_user.id)
            existing_match = await session.execute(
                select(Match).where(
                    Match.user1_id == user1_id,
                    Match.user2_id == user2_id,
                    Match.is_active.is_(True),
                )
            )
            if not existing_match.scalar_one_or_none():
                session.add(Match(user1_id=user1_id, user2_id=user2_id))

        await session.commit()

        print("Created test user:")
        print(f"  db user_id: {user.id}")
        print(f"  telegram_id: {user.telegram_id}")
        print(f"  username: @{user.username}")
        print(f"  name: {profile.name}")
        print(f"  photos: {photo_count} approved")
        if target_user:
            print(f"  action toward {target_user.telegram_id}: {args.action}")

        if surreal:
            await surreal.close()

    await engine.dispose()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-telegram-id", type=int)
    parser.add_argument("--action", choices=["none", "like", "skip", "match"], default="none")
    parser.add_argument("--telegram-id", type=int)
    parser.add_argument("--username")
    parser.add_argument("--name")
    parser.add_argument("--gender", choices=["male", "female"], default="female")
    parser.add_argument("--age", type=int, default=24)
    parser.add_argument("--city", default="Москва")
    parser.add_argument("--description")
    parser.add_argument("--interests")
    parser.add_argument("--photos", type=int, default=3)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(create_user(parse_args()))
