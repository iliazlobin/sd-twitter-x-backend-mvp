import json
import uuid
from base64 import b64decode, b64encode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.database import get_session
from twitter_x.schemas.search import SearchResponse, SearchResult
from twitter_x.schemas.tweet import TweetAuthor

router = APIRouter(prefix="/api/v1/search", tags=["search"])

PAGE_SIZE = 20


def _encode_cursor(score: float, result_type: str, entity_id: str) -> str:
    payload = json.dumps(
        {"score": score, "type": result_type, "id": entity_id},
        separators=(",", ":"),
    )
    return b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[float, str, str]:
    try:
        payload = json.loads(b64decode(cursor.encode()).decode())
        return payload["score"], payload["type"], payload["id"]
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid cursor") from None


_SEARCH_SQL = text("""
    WITH query AS (
        SELECT websearch_to_tsquery('english', :q) AS tsq
    ),
    ranked AS (
        SELECT
            'tweet' AS type,
            t.tweet_id::text AS entity_id,
            t.text,
            NULL AS hashtag_name,
            NULL AS hashtag_id,
            t.author_id::text,
            u.username,
            u.display_name,
            t.created_at,
            (ts_rank(t.fts_vector, query.tsq) * recency_decay(t.created_at)) AS score
        FROM tweets t
        CROSS JOIN query
        JOIN users u ON t.author_id = u.user_id
        WHERE t.fts_vector @@ query.tsq

        UNION ALL

        SELECT
            'hashtag' AS type,
            h.hashtag_id::text AS entity_id,
            NULL AS text,
            h.name AS hashtag_name,
            h.hashtag_id::text,
            NULL AS author_id,
            NULL AS username,
            NULL AS display_name,
            NULL AS created_at,
            ts_rank(h.fts_vector, query.tsq) AS score
        FROM hashtags h
        CROSS JOIN query
        WHERE h.fts_vector @@ query.tsq
    )
    SELECT * FROM ranked
    WHERE (:cursor_score IS NULL
           OR (score, type, entity_id) < (:cursor_score, :cursor_type, :cursor_id))
    ORDER BY score DESC
    LIMIT :limit
""")


@router.get("")
async def search(
    q: str = Query(""),
    cursor: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    if not q.strip():
        return SearchResponse(results=[], next_cursor=None)

    limit = PAGE_SIZE + 1

    if cursor:
        cursor_score, cursor_type, cursor_id = _decode_cursor(cursor)
    else:
        cursor_score = cursor_type = cursor_id = None

    result = await session.execute(
        _SEARCH_SQL,
        {
            "q": q,
            "limit": limit,
            "cursor_score": cursor_score,
            "cursor_type": cursor_type,
            "cursor_id": cursor_id,
        },
    )
    rows = result.all()

    has_more = len(rows) > PAGE_SIZE
    if has_more:
        rows = rows[:PAGE_SIZE]

    search_results: list[SearchResult] = []
    for row in rows:
        created_at = row.created_at.isoformat() if row.created_at else None
        author = None
        if row.username:
            author = TweetAuthor(
                user_id=uuid.UUID(row.author_id),
                username=row.username,
                display_name=row.display_name,
            )
        search_results.append(
            SearchResult(
                type=row.type,
                tweet_id=uuid.UUID(row.tweet_id) if row.tweet_id else None,
                text=row.text or row.hashtag_name,
                hashtag_id=uuid.UUID(row.hashtag_id) if row.hashtag_id else None,
                name=row.hashtag_name,
                author=author,
                created_at=created_at,
                score=row.score,
            )
        )

    next_cursor = None
    if has_more and search_results:
        last = search_results[-1]
        eid = str(last.tweet_id or last.hashtag_id or "")
        next_cursor = _encode_cursor(last.score, last.type, eid)

    return SearchResponse(results=search_results, next_cursor=next_cursor)
