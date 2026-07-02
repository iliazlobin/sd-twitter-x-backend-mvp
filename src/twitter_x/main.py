from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from twitter_x.database import get_session_factory
from twitter_x.redis import close_redis, ensure_redis
from twitter_x.routers import routers
from twitter_x.workers.fanout_worker import fanout_worker_lifespan
from twitter_x.workers.trending_worker import trending_worker_lifespan


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Schema is owned by Alembic (`alembic upgrade head` in CI/deploy); do NOT create_all here —
    # it races the migration step and raises DuplicateTableError ("relation ... already exists").
    redis = await ensure_redis()
    session_factory = get_session_factory()

    fanout_stop = await fanout_worker_lifespan(redis, session_factory)
    trending_stop = await trending_worker_lifespan(redis, session_factory)

    yield

    await fanout_stop()
    await trending_stop()
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(title="Twitter/X MVP", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    for router in routers:
        app.include_router(router)

    return app


app = create_app()
