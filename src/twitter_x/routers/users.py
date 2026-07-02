from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.database import get_session
from twitter_x.schemas.common import FollowResponse
from twitter_x.schemas.timeline import TimelineResponse
from twitter_x.schemas.user import UserCreate, UserResponse
from twitter_x.services.user_service import (
    _decode_cursor,
    get_profile_tweets,
    get_user_by_id,
    get_user_by_username,
    user_to_response,
)
from twitter_x.services.user_service import (
    create_user as create_user_svc,
)
from twitter_x.services.user_service import (
    follow_user as follow_user_svc,
)
from twitter_x.services.user_service import (
    unfollow_user as unfollow_user_svc,
)

users_router = APIRouter(prefix="/api/v1/users", tags=["users"])


@users_router.post("", status_code=201, response_model=UserResponse)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Create a new user."""
    # Check for duplicate username
    existing = await get_user_by_username(db, body.username)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already taken")

    try:
        user = await create_user_svc(db, body)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return user_to_response(user)


@users_router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Get user profile."""
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user_to_response(user)


@users_router.get("/{user_id}/tweets", response_model=TimelineResponse)
async def get_user_tweets(
    user_id: UUID,
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> TimelineResponse:
    """Get a user's profile timeline."""
    decoded_cursor = None
    if cursor:
        decoded_cursor = _decode_cursor(cursor)
        if decoded_cursor is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    items, next_cursor = await get_profile_tweets(db, user_id, decoded_cursor)
    return TimelineResponse(tweets=items, next_cursor=next_cursor)


@users_router.post("/{followee_id}/follow", response_model=FollowResponse)
async def follow_user(
    followee_id: UUID,
    follower_id: UUID = Query(...),
    db: AsyncSession = Depends(get_session),
) -> FollowResponse:
    """Follow a user (idempotent)."""
    try:
        result = await follow_user_svc(db, followee_id, follower_id)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    return result


@users_router.delete("/{followee_id}/follow", response_model=FollowResponse)
async def unfollow_user(
    followee_id: UUID,
    follower_id: UUID = Query(...),
    db: AsyncSession = Depends(get_session),
) -> FollowResponse:
    """Unfollow a user (idempotent)."""
    try:
        result = await unfollow_user_svc(db, followee_id, follower_id)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    return result
