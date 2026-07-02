# Twitter/X MVP — Design & Module Layout

An MVP real-time social platform backend that implements the core Twitter posting and timeline loop. One FastAPI process serves REST endpoints backed by PostgreSQL for durable storage and Redis for timeline caching and trending computation. The MVP covers tweet posting with async fan-out, follower-based home timelines, user profile timelines, full-text search, follow/unfollow with idempotency, and velocity-based trending topics — minus media uploads, Kafka event streaming, celebrity push/pull fan-out, Earlybird search, Snowflake IDs, and authentication.

The broader target — the full Twitter/X System Design — scales this to 330M MAU with a hybrid push/pull fan-out (1M follower threshold), Earlybird per-partition in-memory inverted index for real-time search, Kafka for async fan-out decoupling, Snowflake IDs for chronological sort without a timestamp column, and MySQL + Manhattan KV for hot/cold storage tiering. This MVP implements the tweet→timeline→search→trends spine that everything else attaches to.

## Architecture

```mermaid
graph TB
    subgraph api["FastAPI App — port 8000"]
        R_TWEETS[Tweets Router<br/>POST /api/v1/tweets]
        R_TIMELINE[Timeline Router<br/>GET /api/v1/timeline/home]
        R_USERS[Users Router<br/>GET /api/v1/users/:id/tweets<br/>POST|DELETE /api/v1/users/:id/follow]
        R_SEARCH[Search Router<br/>GET /api/v1/search]
        R_TRENDS[Trends Router<br/>GET /api/v1/trends]
    end

    subgraph services["Service Layer"]
        TS[TweetService<br/>create, hashtag extraction, fan-out dispatch]
        TLS[TimelineService<br/>sorted-set merge, cursor pagination]
        US[UserService<br/>CRUD, follow/unfollow, counter updates]
        SS[SearchService<br/>FTS tsquery builder, ranked merge]
        TRS[TrendingService<br/>velocity scoring, windowed ZSET merge]
    end

    subgraph data["Data Layer"]
        PG[(PostgreSQL 16<br/>users, tweets, hashtags,<br/>tweet_hashtags, follows<br/>+ GIN FTS indexes)]
        RD[(Redis<br/>timeline:{user_id} sorted sets<br/>trends:{window} sorted sets<br/>counters:{user_id} hashes)]
    end

    subgraph async["Background (in-process)"]
        FO[Fan-out Worker<br/>asyncio task: 500ms poll<br/>writes to Redis timeline ZSETs]
        TW[Trending Worker<br/>asyncio task: 60s poll<br/>computes velocity scores]
    end

    R_TWEETS --> TS
    R_TIMELINE --> TLS
    R_USERS --> US
    R_SEARCH --> SS
    R_TRENDS --> TRS
    TS --> PG
    TS --> FO
    TLS --> RD
    TLS --> PG
    US --> PG
    US --> RD
    SS --> PG
    TRS --> RD
    TRS --> PG
    FO --> PG
    FO --> RD
    TW --> PG
    TW --> RD

    classDef rt fill:#d0ebff,stroke:#1c7ed6,color:#1a1a1a
    classDef svc fill:#ffe8cc,stroke:#e8590c,color:#1a1a1a
    classDef store fill:#d3f9d8,stroke:#2f9e44,color:#1a1a1a
    classDef cache fill:#fff3bf,stroke:#f08c00,color:#1a1a1a
    classDef async fill:#f3d9fa,stroke:#9c36b5,color:#1a1a1a

    class R_TWEETS,R_TIMELINE,R_USERS,R_SEARCH,R_TRENDS rt
    class TS,TLS,US,SS,TRS svc
    class PG store
    class RD cache
    class FO,TW async
```

Routers parse HTTP, validate with Pydantic, and delegate to services — no business logic. Services own the domain logic and data access. Redis caches pre-computed timelines per user as sorted sets and trending topic velocity scores; all authoritiative state lives in Postgres. Fan-out and trending computation run as in-process background `asyncio` tasks — no separate worker containers at MVP scale.

## Scope

### In scope

