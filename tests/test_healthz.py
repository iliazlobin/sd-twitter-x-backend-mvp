from __future__ import annotations


class TestHealthz:
    async def test_healthz_returns_200(self, client):
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
