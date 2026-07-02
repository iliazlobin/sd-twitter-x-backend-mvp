from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.database import get_session
from twitter_x.schemas.timeline import TimelineResponse
from twitter_x.services.timeline_service import decode_cursor, get_home_timeline

timeline_router = APIRouter(prefix="/api/v1/timeline", tags=["timeline"])


@timeline_router.get("/home", response_model=TimelineResponse)
async def home_timeline(
    user_id: UUID = Query(...),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> TimelineResponse:
    """Get the home timeline for a user."""
    decoded_cursor = None
    if cursor:
        decoded_cursor = decode_cursor(cursor)
        if decoded_cursor is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    try:
        items, next_cursor = await get_home_timeline(db, user_id, decoded_cursor)
    except HTTPException:
        raise
    return TimelineResponse(tweets=items, next_cursor=next_cursor)
