# Twitter/X MVP — Design Document

A real-time social platform backend implementing the core Twitter posting, timeline, search, and trending loop. Serves REST endpoints via FastAPI backed by PostgreSQL for durable storage and Redis for timeline caching, fan-out dispatch, and trending computation.

---

## Scope

### In scope (functional requirements)

| # | Requirement | Implementation |
|---|-------------|---------------|
| FR1 | Post a tweet with text (max 280 chars) and optional hashtags | [`routers/tweets.py`](../src/twitter_x/routers/tweets.py) — Pydantic-validated, regex hashtag extraction + upsert |
| FR2 | Home timeline of tweets from followed users, cursor-paginated (20/page) | [`routers/timeline.py`](../src/twitter_x/routers/timeline.py) — Redis ZSET + Postgres fallback |
| FR3 | Profile timeline of a user's own tweets, cursor-paginated | [`routers/users.py`](../src/twitter_x/routers/users.py) — `GET /api/v1/users/{id}/tweets` |
| FR4 | Full-text search across tweets and hashtags with relevance ranking | [`routers/search.py`](../src/twitter_x/routers/search.py) — `websearch_to_tsquery` + GIN-indexed tsvector |
| FR5 | Follow/unfollow with idempotency and denormalized counter updates | [`routers/users.py`](../src/twitter_x/routers/users.py) — UNIQUE constraint, synchronous counter increments |
| FR6 | Velocity-based trending topics over 1h and 24h windows | [`workers/trending_worker.py`](../src/twitter_x/workers/trending_worker.py) — score = (recent / baseline) × log(1 + recent) |
| — | User CRUD for MVP setup (no auth) | [`routers/users.py`](../src/twitter_x/routers/users.py) — `POST /api/v1/users` |
| — | Health check | [`main.py`](../src/twitter_x/main.py) — `GET /healthz` → `{"status":"ok"}` |

### Out of scope

Media uploads, Kafka / event streaming, celebrity push/pull fan-out, Earlybird real-time inverted index, Snowflake IDs, tweet deletion / soft deletes, authentication / authorization, DMs, Spaces, X Premium, rate limiting, multi-device sync.

---

## Architecture

```mermaid
graph TB
    subgraph api["FastAPI — port 8000"]
        RT[Tweets Router<br/>POST /api/v1/tweets]
        RL[Home Timeline Router<br/>GET /api/v1/timeline/home]
        RU[Users Router<br/>GET /api/v1/users/:id/tweets<br/>POST|DELETE follow]
        RS[Search Router<br/>GET /api/v1/search]
        RTR[Trends Router<br/>GET /api/v1/trends]
    end

    subgraph svc["Service Layer"]
        TS[TweetService<br/>create + hashtag extraction + fan-out dispatch]
        TLS[TimelineService<br/>Redis ZSET read, Postgres fallback, cursor pagination]
        US[UserService<br/>CRUD, follow/unfollow, counter updates, timeline backfill]
        SS[SearchService<br/>websearch_to_tsquery, ranked UNION, recency decay]
        TRS[TrendingService<br/>velocity scoring, windowed ZSET merge]
    end

    subgraph store["PostgreSQL 16"]
        PG[(users, tweets, hashtags,<br/>tweet_hashtags, follows<br/>+ GIN indexes on fts_vector columns)]
    end

    subgraph cache["Redis 7"]
        RD[(timeline:{user_id} ZSETs<br/>trends:{window} ZSETs<br/>trends:{window}:counts ZSETs<br/>fanout_queue list)]
    end

    subgraph bg["Background asyncio tasks"]
        FO[FanOutWorker<br/>500ms BRPOP → pipeline ZADD to all followers]
        TW[TrendingWorker<br/>60s poll → velocity scores via windowed SQL count]
    end

    RT --> TS
    RL --> TLS
    RU --> US
    RS --> SS
    RTR --> TRS
    TS --> PG
    TS --> FO
    TLS --> RD
    TLS --> PG
    US --> PG
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
    classDef bg fill:#f3d9fa,stroke:#9c36b5,color:#1a1a1a

    class RT,RL,RU,RS,RTR rt
    class TS,TLS,US,SS,TRS svc
    class PG store
    class RD cache
    class FO,TW bg
```

