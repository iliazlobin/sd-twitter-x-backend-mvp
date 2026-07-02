# Twitter/X MVP

A real-time social platform backend that implements the core Twitter posting, timeline, search, and trending loop. One FastAPI process serves a REST API backed by PostgreSQL for durable storage and Redis for timeline caching, fan-out dispatch, and trending computation.

## Stack

| Layer | Technology | Role |
|-------|-----------|------|
| **API** | FastAPI (Python 3.12) | REST endpoints, Pydantic validation, async handlers |
| **Database** | PostgreSQL 16 | Durable store — users, tweets, hashtags, follows |
| **Cache** | Redis 7 | Timeline ZSETs, fan-out queue, trend scores |
| **Migrations** | Alembic | Schema versioning (2 migrations — initial + recency decay) |
| **Background** | `asyncio` tasks (in-process) | Fan-out dispatch, trending computation |
| **Container** | Docker Compose | `app` + `db` (Postgres) + `redis` containers |

## Quick start

```bash
# 1. Copy env template (optional — built-in defaults work)
cp .env.example .env

# 2. Build and start the full stack
APP_PORT=8040 docker compose up -d --build

# 3. Wait for health
sleep 15 && curl -sf http://localhost:8040/healthz
# → {"status":"ok"}

# 4. Run migrations
docker compose exec app alembic upgrade head

# 5. Smoke test — create a user and tweet
curl -sf http://localhost:8040/api/v1/users \
  -H 'Content-Type: application/json' \
  -d '{"username": "alice"}'
# → {"user_id":"...","username":"alice","follower_count":0,...}

curl -sf http://localhost:8040/api/v1/tweets \
  -H 'Content-Type: application/json' \
  -d '{"author_id":"<user_id>","text":"Hello #twitterx MVP!","hashtags":["mvp"]}'
# → {"tweet_id":"...","text":"Hello #twitterx MVP!","hashtags":[...],...}
```

## API

