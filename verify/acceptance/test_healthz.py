"""GET /healthz returns 200 when the app is alive."""

from verify.acceptance.conftest import healthz


def test_healthz_200(client):
    body = healthz(client)
    assert body["status"] == "ok"
