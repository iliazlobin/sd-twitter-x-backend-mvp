from twitter_x.routers.health import router as health_router
from twitter_x.routers.search import router as search_router
from twitter_x.routers.timeline import router as timeline_router
from twitter_x.routers.trends import router as trends_router
from twitter_x.routers.tweets import router as tweets_router
from twitter_x.routers.users import router as users_router

routers = [
    health_router,
    users_router,
    tweets_router,
    timeline_router,
    search_router,
    trends_router,
]

__all__ = ["routers"]
