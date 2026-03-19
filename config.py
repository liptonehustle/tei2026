"""
config.py — Central configuration loader
Reads all settings from environment variables (.env file).
Import this in every service module: from config import db, redis_cfg, app
"""

import os
from dotenv import load_dotenv

load_dotenv()


class DatabaseConfig:
    HOST     = os.getenv("POSTGRES_HOST", "localhost")
    PORT     = int(os.getenv("POSTGRES_PORT", 5432))
    USER     = os.getenv("POSTGRES_USER", "trading_user")
    PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
    DB       = os.getenv("POSTGRES_DB", "trading_db")

    @property
    def url(self):
        return f"postgresql://{self.USER}:{self.PASSWORD}@{self.HOST}:{self.PORT}/{self.DB}"


class RedisConfig:
    HOST     = os.getenv("REDIS_HOST", "localhost")
    PORT     = int(os.getenv("REDIS_PORT", 6379))
    PASSWORD = os.getenv("REDIS_PASSWORD", "")

    @property
    def url(self):
        return f"redis://:{self.PASSWORD}@{self.HOST}:{self.PORT}/0"


class ExchangeConfig:
    BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
    ALPHA_VANTAGE_KEY  = os.getenv("ALPHA_VANTAGE_KEY", "")


class OllamaConfig:
    HOST  = os.getenv("OLLAMA_HOST", "localhost")
    PORT  = int(os.getenv("OLLAMA_PORT", 11434))
    MODEL = os.getenv("OLLAMA_MODEL", "llama3")

    @property
    def url(self):
        return f"http://{self.HOST}:{self.PORT}"


class AppConfig:
    LOG_LEVEL   = os.getenv("LOG_LEVEL", "INFO")
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


db         = DatabaseConfig()
redis_cfg  = RedisConfig()
exchange   = ExchangeConfig()
ollama     = OllamaConfig()
app        = AppConfig()
