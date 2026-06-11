from .base import Settings

class TestSettings(Settings):
    DEBUG: bool = True
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/cv_db_test"

settings = TestSettings()
