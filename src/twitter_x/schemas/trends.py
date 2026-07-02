import uuid

from pydantic import BaseModel, Field


class TrendItem(BaseModel):
    hashtag_id: uuid.UUID
    name: str
    velocity_score: float
    tweet_count: int


class TrendsResponse(BaseModel):
    trends: list[TrendItem]
    window: str = Field(default="1h")
