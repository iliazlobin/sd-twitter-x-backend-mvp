# Twitter/X MVP

An MVP real-time social platform backend that implements the core Twitter posting and timeline loop.

## Stack

- **FastAPI** (Python 3.12) — REST API server
- **PostgreSQL 16** — durable storage (users, tweets, hashtags, follows)
- **Redis 7** — timeline cache, trends, fan-out queue
- **Alembic** — schema migrations
- **Docker Compose** — local development & testing

## Quick start

```bash
# Start the full stack
APP_PORT=8040 docker compose up -d --build

# Wait for health check
curl -sf http://localhost:8040/healthz

# Run acceptance tests
cd verify
python -m venv .venv && source .venv/bin/activate
pip install httpx pytest
API_BASE_URL=http://localhost:8040 python -m pytest acceptance -q
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/healthz` | Health check → `{"status": "ok"}` |
| POST | `/api/v1/users` | Create user (body: `{username, display_name?}`) |
| GET | `/api/v1/users/{id}` | Get user profile |
| POST | `/api/v1/tweets` | Create tweet (body: `{author_id, text, hashtags?}`) |
| GET | `/api/v1/tweets/{id}` | Get tweet detail with author + hashtags |
| GET | `/api/v1/timeline/home?user_id=<id>&cursor=<token>` | Home timeline (followed users' tweets) |
| GET | `/api/v1/users/{id}/tweets?cursor=<token>` | Profile timeline |
| POST | `/api/v1/users/{id}/follow?follower_id=<id>` | Follow a user |
| DELETE | `/api/v1/users/{id}/follow?follower_id=<id>` | Unfollow a user |
| GET | `/api/v1/search?q=<query>&cursor=<token>` | Full-text search |
| GET | `/api/v1/trends?window=1h&limit=10` | Trending topics |

## Data model

- **User** — username, display_name, denormalized follower/following counts
- **Tweet** — text (max 280 chars), author FK, FTS tsvector with GIN index
- **Hashtag** — name (unique), FTS tsvector with GIN index
- **TweetHashtag** — join table (tweet ↔ hashtag)
- **Follow** — follower ↔ followee with idempotent UNIQUE constraint

## Key design decisions

- **In-process fan-out** — background asyncio task pushes tweets to followers' Redis timelines
- **Redis-native timelines** — sorted sets `timeline:{user_id}`, Postgres fallback on cache miss
- **Postgres FTS** — GIN-indexed tsvector columns on tweets.text and hashtags.name
- **UUIDv4** primary keys (no Snowflake IDs in MVP)
- **Cursor pagination** — base64 JSON cursors for stable pagination
- **Velocity-based trending** — `count_recent / max(count_baseline, 1) * log(1 + count_recent)`
