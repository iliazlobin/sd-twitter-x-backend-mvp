import uuid
from datetime import datetime

from sqlalchemy import Computed, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twitter_x.models.base import Base


class Tweet(Base):
    __tablename__ = "tweets"

    tweet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(String(280), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    fts_vector = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
    )

    author = relationship("User", back_populates="tweets", lazy="selectin")
    hashtags = relationship(
        "TweetHashtag", back_populates="tweet", lazy="selectin", cascade="all, delete-orphan"
    )