- FR1: Post a tweet with text (max 280 chars) and optional hashtags
- FR2: View a home timeline of tweets from followed users, cursor-paginated (20 tweets/page)
- FR3: View a user's profile timeline, reverse-chronological, cursor-paginated
- FR4: Search tweets by keyword and hashtag with relevance ranking
- FR5: Follow/unfollow other users with idempotency and counter updates
- FR6: Return trending topics with velocity-based scoring over 1h and 24h windows
- GET /healthz
- POST /api/v1/users (MVP setup — no auth, create user via API)

### Out of scope

- Media uploads (images, video, GIFs) — text-only tweets
- Kafka / event streaming (fan-out is in-process async)
- Celebrity push/pull fan-out (all users are "regular" — push to all followers)
- Earlybird / real-time inverted index (Postgres FTS with GIN index)
- Snowflake IDs (UUIDs for tweet_id)
- Soft deletes / tweet deletion
- Authentication / authorization (user_id passed as query param)
- DMs, Spaces, X Premium, monetization
- Multi-device sync / push notifications
- Rate limiting beyond basic request validation

## Data Model

```sql
User {
  user_id:          uuid PK
  username:         text UNIQUE           ← max 15 chars
  display_name:     text
  follower_count:   integer DEFAULT 0     ← denormalized
  following_count:  integer DEFAULT 0     ← denormalized
  created_at:       timestamp
}

Tweet {
  tweet_id:      uuid PK
  author_id:     uuid FK → User
  text:          text                     ← max 280 chars
  created_at:    timestamp
}

Hashtag {
  hashtag_id:  uuid PK
  name:        text UNIQUE               ← lowercased, without # prefix
}

TweetHashtag {
  tweet_id:   uuid PK FK → Tweet
  hashtag_id: uuid PK FK → Hashtag
}

Follow {
  follower_id:  uuid PK FK → User
  followee_id:  uuid PK FK → User
  created_at:   timestamp
  UNIQUE(follower_id, followee_id)       ← idempotent follow
}
```

### Key schema decisions

- **`Follow` has `UNIQUE(follower_id, followee_id)`** — the follow endpoint is idempotent. A duplicate follow returns 200. Unfollow deletes the row. No celebrity threshold in MVP — all follows trigger fan-out pre-population equally.
- **`follower_count` and `following_count` on User are denormalized.** In the MVP, the service layer increments/decrements them synchronously within the follow/unfollow transaction. The full design would use async Kafka consumers; MVP trades eventual consistency for simplicity.
- **No `TimelineEntry` table.** The fan-out is Redis-native: each user's timeline is a sorted set `timeline:{user_id}` with score = `created_at` epoch, value = `tweet_id`. If Redis is cold (cache miss), the TimelineService falls back to a Postgres query: `SELECT * FROM tweets WHERE author_id IN (SELECT followee_id FROM follows WHERE follower_id = $1) ORDER BY created_at DESC LIMIT 50`. This avoids the write amplification of a fan-out table while keeping reads fast.
- **Hashtags are extracted at tweet creation time** via regex (`#\w+`). The TweetService upserts hashtag rows (lookup-or-create) and writes TweetHashtag join rows. Hashtag names are lowercased and stored without the `#` prefix.
- **FTS uses a Postgres generated `tsvector` column** on `tweets` (text) and `hashtags` (name), both indexed with GIN. Search UNIONs results from tweet text match and hashtag name match, ranked by `ts_rank` with a recency decay.
- **Trending uses Redis sorted sets** keyed by time window: `trends:1h` and `trends:24h`. The TrendingWorker (60s poll) counts hashtag occurrences in the window, computes velocity score = `count_recent / count_prior`, and updates the sorted set. `GET /trends` reads the top N from the active window's ZSET.

### Redis key schema

| Key pattern | Type | Value | Score |
|---|---|---|---|
| `timeline:{user_id}` | ZSET | `tweet_id` | `created_at` epoch (float) |
| `trends:{window}` | ZSET | hashtag `name` | velocity score |
| `counters:{user_id}` | HASH | `follower_count`, `following_count` | — |

