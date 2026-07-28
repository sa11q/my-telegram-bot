import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    BOT_TOKEN: str
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    DB_TYPE: str = "json"
    JSON_DB_PATH: str = "database/database.json"
    POSTGRES_URL: str = ""
    ADMIN_IDS: List[int] = []

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

config = Settings()

