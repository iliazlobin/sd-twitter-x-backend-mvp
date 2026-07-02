from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def search(
    db: AsyncSession,
    query: str,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[dict], str | None]:
    """Full-text search across tweets and hashtags with relevance ranking."""
    query = query.strip()
    if not query:
        return [], None

    # Decode cursor (includes reference timestamp for stable pagination)
    cursor_score = None
    cursor_type = None
    cursor_id = None
    reference_time = datetime.now(timezone.utc)

    if cursor:
        decoded = _decode_search_cursor(cursor)
        if decoded:
            cursor_score, cursor_type, cursor_id, reference_time = decoded

    sql = text("""
        WITH tweet_matches AS (
            SELECT
                'tweet' AS result_type,
                t.tweet_id::text AS entity_id,
                t.text,
                t.author_id::text AS author_id,
                u.username,
                t.created_at,
                ts_rank(t.fts_vector, websearch_to_tsquery('english', :query))
                    * (1.0 / (1.0 + extract(epoch from (:ref_time - t.created_at)) / 86400.0))
                    AS score
            FROM tweets t
            JOIN users u ON t.author_id = u.user_id
            WHERE t.fts_vector @@ websearch_to_tsquery('english', :query)
        ),
        hashtag_matches AS (
            SELECT
                'hashtag' AS result_type,
                h.hashtag_id::text AS entity_id,
                NULL AS text,
                NULL AS author_id,
                NULL AS username,
                NULL::timestamptz AS created_at,
                0.0 AS score,
                h.name,
                COALESCE(cnt.cnt, 0) AS tweet_count
            FROM hashtags h
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS cnt
                FROM tweet_hashtags th
                WHERE th.hashtag_id = h.hashtag_id
            ) cnt ON true
            WHERE h.fts_vector @@ websearch_to_tsquery('english', :query)
        ),
        combined AS (
            SELECT
                result_type, entity_id, text, author_id, username, created_at, score,
                NULL AS name, NULL::bigint AS tweet_count
            FROM tweet_matches
            UNION ALL
            SELECT
                result_type, entity_id, text, author_id, username, created_at, score,
                name, tweet_count
            FROM hashtag_matches
        )
        SELECT
            result_type, entity_id, text, author_id, username,
            created_at, score, name, tweet_count
        FROM combined
        WHERE CAST(:cursor_score AS float) IS NULL
           OR score < CAST(:cursor_score AS float)
           OR (score = CAST(:cursor_score AS float)
               AND result_type > CAST(:cursor_type AS text))
           OR (score = CAST(:cursor_score AS float)
               AND result_type = CAST(:cursor_type AS text)
               AND entity_id < CAST(:cursor_id AS text))
        ORDER BY score DESC, result_type ASC, entity_id DESC
        LIMIT :limit_val
    """)

    params = {
        "query": query,
        "ref_time": reference_time,
        "cursor_score": cursor_score,
        "cursor_type": cursor_type,
        "cursor_id": cursor_id,
        "limit_val": limit + 1,
    }

    result = await db.execute(sql, params)
    rows = result.fetchall()

    has_more = len(rows) > limit
    rows = rows[:limit]

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_search_cursor(
            last.score, last.result_type, last.entity_id, reference_time
        )

    # Build response items
    items = []
    for row in rows:
        item = {
            "type": row.result_type,
            "score": float(row.score) if row.score else 0.0,
        }

        if row.result_type == "tweet":
            item["tweet_id"] = row.entity_id
            item["text"] = row.text
            item["author_id"] = row.author_id
            item["username"] = row.username
            item["created_at"] = row.created_at.isoformat() if row.created_at else None
            item["author"] = {
                "user_id": row.author_id,
                "username": row.username,
            }
        else:
            item["hashtag_id"] = row.entity_id
            item["name"] = row.name
            item["tweet_count"] = int(row.tweet_count) if row.tweet_count else 0

        items.append(item)

    return items, next_cursor


def _encode_search_cursor(
    score: float, result_type: str, entity_id: str, ref_time: datetime | None = None
) -> str:
    payload = {
        "score": score,
        "type": result_type,
        "id": entity_id,
        "ref": ref_time.isoformat() if ref_time else None,
    }
    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def _decode_search_cursor(cursor: str) -> tuple | None:
    try:
        data = json.loads(base64.b64decode(cursor.encode()).decode())
        ref_time = None
        if "ref" in data and data["ref"]:
            ref_time = datetime.fromisoformat(data["ref"])
        return (float(data["score"]), data["type"], data["id"], ref_time)
    except Exception:
        return None