## API Spec

### GET /healthz
Returns `200 {"status": "ok"}` when the app is alive. Used by compose healthcheck and e2e READY probe.

### POST /api/v1/users
Body: `{username, display_name?}`
Creates a user. Username must be unique, max 15 chars.
Response: `201 {user_id, username, display_name, follower_count: 0, following_count: 0, created_at}`
Errors: `409` if username taken. `422` if username empty or > 15 chars.

### GET /api/v1/users/{user_id}
Returns the user profile with follower/following counts.
Response: `200 {user_id, username, display_name, follower_count, following_count, created_at}`
Errors: `404` if not found.

### POST /api/v1/tweets
Body: `{author_id, text, hashtags?: [string]}`
Creates a tweet. Hashtag names are extracted from text via regex AND from the optional `hashtags` field (client-supplied). Hashtags are upserted (lookup-or-create). Triggers async fan-out to all followers' Redis timeline ZSETs via the FanOutWorker.
Response: `201 {tweet_id, author_id, text, hashtags: [{hashtag_id, name}], created_at}`
Errors: `404` if author_id unknown. `422` if text empty or > 280 chars.

### GET /api/v1/tweets/{tweet_id}
Tweet detail with author and hashtags.
Response: `200 {tweet_id, text, author: {user_id, username, display_name}, hashtags: [{hashtag_id, name}], created_at}`
Errors: `404` if not found.

### GET /api/v1/timeline/home?user_id=<uuid>&cursor=<token>
Home timeline for a user — tweets from all followed users, reverse-chronological, cursor-paginated (20 tweets/page). Reads from Redis `timeline:{user_id}` sorted set; falls back to Postgres query if Redis is cold. Cursor encodes `(created_at, tweet_id)` as base64 JSON.
Response: `200 {tweets: [{tweet_id, text, author: {user_id, username, display_name}, hashtags: [{hashtag_id, name}], created_at}, ...], next_cursor: <token>|null}`
Errors: `404` if user not found. `400` if cursor malformed.

### GET /api/v1/users/{user_id}/tweets?cursor=<token>
User's profile timeline — their own tweets, reverse-chronological, cursor-paginated (20 tweets/page). Direct Postgres query on `tweets WHERE author_id = $1 ORDER BY created_at DESC`.
Response: `200 {tweets: [{tweet_id, text, hashtags: [{hashtag_id, name}], created_at}, ...], next_cursor: <token>|null}`
Errors: `404` if user not found. `400` if cursor malformed.

### POST /api/v1/users/{followee_id}/follow?follower_id=<uuid>
Follow a user. Idempotent — if already following, returns 200. Increments `follower_count` on followee and `following_count` on follower. Triggers pre-population of the follower's timeline with the followee's recent tweets.
Response: `200 {"status": "following"}`
Errors: `404` if followee or follower not found. `422` if trying to follow self.

### DELETE /api/v1/users/{followee_id}/follow?follower_id=<uuid>
Unfollow a user. Idempotent — if not following, still returns 200. Decrements counters.
Response: `200 {"status": "unfollowed"}`
Errors: `404` if followee or follower not found.

### GET /api/v1/search?q=<query>&cursor=<token>
Full-text search across tweet text and hashtag names. Uses Postgres `websearch_to_tsquery` with GIN-indexed tsvector columns. Results ranked by `ts_rank` with recency decay. Cursor pagination (20 results/page).
Response: `200 {results: [{type: "tweet"|"hashtag", tweet_id?, text?, hashtag_id?, name?, author?: {user_id, username}, created_at?, score}, ...], next_cursor: <token>|null}`
Errors: `400` if cursor malformed. Empty query returns empty results (200).

### GET /api/v1/trends?window=1h|24h&limit=10
Current trending topics. Returns top-N hashtags by velocity score from Redis sorted set. Window parameter selects the active time bucket (default: `1h`).
Response: `200 {trends: [{hashtag_id, name, velocity_score, tweet_count}, ...], window: "1h"}`
Errors: `422` if window parameter invalid.

## High-Level Design — per-FR flows

