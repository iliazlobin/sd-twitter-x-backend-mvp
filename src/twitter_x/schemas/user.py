from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str | None = Field(None, max_length=50)


class UserResponse(BaseModel):
    user_id: UUID
    username: str
    display_name: str | None
    follower_count: int
    following_count: int
    created_at: datetime
