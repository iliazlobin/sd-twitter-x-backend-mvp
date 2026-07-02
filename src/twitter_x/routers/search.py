from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.database import get_session
from twitter_x.schemas.search import SearchResponse
from twitter_x.services.search_service import search as search_svc

search_router = APIRouter(prefix="/api/v1/search", tags=["search"])


@search_router.get("", response_model=SearchResponse)
async def search(
    q: str = Query("", description="Search query"),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> SearchResponse:
    """Full-text search across tweets and hashtags."""
    items, next_cursor = await search_svc(db, q, cursor)
    return SearchResponse(results=items, next_cursor=next_cursor)