### FR1: Post a tweet

**Components:** Client → Tweets Router → TweetService → Postgres + FanOutWorker (async).

**Flow:**
1. Client calls `POST /api/v1/tweets` with `{author_id, text, hashtags?}`.
2. Router validates the request: text length 1–280, author_id is a valid UUID.
3. TweetService verifies author exists (404 if not). Extracts hashtags from text via regex `#(\w+)` and merges with client-supplied `hashtags` array (deduped, lowercased).
4. Inside a DB transaction: inserts `Tweet` row, upserts `Hashtag` rows (`INSERT ... ON CONFLICT (name) DO NOTHING RETURNING *`), inserts `TweetHashtag` join rows.
5. Returns `201` with the tweet + hashtags immediately.
6. After responding, dispatches a fan-out task to the FanOutWorker: `{author_id, tweet_id, created_at}`. The POST handler does NOT block on fan-out completion — it returns in <10ms (single-row insert + hashtag upsert).

### FR2: View home timeline

**Components:** Client → Timeline Router → TimelineService → Redis + Postgres.

**Flow:**
1. Client calls `GET /api/v1/timeline/home?user_id=<uuid>&cursor=<token>`.
2. TimelineService attempts Redis read: `ZREVRANGE timeline:{user_id} <cursor_score> -inf BYSCORE LIMIT 0 21` (fetch 21 to detect has-more). Score is `created_at` epoch. If Redis returns results → hydrate tweets from Postgres in a single `SELECT WHERE tweet_id IN (...)` query, sort by score, return page.
3. If Redis is cold (empty set or Redis unavailable): fall back to Postgres query:

```sql
SELECT t.* FROM tweets t
JOIN follows f ON t.author_id = f.followee_id
WHERE f.follower_id = $1
ORDER BY t.created_at DESC
LIMIT 21
```

4. Cursor encodes the last tweet's `(created_at, tweet_id)` as base64 JSON. If 21 results returned, `next_cursor` is set; otherwise `null`.

### FR3: View profile timeline

**Components:** Client → Users Router → UserService → Postgres.

**Flow:**
1. Client calls `GET /api/v1/users/{user_id}/tweets?cursor=<token>`.
2. UserService verifies user exists (404 if not).
3. Queries:

```sql
SELECT * FROM tweets
WHERE author_id = $1
  AND (created_at, tweet_id) < ($2, $3)
ORDER BY created_at DESC, tweet_id DESC
LIMIT 21
```

4. Joins hashtags via TweetHashtag → Hashtag. Returns paginated response with cursor.

### FR4: Search tweets

**Components:** Client → Search Router → SearchService → Postgres (FTS).

**Flow:**
1. Client calls `GET /api/v1/search?q=<query>&cursor=<token>`.
2. SearchService converts query to tsquery via `websearch_to_tsquery` (supports quoted phrases, OR logic).
3. UNIONs two sub-queries:

```sql
-- Tweet text match
SELECT 'tweet' as type, t.tweet_id, t.text, t.created_at,
       ts_rank(t.fts_vector, query) * recency_decay(t.created_at) as score
FROM tweets t, to_tsquery('english', $1) query
WHERE t.fts_vector @@ query

UNION ALL

-- Hashtag name match
SELECT 'hashtag' as type, NULL as tweet_id, h.name as text, NULL as created_at,
       ts_rank(h.fts_vector, query) as score
FROM hashtags h, to_tsquery('english', $1) query
WHERE h.fts_vector @@ query

ORDER BY score DESC
LIMIT 21
```

4. Cursor encodes `(score, type, tweet_id_or_hashtag_id)`. Returns 20 results + next_cursor.

### FR5: Follow/unfollow

**Components:** Client → Users Router → UserService → Postgres + Redis.

