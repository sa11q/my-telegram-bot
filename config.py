from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):

    # Telegram
    BOT_TOKEN: str = Field(..., min_length=20)

    # Owner
    OWNER_ID: int = 0
    OWNER_USERNAME: str = "@wonti9"

    # Database
    DB_TYPE: str = "json"

    JSON_DB_PATH: str = "database/database.json"

    POSTGRES_URL: Optional[str] = None


    # Redis FSM
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None


    # Admin system
    ADMIN_IDS: List[int] = []


    # Bot settings
    BOT_LANGUAGE: str = "ru"

    DEBUG_MODE: bool = False


    # Tournament settings
    DEFAULT_ELO: int = 1200

    ELO_K_FACTOR: int = 32

    MATCH_CONFIRM_TIMEOUT: int = 3600
    # 1 час на подтверждение

    DEFAULT_MATCH_DEADLINE: int = 86400
    # 24 часа на матч


    # Reminders
    REMINDER_ENABLED: bool = True

    REMINDER_INTERVAL_MINUTES: int = 30


    # Security
    MAX_REQUESTS_PER_MINUTE: int = 30

    ENABLE_RATE_LIMIT: bool = True


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


    @field_validator("DB_TYPE")
    @classmethod
    def validate_db(cls, value):
        value = value.lower()

        if value not in [
            "json",
            "postgres"
        ]:
            raise ValueError(
                "DB_TYPE must be json or postgres"
            )

        return value


    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admins(cls, value):

        if not value:
            return []

        if isinstance(value, list):
            return value

        return [
            int(x.strip())
            for x in value.split(",")
            if x.strip()
        ]


    def validate_production(self):

        if not self.BOT_TOKEN:
            raise RuntimeError(
                "BOT_TOKEN missing"
            )

        if self.DB_TYPE == "postgres" and not self.POSTGRES_URL:
            raise RuntimeError(
                "POSTGRES_URL required for postgres mode"
            )


config = Settings()

config.validate_production()
