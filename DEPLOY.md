# Twitter/X MVP — Deploy

## Local development

### Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)

### First run

```bash
# 1. Start the stack
APP_PORT=8040 docker compose up -d --build

# 2. Run Alembic migrations
docker compose exec app alembic upgrade head

# 3. Verify the app is ready
curl -sf http://localhost:8040/healthz
# → {"status":"ok"}

# 4. Run acceptance tests
cd verify
python -m venv .venv && source .venv/bin/activate
pip install httpx pytest
API_BASE_URL=http://localhost:8040 python -m pytest acceptance -q
```

### Stopping

```bash
# Stop and remove containers + volumes
docker compose down --volumes --remove-orphans
```

## Configuration

All configuration is via environment variables (set in `docker-compose.yml` or `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://twitter_x:***@db:5432/twitter_x` | Postgres connection |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `APP_PORT` | `8040` | Host port for the API |

## Migrations

```bash
# Create a new migration
docker compose exec app alembic revision --autogenerate -m "description"

# Apply all pending migrations
docker compose exec app alembic upgrade head

# Rollback one step
docker compose exec app alembic downgrade -1
```
