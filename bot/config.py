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

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


def load_config() -> Config:
    return Config(
        bot_token=os.environ.get("BOT_TOKEN", ""),
        db_host=os.environ.get("DB_HOST", "localhost"),
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_user=os.environ.get("DB_USER", "postgres"),
        db_password=os.environ.get("DB_PASSWORD", "postgres"),
        db_name=os.environ.get("DB_NAME", "dating_bot"),
    )
