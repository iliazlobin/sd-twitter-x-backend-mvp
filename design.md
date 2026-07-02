# Twitter/X Backend MVP — Design Document

- **Stack:** FastAPI + PostgreSQL 16 + Redis 7
- **Worker model:** In-process `asyncio` background tasks (FanOutWorker, TrendingWorker)
- **Deployment:** Docker Compose (3 services: `db`, `redis`, `app`)
- **Version:** 0.1.0

A single-process real-time social platform backend: tweet posting with hashtag extraction, home
timeline fan-out via Redis, full-text search with recency-weighted ranking, and velocity-based
trending computation.

---

## Functional requirements

| # | Requirement | Source file | Acceptance suite |
|---|---|---|---|
| FR1 | Post a tweet with text (max 280 chars) and optional hashtags | `routers/tweets.py` → `services/tweet_service.py` | `verify/acceptance/test_fr1_post_tweet.py` (12 cases) |
| FR2 | Home timeline of tweets from followed users, cursor-paginated (20/page) | `routers/timeline.py` → `services/timeline_service.py` | `verify/acceptance/test_fr2_home_timeline.py` (7 cases) |
| FR3 | Profile timeline of a user's own tweets, cursor-paginated | `routers/users.py` → `services/user_service.py` | `verify/acceptance/test_fr3_profile_timeline.py` (5 cases) |
| FR4 | Full-text search across tweets and hashtags with relevance ranking | `routers/search.py` → `services/search_service.py` | `verify/acceptance/test_fr4_search.py` (9 cases) |
| FR5 | Follow/unfollow with idempotency and denormalized counter updates | `routers/users.py` → `services/user_service.py` | `verify/acceptance/test_fr5_follow.py` (9 cases) |
| FR6 | Velocity-based trending topics over 1h and 24h windows | `routers/trends.py` → `services/trending_service.py` + `workers/trending_worker.py` | `verify/acceptance/test_fr6_trending.py` (7 cases) |
| — | User CRUD for MVP setup (no auth) | `routers/users.py` → `services/user_service.py` | `verify/acceptance/test_fr_user_crud.py` (8 cases) |
| — | Health check | `routers/health.py` | `verify/acceptance/test_healthz.py` (1 case) |

**Total: 58 black-box acceptance test cases across 8 suites.**

### Out of scope

Media uploads, Kafka / event streaming, celebrity push/pull fan-out, Earlybird real-time inverted
index, Snowflake IDs, tweet deletion / soft deletes, authentication / authorization, DMs, Spaces,
X Premium, rate limiting, multi-device sync.

---

## Architecture

```mermaid
graph TB
    subgraph api["FastAPI — port 8000"]
        RT["Tweets Router<br/>POST /api/v1/tweets"]
        RL["Home Timeline Router<br/>GET /api/v1/timeline/home"]
        RU["Users Router<br/>GET /api/v1/users/:id/tweets<br/>POST|DELETE follow"]
        RS["Search Router<br/>GET /api/v1/search"]
        RTR["Trends Router<br/>GET /api/v1/trends"]
    end

    subgraph svc["Service Layer"]
        TS["TweetService<br/>create + hashtag extraction + fan-out dispatch"]
        TLS["TimelineService<br/>Redis ZSET read, Postgres fallback, cursor pagination"]
        US["UserService<br/>CRUD, follow/unfollow, counter updates, timeline backfill"]
        SS["SearchService<br/>websearch_to_tsquery, ranked UNION, recency decay"]
        TRS["TrendingService<br/>velocity scoring, windowed ZSET merge"]
    end

    subgraph store["PostgreSQL 16"]
        PG[(users, tweets, hashtags,<br/>tweet_hashtags, follows<br/>+ GIN indexes on fts_vector columns)]
    end

    subgraph cache["Redis 7"]
        RD[(timeline:{user_id} ZSETs<br/>trends:{window} ZSETs<br/>trends:{window}:counts ZSETs<br/>fanout_queue list)]
    end

    subgraph bg["Background asyncio tasks"]
        FO["FanOutWorker<br/>500ms BRPOP → pipeline ZADD to all followers"]
        TW["TrendingWorker<br/>60s poll → velocity scores via windowed SQL count"]
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

**Routers** parse HTTP, validate with Pydantic, and delegate to services — they contain zero business
logic. **Services** own all domain logic and data access. **Redis** caches pre-computed timelines per
user as sorted sets (`timeline:{user_id}`) and trending scores (`trends:{window}`). All authoritative
state lives in PostgreSQL. Fan-out and trending computation run as in-process `asyncio` background
tasks with no separate worker containers.

---

## Data model

### PostgreSQL (5 tables + 1 function)

```
User
├── user_id:          UUID PK DEFAULT gen_random_uuid()
├── username:         VARCHAR(15) UNIQUE NOT NULL   (regex: ^[a-zA-Z0-9_-]+$)
├── display_name:     VARCHAR(50)
├── follower_count:   INTEGER DEFAULT 0             ← denormalized
├── following_count:  INTEGER DEFAULT 0             ← denormalized
├── created_at:       TIMESTAMPTZ DEFAULT now()

