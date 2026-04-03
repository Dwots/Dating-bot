from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, BigInteger, String, Boolean, Integer, Float, DateTime, Text, Enum as SQLEnum, ForeignKey
from sqlalchemy.sql import func
import enum


class Base(DeclarativeBase):
    pass


class Gender(enum.Enum):
    MALE = "male"
    FEMALE = "female"


class ModerationStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_banned = Column(Boolean, default=False)


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    name = Column(String(100), nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(SQLEnum(Gender), nullable=True)
    city = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    interests = Column(Text, nullable=True)
    photo_count = Column(Integer, default=0)
    completeness = Column(Float, default=0.0)
    moderation_status = Column(SQLEnum(ModerationStatus), default=ModerationStatus.PENDING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Preference(Base):
    __tablename__ = "preferences"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    preferred_gender = Column(SQLEnum(Gender), nullable=True)
    min_age = Column(Integer, default=18)
    max_age = Column(Integer, default=100)
    preferred_city = Column(String(100), nullable=True)


class Match(Base):
    __tablename__ = "matches"

    id = Column(BigInteger, primary_key=True)
    user1_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    user2_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(BigInteger, primary_key=True)
    from_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    to_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(20), nullable=False)  # 'like', 'skip', 'view'
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Rating(Base):
    __tablename__ = "ratings"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    primary_score = Column(Float, default=0.0)
    behavioral_score = Column(Float, default=0.0)
    combined_score = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Database:
    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url, echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def create_tables(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def get_session(self) -> AsyncSession:
        async with self.session_factory() as session:
            return session
