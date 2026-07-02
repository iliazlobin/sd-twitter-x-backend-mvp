"""FR6: Return trending topics with velocity-based scoring.

GET /api/v1/trends?window=1h|24h&limit= → 200
Returns hashtags with velocity scores
Window parameter validation
Results ordered by score descending
Empty results for cold window
Invalid window → 422
"""

from verify.acceptance.conftest import (
    assert_422,
    get_trends,
)


def test_trends_returns_results(client):
    """GET /api/v1/trends returns a valid response structure."""
    results = get_trends(client)
    assert "trends" in results
    assert "window" in results
    assert results["window"] in ("1h", "24h")
    assert isinstance(results["trends"], list)


def test_trends_window_1h(client):
    """Explicit 1h window returns results."""
    results = get_trends(client, window="1h")
    assert results["window"] == "1h"


def test_trends_window_24h(client):
    """Explicit 24h window returns results."""
    results = get_trends(client, window="24h")
    assert results["window"] == "24h"


def test_trends_invalid_window_422_raw(client):
    """Invalid window returns 422."""
    r = client.get("/api/v1/trends", params={"window": "7d"})
    assert_422(r)


def test_trends_limit_param(client):
    """Limit parameter controls result count."""
    results = get_trends(client, limit=3)
    assert len(results["trends"]) <= 3


def test_trends_result_structure(client):
    """Each trend item has the expected fields."""
    results = get_trends(client, window="1h", limit=10)
    for trend in results["trends"]:
        assert "hashtag_id" in trend
        assert "name" in trend
        assert "velocity_score" in trend
        assert "tweet_count" in trend


def test_trends_ordered_by_score(client):
    """Trending results are ordered by velocity_score descending."""
    results = get_trends(client, window="1h", limit=10)
    if len(results["trends"]) >= 2:
        scores = [t["velocity_score"] for t in results["trends"]]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Score at index {i} ({scores[i]}) should be >= "
                f"score at index {i + 1} ({scores[i + 1]})"
            )
