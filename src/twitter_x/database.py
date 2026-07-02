from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from twitter_x.config import settings

_engine = None
_async_session_factory = None


def get_engine():
    """Lazy-init engine so tests can override settings first."""
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=False)
    return _engine


def get_session_factory():
    """Lazy-init session factory."""
    global _async_session_factory  # noqa: PLW0603
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
        try:
            if session.in_transaction():
                await session.commit()
        except Exception:
            await session.rollback()
            raise