Routers parse HTTP and validate with Pydantic, then delegate to services — routers contain zero business logic. Services own the domain logic and data access. Redis caches pre-computed timelines per user as sorted sets (`timeline:{user_id}`) and trending scores (`trends:{window}`); all authoritative state lives in PostgreSQL. Fan-out and trending computation run as in-process `asyncio` background tasks with no separate worker containers.

---

## Data model

### Entity relationship

```
User
├── user_id:          UUID PK            (uuid.uuid4 default)
├── username:         VARCHAR(15) UNIQUE  (alphanumeric + _-)
├── display_name:     VARCHAR(50)?
├── follower_count:   INTEGER DEFAULT 0   (denormalized)
├── following_count:  INTEGER DEFAULT 0   (denormalized)
├── created_at:       TIMESTAMPTZ         (server_default=func.now())

Tweet
├── tweet_id:      UUID PK
├── author_id:     UUID FK → User
├── text:          VARCHAR(280)
├── fts_vector:    TSVECTOR              (GENERATED ALWAYS AS to_tsvector('english', text) STORED)
├── created_at:    TIMESTAMPTZ            (server_default=func.now())

Hashtag
├── hashtag_id:    UUID PK
├── name:          VARCHAR(50) UNIQUE     (lowercased, without #)
├── fts_vector:    TSVECTOR               (GENERATED ALWAYS AS to_tsvector('english', name) STORED)

TweetHashtag
├── tweet_id:   UUID PK FK → Tweet
├── hashtag_id: UUID PK FK → Hashtag
└── UNIQUE(tweet_id, hashtag_id)

Follow
├── follower_id:  UUID PK FK → User
├── followee_id:  UUID PK FK → User
├── created_at:   TIMESTAMPTZ
└── UNIQUE(follower_id, followee_id)
```

*Sources: [`models/tweet.py`](../src/twitter_x/models/tweet.py), [`models/user.py`](../src/twitter_x/models/user.py), [`models/hashtag.py`](../src/twitter_x/models/hashtag.py), [`models/follow.py`](../src/twitter_x/models/follow.py), [`alembic/versions/001_initial.py`](../alembic/versions/001_initial.py)*

### Redis key schema

| Key pattern | Type | Value | Purpose |
|------------|------|-------|---------|
| `timeline:{user_id}` | ZSET | `tweet_id` → `created_at` epoch | Pre-computed home timeline per user |
| `fanout_queue` | List | JSON payloads `{author_id, tweet_id, created_at}` | Fan-out dispatch queue |
| `trends:{window}` | ZSET | hashtag `name` → `velocity_score` | Top trending topics |
| `trends:{window}:counts` | ZSET | hashtag `name` → `tweet_count` | Tweet count for trend items |

---

## API specification

### `GET /healthz`
Returns `200 {"status":"ok"}`. Used by Docker HEALTHCHECK and compose readiness probes.

### `POST /api/v1/users`
Body: `{username: str, display_name?: str}`
- username: 1–15 chars, alphanumeric + `_-`
- display_name: max 50 chars (optional)
- Returns `201 {user_id, username, display_name, follower_count: 0, following_count: 0, created_at}`
- `409` if username taken, `422` on validation failure

### `GET /api/v1/users/{user_id}`
Returns user profile with follower/following counts. `404` if not found.

### `GET /api/v1/users/{user_id}/tweets?cursor=<token>`
Profile timeline — user's own tweets, reverse-chronological, cursor-paginated (20/page). Cursor encodes `(created_at, tweet_id)` as base64 JSON.
- `404` if user not found, `400` if cursor malformed
- Returns `{tweets: [...], next_cursor: token|null}`

### `POST /api/v1/users/{followee_id}/follow?follower_id=<uuid>`
Follow a user. Idempotent via UNIQUE constraint — duplicate returns 200. Increments denormalized counters and backfills followee's last 50 tweets into follower's Redis timeline.
- `404` if either user not found, `422` if self-follow
- Returns `200 {"status": "following"}`

### `DELETE /api/v1/users/{followee_id}/follow?follower_id=<uuid>`
Unfollow a user. Idempotent — no-op if not following. Decrements counters and removes followee's tweets from follower's Redis timeline.
- `404` if either user not found
- Returns `200 {"status": "unfollowed"}`

### `POST /api/v1/tweets`
Body: `{author_id: uuid, text: str, hashtags?: [str]}`
- text: 1–280 chars. Hashtags extracted from text via `#(\w+)` regex AND merged with client-supplied `hashtags` array (deduped, lowercased)
- Returns `201 {tweet_id, author_id, text, hashtags: [{hashtag_id, name}], created_at}`
- `404` if author unknown, `422` on validation
- After responding: fire-and-forget `LPUSH fanout_queue` with JSON payload

