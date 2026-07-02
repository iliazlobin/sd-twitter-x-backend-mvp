import uuid
from datetime import datetime

from pydantic import BaseModel

from twitter_x.schemas.tweet import TweetAuthor


class SearchResult(BaseModel):
    type: str  # "tweet" or "hashtag"
    tweet_id: uuid.UUID | None = None
    text: str | None = None
    hashtag_id: uuid.UUID | None = None
    name: str | None = None
    author: TweetAuthor | None = None
    created_at: datetime | None = None
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    next_cursor: str | None
