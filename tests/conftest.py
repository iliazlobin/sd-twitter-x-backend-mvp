"""Shared fixtures for white-box tests."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from twitter_x.models.base import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///file::memory:?cache=shared"


@pytest_asyncio.fixture(scope="session")
def event_loop() -> Any:
    """Session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create an in-memory SQLite engine for tests."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Fresh session per test with rollback isolation."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
