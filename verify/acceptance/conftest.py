"""Shared fixtures and helpers for the Twitter/X MVP black-box acceptance suite.

These tests do NOT import `src.twitter_x`. They talk to the running system
via HTTP at API_BASE_URL. Test isolation is achieved through unique
identifiers per test — no database clearing required.
"""

import os
import uuid

import httpx
import pytest

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_url():
    return API_BASE_URL


@pytest.fixture(scope="session")
def client(base_url):
    """Session-scoped httpx client for the entire acceptance run."""
    with httpx.Client(base_url=base_url, timeout=30) as c:
        yield c


@pytest.fixture
def fresh_uuid():
    """Unique UUID per test for isolation."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_status(r, expected_status):
    """Assert status and return parsed JSON."""
    assert r.status_code == expected_status, (
        f"Expected {expected_status}, got {r.status_code}: {r.text}"
    )
    if r.status_code == 204:
        return None
    return r.json()


def assert_200(r):
    return assert_status(r, 200)


def assert_201(r):
    return assert_status(r, 201)


def assert_400(r):
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
    return r.json()


def assert_404(r):
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    return r.json()


def assert_409(r):
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
    return r.json()


def assert_422(r):
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# Setup helpers — create entities via HTTP
# ---------------------------------------------------------------------------


def create_user(client, username=None, display_name=None):
    """Create a user and return the parsed response body (201)."""
    if username is None:
        username = f"user-{uuid.uuid4().hex[:8]}"
    body = {"username": username}
    if display_name:
        body["display_name"] = display_name
    r = client.post("/api/v1/users", json=body)
    return assert_201(r)


def create_tweet(client, author_id, text="hello world", hashtags=None):
    """Create a tweet and return the parsed response body (201)."""
    body = {"author_id": author_id, "text": text}
    if hashtags is not None:
        body["hashtags"] = hashtags
    r = client.post("/api/v1/tweets", json=body)
    return assert_201(r)


def get_tweet_detail(client, tweet_id):
    """Fetch a tweet by id."""
    r = client.get(f"/api/v1/tweets/{tweet_id}")
    return assert_200(r)


def get_home_timeline(client, user_id, cursor=None):
    """Fetch home timeline for a user."""
    params = {"user_id": user_id}
    if cursor:
        params["cursor"] = cursor
    r = client.get("/api/v1/timeline/home", params=params)
    return assert_200(r)


def get_profile_timeline(client, user_id, cursor=None):
    """Fetch a user's profile timeline."""
    params = {}
    if cursor:
        params["cursor"] = cursor
    r = client.get(f"/api/v1/users/{user_id}/tweets", params=params)
    return assert_200(r)


def get_user_profile(client, user_id):
    """Fetch a user's profile."""
    r = client.get(f"/api/v1/users/{user_id}")
    return assert_200(r)


def follow_user(client, followee_id, follower_id):
    """Follow a user. Returns 200 with status."""
    r = client.post(
        f"/api/v1/users/{followee_id}/follow",
        params={"follower_id": follower_id},
    )
    return assert_200(r)


def unfollow_user(client, followee_id, follower_id):
    """Unfollow a user. Returns 200 with status."""
    r = client.delete(
        f"/api/v1/users/{followee_id}/follow",
        params={"follower_id": follower_id},
    )
    return assert_200(r)


def search_content(client, query, cursor=None):
    """Full-text search."""
    params = {"q": query}
    if cursor:
        params["cursor"] = cursor
    r = client.get("/api/v1/search", params=params)
    return assert_200(r)


def get_trends(client, window="1h", limit=10):
    """Fetch trending topics."""
    params = {"window": window, "limit": limit}
    r = client.get("/api/v1/trends", params=params)
    return assert_200(r)


def healthz(client):
    """Hit the health check."""
    r = client.get("/healthz")
    return assert_200(r)