### `GET /api/v1/tweets/{tweet_id}`
Tweet detail with author and hashtags. `404` if not found.

### `GET /api/v1/timeline/home?user_id=<uuid>&cursor=<token>`
Home timeline — tweets from followed users, reverse-chronological, cursor-paginated (20/page).
- Read path: Redis `ZREVRANGEBYSCORE timeline:{user_id}` → hydrate tweets from Postgres `SELECT WHERE tweet_id IN (...)`
- Fallback: Postgres `JOIN follows → tweets WHERE author_id IN (followee_ids) ORDER BY created_at DESC`
- `404` if user not found

### `GET /api/v1/search?q=<query>&cursor=<token>`
Full-text search across tweet text and hashtag names.
- Uses `websearch_to_tsquery('english', q)` for user-friendly query parsing (supports quoted phrases, OR)
- UNIONs: tweet text FTS match + hashtag name FTS match
- Ranked by `ts_rank * recency_decay(created_at)` — descending
- Cursor encodes `(score, type, entity_id)`
- Empty query returns `200 {results: [], next_cursor: null}`

*Source: [`routers/search.py`](../src/twitter_x/routers/search.py) — the raw SQL with CTE + UNION*

### `GET /api/v1/trends?window=1h|24h&limit=<1-50>`
Velocity-ranked trending topics from Redis sorted set.
- Score formula: `count_recent / max(count_baseline, 1) * log(1 + count_recent)`
- Computed every 60s by TrendingWorker, stored in Redis `trends:{window}` ZSET
- `422` if window not in `{1h, 24h}`

---

## Design decisions

### D1: In-process fan-out vs. Kafka worker

**Decision:** Background `asyncio` task in the FastAPI process, polling a `fanout_queue` Redis list every 500ms.

The FanOutWorker ([`workers/fanout_worker.py`](../src/twitter_x/workers/fanout_worker.py)) runs `BRPOP fanout_queue 0.5`, parses the JSON payload, queries Postgres for the author's followers, then pipelines `ZADD timeline:{follower_id}` for each follower. A tweet from a user with 200 followers completes fan-out in ~20ms of Redis pipelined writes.

**Trade-off:** No durability for the fan-out queue. If the process crashes between `LPUSH` and the worker's `BRPOP`/`ZADD`, followers miss the tweet in their cached timeline. The Postgres fallback on the next timeline read (D2) means the tweet is still visible — just served from Postgres until the cache warms. At production scale (100M followers), Kafka would provide durability and decouple fan-out from the POST path. For MVP, one process is simpler and the cold-cache fallback covers the edge case.

### D2: Redis-native timelines vs. TimelineEntry table

**Decision:** Skip the `TimelineEntry` table. The primary timeline store is a Redis sorted set `timeline:{user_id}`; Postgres is the cold-cache fallback.

The home timeline router ([`routers/timeline.py`](../src/twitter_x/routers/timeline.py)) reads from Redis first via `ZREVRANGEBYSCORE`. On a cache hit, it hydrates tweet objects from Postgres via `SELECT WHERE tweet_id IN (...)`. On a miss (Redis unavailable or empty), it falls back to a Postgres query:

```sql
SELECT t.* FROM tweets t
JOIN follows f ON t.author_id = f.followee_id
WHERE f.follower_id = $1
ORDER BY t.created_at DESC
LIMIT 21
```

**Trade-off:** If Redis is wiped (restart without persistence), all cached timelines are lost. Recovery is automatic — the next timeline request hits Postgres and repopulates. Production would use Redis AOF persistence and a TimelineEntry table as the durable system of record, but the MVP's simple architecture avoids a whole table + index + migration.

### D3: Postgres FTS vs. Elasticsearch

**Decision:** Postgres `tsvector` generated column + GIN index on `tweets.text` and `hashtags.name`. `websearch_to_tsquery` for user-friendly query parsing.

The search query ([`routers/search.py`](../src/twitter_x/routers/search.py)) uses a CTE + UNION approach:
1. Tweet text match via GIN-indexed `fts_vector`
2. Hashtag name match via GIN-indexed `fts_vector`
3. Combined results ranked by `ts_rank` with `recency_decay(created_at)` — a PostgreSQL function defined in [`alembic/versions/002_recency_decay.py`](../alembic/versions/002_recency_decay.py)