**Flow:**
1. Client calls `POST /api/v1/users/{followee_id}/follow?follower_id=<uuid>`.
2. UserService verifies both users exist. Rejects self-follow (422).
3. Inside a DB transaction: inserts `Follow` row (catches `IntegrityError` for duplicate → returns 200 with current counters). Increments `follower_count` on followee, `following_count` on follower.
4. After commit: pre-populates the follower's Redis timeline with the followee's last 50 tweets (`ZADD timeline:{follower_id} {created_at} {tweet_id}` × 50). This is fire-and-forget — if Redis is down, the timeline will populate on demand via Postgres fallback.
5. Returns `200 {"status": "following"}`.

**Unfollow:**
1. `DELETE /api/v1/users/{followee_id}/follow?follower_id=<uuid>`.
2. Deletes the Follow row (idempotent — no-op if not following). Decrements counters.
3. Removes followee's tweets from the follower's Redis timeline: `ZREM timeline:{follower_id}` for all tweet_ids authored by followee.
4. Returns `200 {"status": "unfollowed"}`.

### FR6: Trending topics

**Components:** Client → Trends Router → TrendingService → Redis + Postgres.

**Flow:**
1. Client calls `GET /api/v1/trends?window=1h&limit=10`.
2. TrendingService reads top-N from Redis: `ZREVRANGE trends:{window} 0 {limit-1} WITHSCORES`.
3. Returns `{trends: [{hashtag_id, name, velocity_score, tweet_count}], window}`.

**Background computation** (TrendingWorker, 60s poll):
1. For each window (1h, 24h): counts hashtag occurrences in `[now - 2*window, now - window]` (baseline) and `[now - window, now]` (recent) via Postgres.
2. Velocity score: `score = count_recent / max(count_baseline, 1) * log(1 + count_recent)`. The log factor ensures large absolute counts don't drown out fast-rising topics.
3. Updates Redis: `ZADD trends:{window} {score} {hashtag_name}`.

## Key Design Decisions

### D1: In-process fan-out vs. Kafka worker

**Decision:** Background `asyncio` task in the FastAPI process, polling a `fanout_queue` Redis list every 500ms.

At MVP scale (dozens of users, hundreds of tweets), Kafka is overkill. The fan-out worker runs in the same process: `BRPOP fanout_queue 0.5` → for each follower, `ZADD timeline:{follower_id} {created_at} {tweet_id}`. A tweet from a user with 200 followers completes fan-out in ~20ms of Redis pipelined writes.

**Trade-off:** No durability for the fan-out queue — if the process crashes before the worker picks up the task, followers miss the tweet in their cached timeline. The Postgres fallback (FR2 cold-cache query) means the tweet is still visible, just served slower until the cache warms. At production scale (100M followers), this would be unacceptable — Kafka provides the durability guarantee and decouples fan-out from the POST path. For MVP, the simplicity of one process outweighs the edge-case staleness.

### D2: Redis-native timelines vs. TimelineEntry table

**Decision:** Skip the `TimelineEntry` table. Primary timeline store is Redis sorted set `timeline:{user_id}`; Postgres is the cold-cache fallback.

The Notion design uses a TimelineEntry table for durability, with Redis as a read cache. But TimelineEntry at 330M MAU generates enormous write amplification — every tweet from a 100M-follower account writes 100M rows. For MVP with dozens of users, the Redis-native approach avoids a whole table + index + migration. The Postgres fallback query reconstructs the timeline on demand: JOIN follows → tweets WHERE author_id IN (...).

**Trade-off:** If Redis is wiped (restart without persistence), all cached timelines are lost. Recovery is automatic — the next timeline request hits Postgres and repopulates. This is acceptable for MVP; production would use Redis persistence (AOF) and a TimelineEntry table as the system of record.

### D3: Postgres FTS vs. Elasticsearch

**Decision:** Postgres `tsvector` generated column + GIN index on `tweets.text` and `hashtags.name`. `websearch_to_tsquery` for user-friendly query parsing.

The full design uses Earlybird — a custom per-partition in-memory inverted index capable of single-second freshness at 20K writes/s. That requires ~100 index nodes, custom C++ indexing, and Kafka ingestion. For MVP with thousands of tweets, Postgres FTS handles keyword and hashtag search with zero additional infrastructure. The GIN index supports prefix matching and ranked retrieval; `ts_rank` with recency decay provides reasonable relevance ordering.

