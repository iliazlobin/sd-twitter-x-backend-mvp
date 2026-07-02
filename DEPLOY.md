# Twitter/X Backend MVP — Deploy

## Prerequisites

- Docker & Docker Compose (v2.22+)
- A running Docker daemon
- Port 8010 free on the host (overridable via `APP_PORT`)

## Quick start (compose)

```bash
# 1. Clone the repository
git clone <repo-url> sd-twitter-x-backend
cd sd-twitter-x-backend

# 2. Bootstrap environment (edit .env to override defaults)
cp .env.example .env

# 3. Build and start all services
docker compose up -d --build

# 4. Run database migrations (Alembic owns the schema)
docker compose run --rm app alembic upgrade head

# 5. Verify the app is healthy
curl -sf http://localhost:8010/healthz
# Expected: {"status":"ok"}
```

The stack is now serving on `http://localhost:8010`.

## Environment variables

All values are optional — the stack works out of the box with compose-provided infrastructure.

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_PORT` | `8010` | Host port mapped to the app container (port 8000 in-container) |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@db:5432/twitter_x` | PostgreSQL connection string |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |

Set these in `.env` (copy from `.env.example`). The compose file reads `.env` automatically.

## Services

| Service | Image | Internal port | Health check |
|---------|-------|---------------|--------------|
| `db` | `postgres:16-alpine` | 5432 | `pg_isready -U postgres` |
| `redis` | `redis:7-alpine` | 6379 | `redis-cli ping` |
| `app` | (built from `Dockerfile`) | 8000 | `curl -sf http://localhost:8000/healthz` |

Only `app` publishes a host port. `db` and `redis` are compose-internal.

## Logs

```bash
# All services
docker compose logs -f

# App only (most useful)
docker compose logs app --tail=100 -f

# Database
docker compose logs db --tail=50
```

## Teardown

```bash
# Stop and remove containers, volumes (wipes DB data)
docker compose down --volumes --remove-orphans

# Stop without removing volumes (data preserved)
docker compose down
```

## CI/CD

Three GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | What it runs |
|----------|---------|-------------|
| `lint.yml` | PR + push to `main` + daily | `ruff check` + `ruff format --check` |
| `ci.yml` | PR + push to `main` + daily | Unit tests (Postgres service) + Docker build |
| `functional.yml` | PR + push to `main` + daily | `docker compose up` → migrations → acceptance tests → teardown |

## Manual testing (host-only, not auto-verified)

```bash
# Create a user
curl -s -X POST http://localhost:8010/api/v1/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"testuser","display_name":"Test User"}'

# Post a tweet
curl -s -X POST http://localhost:8010/api/v1/tweets \
  -H 'Content-Type: application/json' \
  -d '{"author_id":"<user-uuid>","text":"Hello #world"}'
```

## Troubleshooting

- **App crash-loops**: `docker compose logs app --tail=50` — common cause: missing `.env` or stale volume
- **Migration fails**: ensure the compose stack is fully up: `docker compose ps` should show all services healthy
- **Port conflict**: set `APP_PORT` to an unused port in `.env`, e.g. `APP_PORT=8011`
- **Schema issues**: run `docker compose run --rm app alembic upgrade head` to sync migrations