**Trade-off:** Postgres FTS lacks real-time indexing, typo-tolerance, and Earlybird's custom ranking formula. At MVP scale with <10K tweets, these differences are invisible. Elasticsearch would add operational complexity (JVM heap, cluster management) with zero query quality benefit at this data volume.

### D4: UUIDv4 vs. Snowflake IDs

**Decision:** UUIDv4 for all primary keys. No Snowflake-style timestamp-encoded IDs.

All models use `uuid.uuid4` as default primary key values ([`models/tweet.py`](../src/twitter_x/models/tweet.py), [`models/user.py`](../src/twitter_x/models/user.py)). Postgres stores them as `UUID` type.

**Trade-off:** UUIDs are 128-bit vs. Snowflake's 64-bit — larger in Redis ZSETs and Postgres indexes. UUIDs are random, not monotonic, so `ORDER BY tweet_id` doesn't give chronological order — all queries sort by `created_at` explicitly. At MVP scale, the storage overhead (~50MB for 1M rows) is negligible and the operational simplicity (no ID generation service, no clock synchronization) wins.

### D5: Velocity-based trending vs. simple count aggregation

**Decision:** Velocity scoring: `score = count_recent / max(count_baseline, 1) * log(1 + count_recent)`. Two overlapping windows (1h responsive, 24h stable).

The TrendingWorker ([`workers/trending_worker.py`](../src/twitter_x/workers/trending_worker.py)) runs every 60s: for each window, it counts hashtag occurrences in `[now - 2*window, now - window]` (baseline) and `[now - window, now]` (recent) via Postgres windowed queries, then computes the velocity formula and writes to Redis `trends:{window}` ZSET.