**Trade-off:** Postgres FTS lacks real-time indexing (the tsvector is updated on INSERT but GIN is not real-time-optimized), doesn't support typo-tolerance, and its scoring is TF-IDF-based rather than the custom formula Earlybird uses. At MVP scale with <10K tweets, these differences are invisible.

### D4: UUIDs vs. Snowflake IDs

**Decision:** UUIDv4 for all primary keys (`user_id`, `tweet_id`). No Snowflake-style timestamp-encoded IDs.

The full design uses Snowflake IDs: 64-bit, monotonically increasing, embedding a timestamp for chronological sort without a separate column, and a worker ID for no-collision partitioning. Snowflake requires an ID generation service or library (Twitter's snowflake, Instagram's sharding ID). For MVP, UUIDs are simpler — no coordination, no clock synchronization, and Postgres sorts by `created_at` anyway.

**Trade-off:** UUIDs are 128-bit vs. Snowflake's 64-bit — larger Redis ZSET values. At MVP scale this is negligible. UUIDs are also random, not monotonic, so `ORDER BY tweet_id` doesn't give chronological order — but we always sort by `created_at` explicitly.

### D5: Trending — velocity scoring vs. simple count

**Decision:** Velocity-based scoring: `score = count_recent / max(count_baseline, 1) * log(1 + count_recent)`. Two overlapping windows: 1h (responsive) and 24h (stable).

A simple count (`SELECT name, COUNT(*) ... GROUP BY ... ORDER BY count DESC LIMIT 10`) would always return the most-used hashtags — `#news` would dominate forever. Velocity scoring surfaces a topic that went from 10 mentions/hour to 500 — a spike. The log factor ensures a topic with 1M baseline mentions doesn't get infinite score if it doubles to 2M (that's noise, not a trend).

**Trade-off:** Computing velocity requires counting tweets in two time windows, which is a range scan on `tweet_hashtags.created_at`. At 600M tweets/day this would need a streaming pipeline (Kafka + Flink). At MVP scale the 60s Postgres query is ~10ms.

### D6: Cursor pagination — `(created_at, tweet_id)` vs. offset

**Decision:** Opaque base64-encoded JSON cursor containing `{created_at: iso8601, tweet_id: uuid}` for timelines, `{score: float, type: string, id: uuid}` for search. Client passes the token back; service decodes and uses it as a WHERE anchor.

Offset pagination (`OFFSET 40 LIMIT 20`) scans and discards rows — O(N) per page. Cursor pagination uses a composite index seek: `WHERE (created_at, tweet_id) < ($1, $2) ORDER BY created_at DESC, tweet_id DESC LIMIT 20` — O(log N) regardless of depth. Essential for a feed scrolled dozens of pages deep.

## Module Layout

```
src/twitter_x/
├── __init__.py
├── main.py                 # create_app() factory, lifespan (starts fanout + trending workers), /healthz
├── config.py               # Settings (pydantic-settings, env-driven)
├── database.py             # async engine/session factory (Postgres), get_session dependency
├── redis.py                # async Redis client, get_redis dependency
├── models/
│   ├── __init__.py
│   ├── user.py             # User ORM model
│   ├── tweet.py            # Tweet ORM model + FTS tsvector generated column
│   ├── hashtag.py          # Hashtag, TweetHashtag ORM models + FTS tsvector
│   └── follow.py           # Follow ORM model
├── schemas/
│   ├── __init__.py
│   ├── user.py             # UserCreate, UserResponse
│   ├── tweet.py            # TweetCreate, TweetResponse, TweetDetail
│   ├── timeline.py         # TimelineResponse, TimelineItem, CursorToken
│   ├── search.py           # SearchResponse, SearchResult
│   ├── trends.py           # TrendsResponse, TrendItem
│   └── common.py           # PaginatedResponse, Cursor helpers
├── routers/
│   ├── __init__.py
│   ├── health.py           # GET /healthz
│   ├── users.py            # POST /api/v1/users, GET /api/v1/users/{id}, GET /api/v1/users/{id}/tweets, POST|DELETE /api/v1/users/{id}/follow
│   ├── tweets.py           # POST /api/v1/tweets, GET /api/v1/tweets/{id}
│   ├── timeline.py         # GET /api/v1/timeline/home
│   ├── search.py           # GET /api/v1/search
│   └── trends.py           # GET /api/v1/trends
├── services/
│   ├── __init__.py
│   ├── user_service.py     # User CRUD, follow/unfollow with counter updates, timeline pre-population
│   ├── tweet_service.py    # Tweet create with hashtag extraction/upsert, fan-out dispatch
│   ├── timeline_service.py # Redis ZSET read + Postgres fallback, cursor encode/decode
│   ├── search_service.py   # FTS query builder (websearch_to_tsquery, UNION, ts_rank, recency decay)
│   └── trending_service.py # Velocity scorer, windowed count queries, Redis ZSET update
└── workers/
    ├── __init__.py
    ├── fanout_worker.py    # Background asyncio task: BRPOP fanout_queue, pipeline ZADD to followers
    └── trending_worker.py  # Background asyncio task: compute velocity scores every 60s
```

