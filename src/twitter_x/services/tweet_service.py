"""Tweet service — tweet creation with hashtag extraction/upsert, fan-out dispatch."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.models.hashtag import Hashtag, TweetHashtag
from twitter_x.models.tweet import Tweet


class TweetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def extract_hashtags(text: str) -> set[str]:
        return {tag.lower() for tag in re.findall(r"#(\w+)", text)}

    async def create_tweet(
        self,
        author_id: uuid.UUID,
        text: str,
        client_hashtags: list[str] | None = None,
    ) -> Tweet:
        tag_names = self.extract_hashtags(text)
        if client_hashtags:
            tag_names.update(h.lower() for h in client_hashtags)

        tweet = Tweet(author_id=author_id, text=text)
        self.session.add(tweet)
        await self.session.flush()

        for name in tag_names:
            stmt = select(Hashtag).where(Hashtag.name == name)
            result = await self.session.execute(stmt)
            hashtag = result.scalar_one_or_none()
            if not hashtag:
                hashtag = Hashtag(name=name)
                self.session.add(hashtag)
                await self.session.flush()

            self.session.add(TweetHashtag(tweet_id=tweet.tweet_id, hashtag_id=hashtag.hashtag_id))

        await self.session.commit()
        await self.session.refresh(tweet)
        return tweet
