from __future__ import annotations

from pydantic import BaseModel


class FollowResponse(BaseModel):
    status: str
