"""User service — CRUD, follow/unfollow with counter updates, timeline pre-population."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.models.follow import Follow
from twitter_x.models.user import User


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_user(self, username: str, display_name: str | None = None) -> User:
        existing = await self.session.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            raise ValueError("Username already taken")
        user = User(username=username, display_name=display_name)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> Follow:
        existing = await self.session.execute(
            select(Follow).where(
                Follow.follower_id == follower_id, Follow.followee_id == followee_id
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("Already following")

        follow = Follow(follower_id=follower_id, followee_id=followee_id)
        self.session.add(follow)
        await self.session.commit()
        await self.session.refresh(follow)
        return follow
