import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.database import get_session
from twitter_x.models.follow import Follow
from twitter_x.models.user import User
from twitter_x.schemas.common import FollowResponse
from twitter_x.schemas.user import UserCreate, UserResponse

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.post("", status_code=201)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    existing = await session.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(username=body.username, display_name=body.display_name)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserResponse.model_validate(user)


@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.post("/{followee_id}/follow")
async def follow_user(
    followee_id: uuid.UUID,
    follower_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> FollowResponse:
    if follower_id == followee_id:
        raise HTTPException(status_code=422, detail="Cannot follow yourself")

    follower = await session.get(User, follower_id)
    followee = await session.get(User, followee_id)
    if not follower or not followee:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await session.execute(
        select(Follow).where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
    )
    if existing.scalar_one_or_none():
        return FollowResponse(status="following")

    session.add(Follow(follower_id=follower_id, followee_id=followee_id))
    follower.following_count += 1
    followee.follower_count += 1
    await session.commit()

    return FollowResponse(status="following")


@router.delete("/{followee_id}/follow")
async def unfollow_user(
    followee_id: uuid.UUID,
    follower_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> FollowResponse:
    follower = await session.get(User, follower_id)
    followee = await session.get(User, followee_id)
    if not follower or not followee:
        raise HTTPException(status_code=404, detail="User not found")

    result = await session.execute(
        select(Follow).where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
    )
    follow = result.scalar_one_or_none()
    if not follow:
        return FollowResponse(status="unfollowed")

    await session.delete(follow)
    follower.following_count = max(0, follower.following_count - 1)
    followee.follower_count = max(0, followee.follower_count - 1)
    await session.commit()

    return FollowResponse(status="unfollowed")