## Build Plan

Each numbered task below is a kanban card for the build phase. The architect has already produced `design.md`, `verify/acceptance/`, and `verify/manifest.env` — the chain picks up at task 1.

### Tier: senior

1. **Scaffold project skeleton** — `pyproject.toml`, `src/twitter_x/` package, `config.py`, `database.py`, `redis.py`, `main.py` with `create_app()` + `/healthz` + lifespan (starts fanout and trending worker stubs), `.env.example`, `.gitignore`. App boots and `/healthz` returns 200.

2. **FR5 — User CRUD + follow/unfollow** — `models/user.py`, `models/follow.py`, `schemas/user.py`, `services/user_service.py`, `routers/users.py`. User create with unique username (409 on conflict), follow/unfollow with idempotency (UNIQUE constraint) and counter updates, profile endpoint with follower/following counts.

3. **FR3 — Profile timeline** — Extends `routers/users.py`: `GET /api/v1/users/{id}/tweets` with cursor pagination. Direct Postgres query on tweets by author_id. Joins hashtags. Cursor encodes `(created_at, tweet_id)`.

4. **FR6 — Trending topics** — `services/trending_service.py`, `workers/trending_worker.py`, `routers/trends.py`, `schemas/trends.py`. Velocity scoring with 1h and 24h windows, Redis ZSET storage, `GET /api/v1/trends` endpoint with window parameter.

5. **Seed data fixtures** — Alembic migration or standalone seed script that creates: ~10 users with cross-follows, ~50 tweets with varied hashtags across ~15 unique hashtags, tweets spread over 24h to exercise trending velocity. Follow graph: each user follows 3-5 others to populate timelines.

6. **Docker, Compose & Deploy** — Multi-stage `Dockerfile` (python:3.12-slim), `docker-compose.yml` with `db` (Postgres 16) + `redis` + `app` services, healthchecks on all three, `APP_PORT` override. `DEPLOY.md` with first-run instructions.

7. **White-box tests** — `tests/conftest.py` + per-service test files under `tests/`. Cover: tweet creation with hashtag extraction, follow idempotency + counter updates, timeline cursor encode/decode, Redis ZSET fallback to Postgres, FTS query building with ts_rank + recency decay, trending velocity score computation.

8. **README + docs** — `README.md` (stack, quick start, API table), `docs/system-design.md` (the full target design from Notion), `docs/mvp-scope.md` (this exact cut).

### Tier: staff

9. **Data model & Alembic initial migration** — All ORM models: User, Tweet, Hashtag, TweetHashtag, Follow. All constraints (FKs, UNIQUE on username, UNIQUE on follower_id+followee_id, UNIQUE on hashtag name). GIN indexes on `tweets.fts_vector` and `hashtags.fts_vector` (generated tsvector columns). Alembic `001_initial` migration that creates every table + index. This is the foundation every other task builds on.

