# Builder stage
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1

WORKDIR /build

COPY pyproject.toml requirements.txt ./
COPY src/ src/

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt && \
    /opt/venv/bin/pip install --no-cache-dir alembic

# Runtime stage
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"

# Set WORKDIR before the relative COPYs so alembic.ini / alembic/ land in /app
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic/ alembic/
COPY src/ src/
COPY pyproject.toml requirements.txt ./

EXPOSE 8000

CMD ["uvicorn", "twitter_x.main:app", "--host", "0.0.0.0", "--port", "8000"]
