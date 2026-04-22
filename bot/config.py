import os
from dataclasses import dataclass


@dataclass
class Config:
    bot_token: str
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    redis_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    rabbitmq_url: str
    surreal_url: str
    surreal_user: str
    surreal_pass: str

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


def load_config() -> Config:
    return Config(
        bot_token=os.environ.get("BOT_TOKEN", ""),
        db_host=os.environ.get("DB_HOST", "localhost"),
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_user=os.environ.get("DB_USER", "postgres"),
        db_password=os.environ.get("DB_PASSWORD", "postgres"),
        db_name=os.environ.get("DB_NAME", "dating_bot"),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
        minio_endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
        minio_access_key=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
        minio_secret_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
        minio_bucket=os.environ.get("MINIO_BUCKET", "profiles"),
        rabbitmq_url=os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
        surreal_url=os.environ.get("SURREAL_URL", "ws://localhost:8000/rpc"),
        surreal_user=os.environ.get("SURREAL_USER", "root"),
        surreal_pass=os.environ.get("SURREAL_PASS", "root"),
    )