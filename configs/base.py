from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
import json

class Settings(BaseSettings):
    PROJECT_NAME: str = "Computer Vision API"
    API_V1_STR: str = "/api/v1"
    
    # Database Configuration
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/cv_db"
    
    # Security Configuration
    SECRET_KEY: str = "super-secret-key-for-development-only-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    
    # CORS Configuration
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost:8000"]
    
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except Exception:
                    return [v]
            return v
        return v
    
    # Storage Configuration
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False
    MINIO_BUCKET_NAME: str = "cv-media"

    # Celery Configuration
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Redis Cache Configuration
    REDIS_URL: str = "redis://localhost:6379/1"


    # RTSP Configuration
    RTSP_RETRY_INTERVAL: int = 5  # seconds

    # YOLO Configuration
    YOLO_MODEL: str = "models/yolo12n.pt"
    YOLO_IMGSZ: int = 384
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()
