from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from configs.base import settings

engine = create_async_engine(settings.DATABASE_URL, echo=True)
SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