10. **FR1 — Tweet creation with fan-out dispatch** — `models/tweet.py`, `models/hashtag.py`, `schemas/tweet.py`, `services/tweet_service.py`, `routers/tweets.py`. Tweet create with hashtag extraction (regex) + upsert, fan-out task dispatch to Redis queue. Tweet detail endpoint with author + hashtags.

11. **FR2 — Home timeline** — `services/timeline_service.py`, `workers/fanout_worker.py`, `routers/timeline.py`, `schemas/timeline.py`. Redis ZSET read (`timeline:{user_id}`) with Postgres fallback query. Cursor encode/decode with `(created_at, tweet_id)`. FanOutWorker: `BRPOP fanout_queue` → `ZADD timeline:{follower_id}` for all followers. Follow pre-population: backfill last 50 tweets on new follow.

12. **FR4 — Full-text search** — `services/search_service.py`, `routers/search.py`, `schemas/search.py`. `websearch_to_tsquery`, UNION across tweet tsvector + hashtag tsvector, ts_rank ordering with recency decay. Cursor pagination with `(score, type, id)`.

## Acceptance Tests

The `verify/acceptance/` directory contains one executable black-box test file per functional requirement. All tests talk to the running system at `API_BASE_URL` via `httpx` — no app imports. Created as part of this architect card.

| File | FR | What it asserts |
|---|---|---|
| `test_healthz.py` | Health | GET /healthz → 200 |
| `test_fr1_post_tweet.py` | FR1 | Tweet create → 201 with hashtags extracted; detail → 200; 404 on unknown author; 422 on empty/long text; hashtag reuse deduplicates |
| `test_fr2_home_timeline.py` | FR2 | Timeline returns tweets from followed users (not unfollowed), reverse-chronological, cursor pagination works (20/page), empty timeline for new user, 404 for unknown user |
| `test_fr3_profile_timeline.py` | FR3 | Profile timeline returns only that user's tweets, reverse-chronological, cursor pagination, 404 for unknown user |
| `test_fr4_search.py` | FR4 | Search by keyword finds matching tweets, search by hashtag finds tweets with that hashtag, ts_rank ordering (relevant first), empty query → empty results, cursor pagination |
| `test_fr5_follow.py` | FR5 | Follow → 200 + counter increments, unfollow → 200 + counter decrements, duplicate follow idempotent, self-follow → 422, 404 for unknown users; after follow, timeline includes followee's tweets |
| `test_fr6_trending.py` | FR6 | GET /api/v1/trends returns hashtags with velocity scores, window parameter validation (1h/24h), results ordered by score descending, empty results for cold window, invalid window → 422 |

## Supporting endpoints (not FR-gated, exercised by acceptance test setup)

- `POST /api/v1/users` — create a user → `201`. Duplicate username → `409`. Required by every FR test for setup.
- `GET /api/v1/users/{user_id}` — user profile → `200`. Used by setup helpers to verify user creation.
- `GET /api/v1/tweets/{tweet_id}` — tweet detail → `200`. Used by timeline/search tests to verify tweet existence.

## Conformance to MVP Standards

| # | Standard | Status |
|---|----------|--------|
| 1 | `src/<pkg>/` layout | ✅ `src/twitter_x/` planned |
| 2 | routers/services/models/schemas layering | ✅ |
| 3 | app factory + lifespan + `/healthz` | ✅ |
| 4 | `pydantic-settings` config | ✅ |
| 5 | `pyproject.toml` + dev extras | ✅ planned |
| 6 | Alembic migrations | ✅ planned |
| 7 | Multi-stage Dockerfile, py3.12 | ✅ planned |
| 8 | Compose: `db`/`redis`/`app` names, `APP_PORT`, healthcheck | ✅ planned |
| 9 | per-FR acceptance `test_fr<N>_*` | ✅ 7 files (delivered by architect) |
| 10 | `docs/{system-design,mvp-scope,synthesis}.md` | ✅ planned |
| 11 | `DEPLOY.md` | ✅ planned |
| 12 | `.gitignore`, no committed artifacts/`.env` | ✅ planned |
| 13 | env-agnostic product code | ✅ planned |
