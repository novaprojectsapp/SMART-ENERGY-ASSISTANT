import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings(BaseSettings):
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'smart_energy.db'}"
    TEST_DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'test_smart_energy.db'}"
    DEVICE_API_KEY: str = "change-me-in-production"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_ENABLED: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"


def _resolve_database_url() -> str:
    if os.environ.get("APP_TESTING") == "1":
        return settings.TEST_DATABASE_URL
    return settings.DATABASE_URL


settings = Settings()
