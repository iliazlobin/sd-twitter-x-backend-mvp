"""Tests for /healthz endpoint."""

from httpx import ASGITransport, AsyncClient

from twitter_x.main import app


async def test_healthz_returns_ok() -> None:
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