Tweet
├── tweet_id:      UUID PK DEFAULT gen_random_uuid()
├── author_id:     UUID NOT NULL FK → User(user_id)
├── text:          VARCHAR(280) NOT NULL
├── fts_vector:    TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
├── created_at:    TIMESTAMPTZ DEFAULT now()

Hashtag
├── hashtag_id:    UUID PK DEFAULT gen_random_uuid()
├── name:          VARCHAR(50) UNIQUE NOT NULL       (lowercased, no # prefix)
├── fts_vector:    TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', name)) STORED

TweetHashtag
├── tweet_id:   UUID FK → Tweet(tweet_id)   PK part
├── hashtag_id: UUID FK → Hashtag(hashtag_id) PK part
└── UNIQUE(tweet_id, hashtag_id)

Follow
├── follower_id:  UUID FK → User(user_id)   PK part
├── followee_id:  UUID FK → User(user_id)   PK part
├── created_at:   TIMESTAMPTZ DEFAULT now()
└── UNIQUE(follower_id, followee_id)
```

**Indexes** (beyond PKs/UNIQUEs):
- `tweets(author_id, created_at DESC)` — profile timeline + timeline fallback
- `tweets(created_at DESC)` — time-range scans
- GIN on `tweets.fts_vector` — full-text search
- GIN on `hashtags.fts_vector` — hashtag name search
- `tweet_hashtags(hashtag_id, tweet_id)` — reverse lookup from hashtag to tweets

**Migration `002_recency_decay.py`** adds a SQL function:
```sql
recency_decay(created_at TIMESTAMPTZ) RETURNS FLOAT
  AS $$ SELECT exp(-EXTRACT(EPOCH FROM ($1 - created_at)) / 86400.0) $$
```
Used in search ranking as `ts_rank(...) * recency_decay(tweet.created_at)` — 24h half-life decay.

### Redis key schema

| Key | Type | Member → Score | Purpose |
|-----|------|----------------|---------|
| `timeline:{user_id}` | ZSET | `tweet_id` → `created_at` epoch (float) | Pre-computed home timeline |
| `fanout_queue` | List | JSON `{author_id, tweet_id, created_at}` | Fan-out dispatch queue |
| `trends:{window}` | ZSET | `hashtag_name` → `velocity_score` | Top trending |
| `trends:{window}:counts` | ZSET | `hashtag_name` → `tweet_count` | Raw count for display |

All Redis keys are cache — loss is survivable (Postgres fallback on next timeline read).

---

## API specification

Every endpoint prefixed `/api/v1` except `/healthz`. All IDs are UUIDv4 (string form in JSON).
All timestamps are ISO 8601.

### `GET /healthz`
```
200  {"status": "ok"}
```
No auth. Used by Docker HEALTHCHECK. Always returns 200 if the process is alive.

### `POST /api/v1/users`
```
→ Body:     {"username": "alice", "display_name"?: "Alice Smith"}
← 201:      {"user_id": "<uuid>", "username": "alice", "display_name": "Alice Smith",
             "follower_count": 0, "following_count": 0, "created_at": "<iso>"}
← 409:      {"detail": "Username already taken"}
← 422:      {"detail": [{"loc": ["body","username"], "msg": "..."}]}
```
username: 1–15 chars, regex `^[a-zA-Z0-9_-]+$`. display_name: max 50 chars, optional.

### `GET /api/v1/users/{user_id}`
```
← 200:      {"user_id": "<uuid>", "username": "alice", "display_name": "Alice Smith",
             "follower_count": N, "following_count": N, "created_at": "<iso>"}
← 404:      {"detail": "User not found"}
```

### `GET /api/v1/users/{user_id}/tweets?cursor=<token>`
Profile timeline — user's own tweets, reverse-chronological, cursor-paginated (20/page).
```
← 200:      {"tweets": [{...tweet...}], "next_cursor": "<token>"|null}
← 404:      {"detail": "User not found"}
← 400:      {"detail": "Invalid cursor"}
```

### `POST /api/v1/users/{followee_id}/follow?follower_id=<uuid>`
```
← 200:      {"status": "following"}
← 404:      {"detail": "User not found"}
← 422:      {"detail": "Cannot follow yourself"}
```
Idempotent via UNIQUE constraint. Increments denormalized counters. Backfills last 50 tweets
into follower's Redis timeline.

### `DELETE /api/v1/users/{followee_id}/follow?follower_id=<uuid>`
```
← 200:      {"status": "unfollowed"}
← 404:      {"detail": "User not found"}
```
Idempotent — no-op if not following. Decrements counters. Removes followee's tweets from
follower's Redis timeline.

### `POST /api/v1/tweets`
```
→ Body:     {"author_id": "<uuid>", "text": "hello #world", "hashtags"?: ["extra"]}
← 201:      {"tweet_id": "<uuid>", "author_id": "<uuid>", "text": "hello #world",
             "hashtags": [{"hashtag_id": "<uuid>", "name": "world"}, ...], "created_at": "<iso>"}
← 404:      {"detail": "Author not found"}
← 422:      {"detail": [{"loc": ["body","text"], "msg": "..."}]}
```
text: 1–280 chars. Hashtags extracted from text via `#(\w+)` regex + merged with client-supplied
`hashtags` array (deduped, lowercased). After responding 201, fire-and-forget `LPUSH fanout_queue`.

### `GET /api/v1/tweets/{tweet_id}`
```
← 200:      {"tweet_id": "<uuid>", "text": "...", "author": {"user_id": "...", "username": "..."},
             "hashtags": [{"hashtag_id": "...", "name": "..."}], "created_at": "<iso>"}
← 404:      {"detail": "Tweet not found"}
```

### `GET /api/v1/timeline/home?user_id=<uuid>&cursor=<token>`
Home timeline — tweets from followed users, reverse-chronological, 20/page.
```
← 200:      {"tweets": [{...tweet with author...}], "next_cursor": "<token>"|null}
← 404:      {"detail": "User not found"}
```
**Read path:** Redis `ZREVRANGEBYSCORE timeline:{user_id}` → hydrate from Postgres
`WHERE tweet_id IN (...)`. On Redis miss: Postgres fallback via
`JOIN follows → tweets ORDER BY created_at DESC LIMIT 21`.

### `GET /api/v1/search?q=<query>&cursor=<token>`
Full-text search across tweet text and hashtag names.
```
← 200:      {"results": [{"type": "tweet"|"hashtag", "tweet_id"?: ..., "text"?: ...,
             "author"?: {...}, "hashtag_id"?: ..., "name"?: ...,
             "score": 1.23, "hashtags"?: [...]}], "next_cursor": "<token>"|null}
← 200:      (empty q) {"results": [], "next_cursor": null}
```
Uses `websearch_to_tsquery('english', q)` for query parsing. UNION of tweet text FTS match
and hashtag name FTS match. Ranked by `ts_rank * recency_decay(created_at)` DESC.
Cursor encodes `{score, type, entity_id}`. 20 results per page.

### `GET /api/v1/trends?window=1h|24h&limit=<1-50>`
Velocity-ranked trending topics from Redis.
```
← 200:      {"window": "1h", "trends": [{"hashtag_id": "<uuid>", "name": "...",
             "velocity_score": 3.14, "tweet_count": 42}]}
← 422:      {"detail": [{"loc": ["query","window"], "msg": "..."}]}
```
Reads from `trends:{window}` ZSET. Default limit=10.

---

## Design decisions

### D1: In-process fan-out (no Kafka)

**Decision:** Background `asyncio` task polling `fanout_queue` Redis list every 500ms.

The FanOutWorker (`workers/fanout_worker.py`, 93 lines) runs `BRPOP fanout_queue 0.5`, parses the
payload, queries Postgres for followers, then pipelines `ZADD` to each follower's timeline ZSET.
A tweet from a user with 200 followers completes fan-out in ~20ms of Redis pipelined writes.

**Trade-off:** No queue durability. If the process crashes between `LPUSH` and `BRPOP`/`ZADD`,
followers miss the tweet in their cached timeline. The Postgres fallback on the next timeline read
(D2) covers this — the tweet is still visible, served from Postgres until cache warms. At production
scale (100M+ followers), Kafka would provide durability and decouple fan-out from the POST path.
For MVP, one process is simpler.

### D2: Redis-native timelines (no TimelineEntry table)

**Decision:** Skip the TimelineEntry table. Primary timeline store is a Redis sorted set
`timeline:{user_id}`; Postgres is the cold-cache fallback.

**Read path:** Redis `ZREVRANGEBYSCORE` → hydrate tweet objects from Postgres `SELECT WHERE tweet_id IN (...)`
on cache hit. On miss: `JOIN follows → tweets ORDER BY created_at DESC LIMIT 21` in Postgres.

**Trade-off:** Redis wipe = all cached timelines lost. Recovery is automatic on next read. Production
would add Redis AOF persistence and a TimelineEntry table as the durable system of record.

### D3: Postgres FTS (no Elasticsearch)

**Decision:** `tsvector` generated columns + GIN indexes on `tweets.text` and `hashtags.name`.
`websearch_to_tsquery` for user-friendly query parsing (supports quoted phrases, OR).

The search query (`routers/search.py`) uses a CTE + UNION approach combining tweet text matches
and hashtag name matches, ranked by `ts_rank * recency_decay(created_at)`.

**Trade-off:** Postgres FTS lacks real-time indexing, typo-tolerance, and custom ranking at scale.
At MVP scale with <10K tweets, these differences are invisible. Elasticsearch would add
operational complexity (JVM heap, cluster management) with zero query quality benefit at this
data volume.

### D4: UUIDv4 primary keys (no Snowflake)

**Decision:** `uuid.uuid4` for all PKs. Explicit `created_at` for chronological ordering.

**Trade-off:** UUIDs are 128-bit vs Snowflake's 64-bit — larger in Redis ZSETs and Postgres indexes.
At 1M rows ~50MB overhead, negligible. `ORDER BY tweet_id` is non-chronological (UUIDs are random);
all queries sort by `created_at` explicitly.

### D5: Velocity-based trending (not raw counts)

**Decision:** `score = count_recent / max(count_baseline, 1) * ln(1 + count_recent)`.
Two overlapping windows: 1h (responsive) and 24h (stable).

The TrendingWorker (`workers/trending_worker.py`, 128 lines) runs every 60s: counts hashtag
occurrences in `[now - 2*window, now - window]` (baseline) and `[now - window, now]` (recent)
via Postgres windowed queries, then computes velocity and writes to Redis.

**Trade-off:** Simple count aggregation would always return the most-used hashtags — `#news`
would dominate permanently. Velocity scoring surfaces spikes. The log factor prevents a topic
with 1M baseline mentions from getting infinite score if it doubles to 2M (that's noise, not a
trend). At MVP scale the 60s Postgres query completes in ~10ms.

### D6: Cursor pagination (not offset)

**Decision:** Opaque base64-encoded JSON cursors. Composite index seeks via
`WHERE (created_at, tweet_id) < ($1, $2) ORDER BY ... DESC LIMIT 21` — O(log N) per page
regardless of depth.

**Trade-off:** No "jump to page 5." Acceptable for infinite-scroll mobile UX. Offset pagination
(`OFFSET 40 LIMIT 20`) would scan and discard rows — O(N) per page — and break on concurrent
inserts.

### D7: Single-process async workers (no separate containers)

**Decision:** FanOutWorker and TrendingWorker run as `asyncio` background tasks within the
FastAPI process, started in the lifespan.

**Trade-off:** A CPU-bound worker could starve the HTTP server. Both workers are I/O-bound
(Redis `BRPOP`, Postgres count queries). At MVP scale this doesn't apply. Fan-out uses
`redis.pipeline()` for batch writes; trend computation runs once per 60s.

---

## Background workers

### FanOutWorker (`workers/fanout_worker.py`, 93 lines)

| Property | Value |
|----------|-------|
| Poll method | `BRPOP fanout_queue` (500ms timeout) |
| Dispatch | Redis pipeline — `ZADD timeline:{fid}` for each follower |
| Error handling | Silently retries on transient failure (1s cooldown) |
| Startup | Started by `fanout_worker_lifespan()` in `main.py` lifespan |

On a new tweet: author queries followers → pipelines ZADD to each follower's timeline ZSET.
If the author has no followers, the worker skips.

### TrendingWorker (`workers/trending_worker.py`, 128 lines)

| Property | Value |
|----------|-------|
| Poll interval | 60 seconds |
| Windows | 1h (responsive), 24h (stable) |
| Score formula | `count_recent / max(count_baseline, 1) × log(1 + count_recent)` |
| Storage | Redis `trends:{window}` (velocity) + `trends:{window}:counts` (tweet count) |
| Startup delay | 5s initial sleep for DB/Redis readiness |

---

## Test scenarios

### Acceptance test coverage

Each functional requirement has a corresponding black-box test file in `verify/acceptance/`.
All tests interact with the running system via HTTP — they never import the app.

```
verify/acceptance/
├── conftest.py               # Shared fixtures, helpers, assertion wrappers
├── test_healthz.py           # 1 case: GET /healthz → 200 {"status":"ok"}
├── test_fr_user_crud.py      # 8 cases: create/get user, duplicate/validation errors
├── test_fr1_post_tweet.py    # 12 cases: tweet creation, hashtags, 280-char, 404/422
├── test_fr2_home_timeline.py # 7 cases: timeline content, ordering, pagination, unfollow
├── test_fr3_profile_timeline.py # 5 cases: own tweets, ordering, pagination, 404
├── test_fr4_search.py        # 9 cases: keyword, hashtag, cursor, ranking, no-results
├── test_fr5_follow.py        # 9 cases: follow/unfollow, counters, idempotency, 422/404
└── test_fr6_trending.py      # 7 cases: window param, limits, result structure, ordering
```

**Total: 58 test cases.** Each test creates isolated entities per run (UUID-based usernames),
so tests are safe to run concurrently without cross-contamination.

### Test scenarios — key behaviors verified

**FR1 — Post tweet:**
- Valid tweet returns 201 with tweet_id, text, author_id, hashtags, created_at
- Hashtags extracted from `#(\w+)` regex in text
- Client-supplied hashtags merged with extracted ones, deduped
- Duplicate hashtag names reuse existing hashtag_id (upsert)
- Unknown author → 404, empty text → 422, >280 chars → 422
- Exactly 280 chars is valid
- GET tweet detail returns author and hashtag info

**FR2 — Home timeline:**
- Contains tweets from followed users only
- Reverse-chronological ordering (newest first)
- Cursor pagination: 20 per page, no overlap between pages
- Empty timeline for new user with no follows
- Unknown user → 404
- After unfollow, user's tweets excluded
- Each tweet includes author details

**FR3 — Profile timeline:**
- Contains only that user's tweets
- Reverse-chronological ordering
- Cursor pagination: 20 per page, no overlap
- Empty for user with no tweets
- Unknown user → 404

**FR4 — Search:**
- Keyword search finds matching tweets
- Hashtag name search finds tweets with that hashtag
- Empty query returns empty results (200, not error)
- Cursor pagination works (20 per page)
- Results include author info
- Results ordered by relevance score descending (`ts_rank * recency_decay`)
- Hashtag-type results returned alongside tweet results
- Hashtag results include tweet_count

**FR5 — Follow/unfollow:**
- Following increments both `following_count` and `follower_count`
- Unfollowing decrements both counters
- Duplicate follow is idempotent (counts unchanged)
- Self-follow → 422
- Unknown followee → 404
- Unknown follower → 404
- After follow, timeline includes followee's tweets (backfill)
- Idempotent unfollow when not following
- Following multiple users accumulates counts correctly

**FR6 — Trending:**
- Returns valid response structure (trends, window)
- Works for both 1h and 24h windows
- Invalid window → 422
- Limit parameter respected
- Each trend item has hashtag_id, name, velocity_score, tweet_count
- Results ordered by velocity_score descending

### White-box test

`tests/test_healthz.py` (1 case): Verifies `GET /healthz` returns 200 with `{"status":"ok"}`
via ASGI transport — no database required. Uses `httpx.AsyncClient` with `ASGITransport`.

---

## CI/CD

Three GitHub Actions workflows:

| Workflow | File | Trigger | What it runs |
|----------|------|---------|-------------|
| **lint** | `.github/workflows/lint.yml` | PR + push to `main` + daily | `ruff check` + `ruff format --check` on `src/ tests/ verify/` |
| **ci** | `.github/workflows/ci.yml` | PR + push to `main` + daily | Unit tests (Postgres 16-alpine service) + Docker build |
| **functional** | `.github/workflows/functional.yml` | PR + push to `main` + daily | `docker compose up --build` → `alembic upgrade head` → `verify/acceptance/` suite → compose down |

All workflows run a daily scheduled check at 13:17 UTC.

---

## Module layout

```
src/twitter_x/
├── __init__.py                  # Package marker
├── main.py                      # create_app() factory, lifespan, /healthz, router registration
├── config.py                    # pydantic-settings (DATABASE_URL, REDIS_URL, APP_PORT)
├── database.py                  # async engine/session factory, get_session dependency
├── redis.py                     # Redis client (graceful init, handles unavailable Redis)
├── models/
│   ├── base.py                  # DeclarativeBase
│   ├── user.py                  # User ORM model
│   ├── tweet.py                 # Tweet ORM model (fts_vector generated column)
│   ├── hashtag.py               # Hashtag + TweetHashtag ORM models
│   └── follow.py                # Follow ORM model
├── schemas/
│   ├── user.py                  # UserCreate, UserResponse
│   ├── tweet.py                 # TweetCreate, TweetResponse, TweetDetail, HashtagItem
│   ├── timeline.py              # TimelineItem, TimelineResponse, TimelineAuthor
│   ├── search.py                # SearchResult, SearchResponse
│   ├── trends.py                # TrendItem, TrendsResponse
│   └── common.py                # FollowResponse, cursor helpers
├── routers/
│   ├── health.py                # GET /healthz
│   ├── users.py                 # User CRUD + follow/unfollow + profile timeline
│   ├── tweets.py                # POST/GET tweets
│   ├── timeline.py              # GET /api/v1/timeline/home
│   ├── search.py                # FTS search (websearch_to_tsquery, ranked UNION)
│   └── trends.py                # Trending topics (Redis ZSET read)
├── services/
│   ├── user_service.py          # User CRUD, follow/unfollow, counter update, backfill
│   ├── tweet_service.py         # Tweet create, hashtag extraction, fan-out dispatch
│   ├── timeline_service.py      # Redis ZSET + Postgres fallback, cursor pagination
│   ├── search_service.py        # FTS CTE+UNION query, ts_rank + recency_decay
│   └── trending_service.py      # Velocity scoring, windowed count queries
└── workers/
    ├── fanout_worker.py         # 500ms BRPOP → pipeline ZADD to followers
    └── trending_worker.py       # 60s poll → velocity scores → Redis ZSET

verify/
├── manifest.env                 # e2e lifecycle contract (MODE, UP, DOWN, READY, ACCEPTANCE)
└── acceptance/                  # Black-box tests, one file per FR (58 cases total)
    ├── conftest.py              # Shared fixtures and helpers
    ├── test_healthz.py          # Health check
    ├── test_fr_user_crud.py     # User CRUD (8 cases)
    ├── test_fr1_post_tweet.py   # FR1 — Post tweet (12 cases)
    ├── test_fr2_home_timeline.py # FR2 — Home timeline (7 cases)
    ├── test_fr3_profile_timeline.py # FR3 — Profile timeline (5 cases)
    ├── test_fr4_search.py       # FR4 — Search (9 cases)
    ├── test_fr5_follow.py       # FR5 — Follow/unfollow (9 cases)
    └── test_fr6_trending.py     # FR6 — Trending (7 cases)

tests/
├── conftest.py                  # ASGI transport fixtures
└── test_healthz.py              # White-box unit test (in-memory)

alembic/
└── versions/
    ├── 1093b16c00af_initial_schema.py   # 5 tables + indexes + GIN
    ├── 09bb7eb6ec2a_extend_username_to_50.py  # Username length extension
    └── 002_recency_decay.py             # recency_decay() SQL function
```

---

## Source verification

Every claim in this document traces to an artifact in the repository:

| Artifact | Location |
|----------|----------|
| REST API surface | `src/twitter_x/routers/` — 6 files, ~300 lines |
| Database schema | `src/twitter_x/models/` — 5 ORM models + `alembic/versions/` — 3 migrations |
| FTS implementation | `routers/search.py` + `services/search_service.py` — raw SQL with CTE+UNION |
| Background workers | `workers/fanout_worker.py` (93 lines) + `trending_worker.py` (128 lines) |
| Business services | `services/` — 5 files, ~790 lines |
| White-box tests | `tests/test_healthz.py` — 1 suite, 1 passing |
| Acceptance tests | `verify/acceptance/` — 8 suites, 58 cases total |
| Docker/Compose | `Dockerfile` (multi-stage, 34 lines) + `docker-compose.yml` (3 services, healthchecks) |
| CI/CD | `.github/workflows/` — 3 YAML files (lint, ci, functional) |
| Deploy runbook | `DEPLOY.md` — 106-line runbook with commands, env vars, troubleshooting |
