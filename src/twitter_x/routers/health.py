from fastapi import APIRouter

health_router = APIRouter(tags=["health"])


@health_router.get("/healthz")
async def healthz():
    return {"status": "ok"}
