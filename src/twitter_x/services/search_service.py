"""Search service — FTS query builder, UNION across tweet + hashtag tsvectors."""

from sqlalchemy.ext.asyncio import AsyncSession


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        query: str,
        cursor: str | None = None,
    ) -> tuple[list[dict], str | None]:
        """Full-text search stub. Returns empty results until the staff task implements FR4."""
        return [], None
