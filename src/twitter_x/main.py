from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from twitter_x.database import get_engine
from twitter_x.models.base import Base
from twitter_x.redis import close_redis
from twitter_x.routers import routers
from twitter_x.workers.fanout_worker import fanout_worker_lifespan
from twitter_x.workers.trending_worker import trending_worker_lifespan


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    fanout_stop = await fanout_worker_lifespan()
    trending_stop = await trending_worker_lifespan()

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
