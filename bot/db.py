from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from bot.config import config

engine = create_async_engine(config.database_url, echo=False, pool_size=10, max_overflow=5)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
