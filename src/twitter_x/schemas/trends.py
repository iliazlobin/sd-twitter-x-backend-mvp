from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class TrendItem(BaseModel):
    hashtag_id: UUID | None = None
    name: str
    velocity_score: float
    tweet_count: int


class TrendsResponse(BaseModel):
    window: str
    trends: list[TrendItem]
