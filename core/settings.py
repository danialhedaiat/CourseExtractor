from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Upload / extraction
    UPLOAD_DIR: Path = Path("media")
    CHUNK_SIZE: int = 1024 * 1024  # 1 MiB
    ALLOWED_EXTENSION: str = ".tar"

    # Video download
    YOUTUBE_VIDEO_QUALITY: str = "720"

    # Database
    DATABASE_URL: str = "sqlite:///./courses.db"

    # Celery / Redis
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"


settings = Settings()