A simple count would always return the most-used hashtags — `#news` would dominate permanently. Velocity scoring surfaces a topic that went from 10 mentions/hour to 500 — a spike. The log factor prevents a topic with 1M baseline mentions from getting infinite score if it doubles to 2M (that's noise, not a trend).

**Trade-off:** Computing velocity requires counting tweets in two time windows, which is a Postgres range scan. At 600M tweets/day this would need a streaming pipeline (Kafka + Flink). At MVP scale the 60s Postgres query completes in ~10ms.

### D6: Cursor pagination vs. offset pagination

**Decision:** Opaque base64-encoded JSON cursor containing `{created_at: iso8601, tweet_id: uuid}` for timelines and `{score: float, type: string, id: string}` for search.

Offset pagination (`OFFSET 40 LIMIT 20`) scans and discards rows — O(N) per page. Cursor pagination uses a composite index seek: `WHERE (created_at, tweet_id) < ($1, $2) ORDER BY created_at DESC, tweet_id DESC LIMIT 20` — O(log N) regardless of depth.

The cursor encode/decode functions are in each router (e.g., [`routers/timeline.py`](../src/twitter_x/routers/timeline.py#L26-L42)). They use `json.dumps(separators=(",", ":"))` + `b64encode` to keep cursors compact (~80 bytes each).

---

## Background workers

### FanOutWorker (`workers/fanout_worker.py`)

| Property | Value |
|----------|-------|
| Poll method | `BRPOP fanout_queue` (500ms timeout) |
| Dispatch | Redis pipeline — `ZADD timeline:{fid}` for each follower |
| Error handling | Silently retries on transient failure (1s cooldown) |
| Startup | Started by `fanout_worker_lifespan()` in `main.py` lifespan |

On a new tweet: author queries followers → pipelines ZADD to each follower's timeline ZSET. If the author has no followers, the worker skips without writing anything.

### TrendingWorker (`workers/trending_worker.py`)

| Property | Value |
|----------|-------|
| Poll interval | 60 seconds |
| Windows | 1h (responsive), 24h (stable) |
| Score formula | `count_recent / max(count_baseline, 1) * log(1 + count_recent)` |
| Storage | Redis `trends:{window}` (velocity) + `trends:{window}:counts` (tweet count) |
| Startup delay | 5s initial sleep for DB/Redis readiness |

---

## Module layout

```
src/twitter_x/
├── __init__.py
├── main.py                  # create_app() factory, lifespan, /healthz
├── config.py                # pydantic-settings, env-driven
├── database.py              # async engine/session factory, get_session dependency
├── redis.py                 # Redis client (graceful init, handles unavailable Redis)
├── models/                  # SQLAlchemy ORM models
│   ├── base.py              # DeclarativeBase
│   ├── user.py              # User — username, display_name, counters, created_at
│   ├── tweet.py             # Tweet — author FK, text, FTS tsvector, created_at
│   ├── hashtag.py           # Hashtag, TweetHashtag — join table with UNIQUE
│   └── follow.py            # Follow — follower_id + followee_id with UNIQUE
├── schemas/                 # Pydantic request/response models
│   ├── user.py              # UserCreate, UserResponse
│   ├── tweet.py             # TweetCreate, TweetResponse, TweetDetail, HashtagItem, TweetAuthor
│   ├── timeline.py          # TimelineItem, TimelineResponse
│   ├── search.py            # SearchResult, SearchResponse
│   ├── trends.py            # TrendItem, TrendsResponse
│   └── common.py            # FollowResponse, CursorToken (base)
├── routers/                 # FastAPI routers (no business logic)
│   ├── health.py            # GET /healthz
│   ├── users.py             # User CRUD + follow/unfollow + profile timeline
│   ├── tweets.py            # Tweet CRUD + fan-out dispatch
│   ├── timeline.py          # Home timeline (Redis + Postgres fallback)
│   ├── search.py            # FTS search (websearch_to_tsquery, ranked UNION)
│   └── trends.py            # Trending topics (Redis ZSET read)
├── services/                # Business-logic services (extraction-ready stubs)
│   ├── user_service.py      # User CRUD, follow/unfollow, timeline backfill
│   ├── tweet_service.py     # Tweet create, hashtag extraction, fan-out dispatch
│   ├── timeline_service.py  # Redis ZSET + Postgres fallback, cursor pagination
│   ├── search_service.py    # FTS query building, ts_rank + recency decay
│   └── trending_service.py  # Velocity scores, windowed count queries
└── workers/                 # Background asyncio tasks
    ├── fanout_worker.py     # 500ms BRPOP → pipeline ZADD to followers
    └── trending_worker.py   # 60s poll → trend computation → Redis ZSET update

verify/
├── manifest.env             # e2e lifecycle contract (UP/DOWN/READY/ACCEPTANCE commands)
└── acceptance/              # Black-box tests, one file per FR
    ├── test_healthz.py
    ├── test_fr1_post_tweet.py
    ├── test_fr2_home_timeline.py
    ├── test_fr3_profile_timeline.py
    ├── test_fr4_search.py
    ├── test_fr5_follow.py
    └── test_fr6_trending.py

tests/
├── test_healthz.py          # White-box unit test (in-memory SQLite, ASGI transport)
├── conftest.py              # Shared fixtures (in-memory SQLite engine + session)
```

---

## CI/CD

Three GitHub Actions workflows in `.github/workflows/`:

| Workflow | File | What it runs | Dependencies |
|----------|------|-------------|-------------|
| **lint** | `lint.yml` | `ruff check` + `ruff format --check` on `src/ tests/ verify/` | Python 3.12, ruff==0.15.20 |
| **ci** | `ci.yml` | Unit tests (Postgres service) + Docker build | Postgres 16-alpine service |
| **functional** | `functional.yml` | `docker compose up` → migrations → acceptance tests → teardown | Docker Compose |

All workflows trigger on PR + push to `main` and a daily scheduled run (`17 13 * * *`).

---

## Source verification

Every claim in this document traces to an artifact in the repository:

| Artifact | Location |
|----------|----------|
| REST API surface | `src/twitter_x/routers/` — 6 files, ~760 lines total |
| Database schema | `src/twitter_x/models/` — 5 ORM models + `alembic/versions/` — 2 migrations |
| FTS implementation | `src/twitter_x/routers/search.py` — raw SQL with `websearch_to_tsquery` + `recency_decay()` |
| Background workers | `src/twitter_x/workers/` — `fanout_worker.py` (83 lines) + `trending_worker.py` (113 lines) |
| White-box tests | `tests/test_healthz.py` — 1 suite, 1 passing |
| Acceptance tests | `verify/acceptance/` — 7 suites, one per FR |
| Docker/Compose | `Dockerfile` (multi-stage, 32 lines) + `docker-compose.yml` (3 services, healthchecks) |
| CI/CD | `.github/workflows/` — 3 YAML files (lint, ci, functional) |
