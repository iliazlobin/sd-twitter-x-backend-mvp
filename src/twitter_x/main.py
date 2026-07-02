from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from twitter_x.redis import close_redis, init_redis
from twitter_x.routers.health import health_router
from twitter_x.routers.search import search_router
from twitter_x.routers.timeline import timeline_router
from twitter_x.routers.trends import trends_router
from twitter_x.routers.tweets import tweets_router
from twitter_x.routers.users import users_router
from twitter_x.workers.fanout_worker import FanOutWorker
from twitter_x.workers.trending_worker import TrendingWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting up Twitter/X backend")
    app.state.redis = await init_redis()

    fanout_worker = FanOutWorker()
    trending_worker = TrendingWorker()
    app.state.fanout_worker = fanout_worker
    app.state.trending_worker = trending_worker
    await fanout_worker.start()
    await trending_worker.start()

    yield

    logger.info("Shutting down Twitter/X backend")
    await fanout_worker.stop()
    await trending_worker.stop()
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Twitter/X MVP Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(users_router)
    app.include_router(tweets_router)
    app.include_router(timeline_router)
    app.include_router(search_router)
    app.include_router(trends_router)

    return app


app = create_app()
