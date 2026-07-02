"""User CRUD — create and fetch user profiles.

POST /api/v1/users → 201 with user data
POST /api/v1/users → 409 duplicate username
POST /api/v1/users → 422 invalid username (empty, too long, bad chars)
GET /api/v1/users/{id} → 200 with profile
GET /api/v1/users/{id} → 404 not found
"""

import uuid

from verify.acceptance.conftest import (
    assert_200,
    assert_201,
    assert_404,
    assert_409,
    assert_422,
)


def test_create_user_201(client):
    """Creating a user with valid data returns 201."""
    username = f"newuser-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/v1/users",
        json={"username": username, "display_name": "New User"},
    )
    body = assert_201(r)
    assert body["username"] == username
    assert body["display_name"] == "New User"
    assert "user_id" in body
    assert body["follower_count"] == 0
    assert body["following_count"] == 0
    assert "created_at" in body


def test_create_user_display_name_optional(client):
    """Display name is optional on user creation."""
    username = f"nodisplay-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/users", json={"username": username})
    body = assert_201(r)
    assert body["display_name"] is None


def test_create_user_duplicate_username_409(client):
    """Creating a user with an existing username returns 409."""
    username = f"dup-{uuid.uuid4().hex[:8]}"
    client.post("/api/v1/users", json={"username": username})
    r = client.post("/api/v1/users", json={"username": username})
    assert_409(r)


def test_create_user_empty_username_422(client):
    """Empty username returns 422."""
    r = client.post("/api/v1/users", json={"username": ""})
    assert_422(r)


def test_create_user_long_username_422(client):
    """Username > 50 chars returns 422."""
    r = client.post("/api/v1/users", json={"username": "a" * 51})
    assert_422(r)


def test_create_user_invalid_username_chars_422(client):
    """Username with invalid characters returns 422."""
    r = client.post("/api/v1/users", json={"username": "bad@user"})
    assert_422(r)


def test_get_user_200(client):
    """Fetching an existing user returns 200 with profile data."""
    username = f"fetchme-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/v1/users",
        json={"username": username, "display_name": "Fetch Me"},
    )
    user_id = assert_201(created)["user_id"]

    r = client.get(f"/api/v1/users/{user_id}")
    body = assert_200(r)
    assert body["user_id"] == user_id
    assert body["username"] == username
    assert body["display_name"] == "Fetch Me"
    assert body["follower_count"] == 0
    assert body["following_count"] == 0


def test_get_user_404(client):
    """Fetching a non-existent user returns 404."""
    r = client.get("/api/v1/users/00000000-0000-0000-0000-000000000000")
    assert_404(r)
