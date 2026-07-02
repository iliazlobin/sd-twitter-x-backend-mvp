from pydantic import BaseModel


class CursorToken(BaseModel):
    """Opaque cursor token for cursor-based pagination.

    Serialized as base64 JSON for timelines (created_at, tweet_id)
    and search (score, type, id).
    """

    pass


class FollowResponse(BaseModel):
    status: str
