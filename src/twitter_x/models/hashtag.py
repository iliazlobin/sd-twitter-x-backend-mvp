import uuid

from sqlalchemy import Computed, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twitter_x.models.base import Base


class Hashtag(Base):
    __tablename__ = "hashtags"

    hashtag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    fts_vector = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', name)", persisted=True),
    )

    tweets = relationship("TweetHashtag", back_populates="hashtag", lazy="selectin")


class TweetHashtag(Base):
    __tablename__ = "tweet_hashtags"
    __table_args__ = (UniqueConstraint("tweet_id", "hashtag_id"),)

    tweet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tweets.tweet_id"), primary_key=True
    )
    hashtag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hashtags.hashtag_id"), primary_key=True
    )

    tweet = relationship("Tweet", back_populates="hashtags", lazy="selectin")
    hashtag = relationship("Hashtag", back_populates="tweets", lazy="selectin")