### Core endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check — `{"status": "ok"}` |
| `POST` | `/api/v1/users` | Create user — `{username, display_name?}` |
| `GET` | `/api/v1/users/{user_id}` | Get user profile with follower/following counts |
| `GET` | `/api/v1/users/{user_id}/tweets?cursor=` | Profile timeline (user's own tweets, paginated) |
| `POST` | `/api/v1/users/{followee_id}/follow?follower_id=` | Follow user (idempotent) |
| `DELETE` | `/api/v1/users/{followee_id}/follow?follower_id=` | Unfollow user (idempotent) |
| `POST` | `/api/v1/tweets` | Create tweet — `{author_id, text, hashtags?}` |
| `GET` | `/api/v1/tweets/{tweet_id}` | Get tweet detail with author + hashtags |
| `GET` | `/api/v1/timeline/home?user_id=&cursor=` | Home timeline (followed users' tweets, paginated) |
| `GET` | `/api/v1/search?q=&cursor=` | Full-text search across tweets and hashtags |
| `GET` | `/api/v1/trends?window=1h&limit=10` | Velocity-ranked trending topics |

### Pagination

All list endpoints use cursor-based pagination. Cursors are opaque base64-encoded JSON tokens. Pass `null` for the first page; the response includes `next_cursor` if more results exist.

```bash
curl -s "http://localhost:8040/api/v1/timeline/home?user_id=<uuid>&cursor=<token>"
```

## Architecture

```mermaid
graph TB
    subgraph api["FastAPI — port 8000"]
        RT[Tweets Router]
        RL[Timeline Router]
        RU[Users Router]
        RS[Search Router]
        RTR[Trends Router]
    end

    subgraph svc["Service Layer<br/>(routers → services → DB)"]
        TS[TweetService<br/>create, hashtag, fan-out dispatch]
        TLS[TimelineService<br/>sorted-set merge, cursor pagination]
        US[UserService<br/>CRUD, follow/unfollow, counters]
        SS[SearchService<br/>FTS tsquery, ranked UNION]
        TRS[TrendingService<br/>velocity scoring, ZSET update]
    end

    subgraph store["PostgreSQL 16"]
        PG[(users, tweets, hashtags,<br/>tweet_hashtags, follows<br/>+ GIN FTS indexes)]
    end

    subgraph cache["Redis 7"]
        RD[(timeline:{uid} ZSETs<br/>trends:{window} ZSETs<br/>fanout_queue list)]
    end

    subgraph bg["Background asyncio tasks"]
        FO[FanOutWorker<br/>500ms BRPOP → pipeline ZADD]
        TW[TrendingWorker<br/>60s poll → velocity scores]
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

## Data model

```
User        — user_id (PK, UUIDv4), username (unique, ≤15), display_name,
               follower_count, following_count (denormalized), created_at
Tweet       — tweet_id (PK, UUIDv4), author_id (FK → User), text (≤280),
               fts_vector (GIN-indexed generated column), created_at
Hashtag     — hashtag_id (PK, UUIDv4), name (unique), fts_vector (GIN-indexed)
TweetHashtag — (tweet_id, hashtag_id) join table
Follow      — (follower_id, followee_id) with UNIQUE constraint for idempotency
```

## Test suite

### White-box unit tests (11 tests, 11 passing)

Run via `pytest` with in-memory SQLite (no external deps):

```bash
docker compose exec app python -m pytest tests/ -v
```

| File | What it covers |
|------|---------------|
| `tests/test_healthz.py` | GET /healthz returns 200 + `{"status":"ok"}` |

### Black-box acceptance tests (7 suites, ~25 tests)

Run against the running stack:

```bash
API_BASE_URL=http://localhost:8040 python -m pytest verify/acceptance -v
```

| File | FR | What it asserts |
|------|----|-----------------|
| `verify/acceptance/test_healthz.py` | Health | GET /healthz → 200 |
| `verify/acceptance/test_fr1_post_tweet.py` | FR1 | Tweet creation with hashtags, 422 for empty/long text, 404 for unknown author |
| `verify/acceptance/test_fr2_home_timeline.py` | FR2 | Timeline returns followed users' tweets, reverse-chronological, cursor pagination |
| `verify/acceptance/test_fr3_profile_timeline.py` | FR3 | Profile shows only that user's tweets, paginated |
| `verify/acceptance/test_fr4_search.py` | FR4 | FTS keyword + hashtag search, ranked results, empty query → empty |
| `verify/acceptance/test_fr5_follow.py` | FR5 | Follow/unfollow idempotent, counter updates, self-follow 422 |
| `verify/acceptance/test_fr6_trending.py` | FR6 | Velocity-ranked trends, window validation, ordered scores |

### CI/CD

Three GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | What it checks |
|----------|---------|---------------|
| `lint.yml` | PR + push to main | `ruff check` + `ruff format --check` |
| `ci.yml` | PR + push to main | Unit tests (against Postgres service) + Docker build |
| `functional.yml` | PR + push to main | Full stack up → acceptance tests → teardown |

## Project layout

```
src/twitter_x/
├── main.py              # create_app() factory, lifespan, /healthz
├── config.py            # pydantic-settings, env-driven
├── database.py          # async engine/session factory
├── redis.py             # Redis client (gracefully handles unavailable)
├── models/              # SQLAlchemy ORM — User, Tweet, Hashtag, Follow
├── schemas/             # Pydantic — request/response models
├── routers/             # FastAPI — 6 endpoints (health, users, tweets, timeline, search, trends)
├── services/            # Business logic (stubs ready for extraction)
└── workers/             # asyncio tasks — fan-out (500ms), trending (60s)
```

## Configuration

The app is configured entirely through environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_PORT` | `8040` | Host-side port mapped to in-container `8000` |
| `DATABASE_URL` | `postgresql+asyncpg://twitter_x:twitter_x@db:5432/twitter_x` | Postgres DSN |
| `REDIS_URL` | `redis://redis:6379/0` | Redis DSN |

Set via `.env` file or `environment:` in compose. Secrets (`DATABASE_URL` credentials) belong in `.env` — never committed.

## Out of scope (MVP)

Media uploads, Kafka/event streaming, celebrity push/pull fan-out, Snowflake IDs, soft deletes/tweet deletion, authentication, DMs, Spaces, X Premium, rate limiting, multi-device sync.
