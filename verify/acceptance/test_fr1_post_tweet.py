"""FR1: Post a tweet with text and optional hashtags.

POST /api/v1/tweets → 201 with tweet_id, text, hashtags
GET /api/v1/tweets/{id} → 200 with author, hashtags
Unknown author → 404
Empty text → 422
Text > 280 chars → 422
"""

from verify.acceptance.conftest import (
    assert_404,
    assert_422,
    create_tweet,
    create_user,
    get_tweet_detail,
)


def test_create_tweet_201(client):
    """Creating a valid tweet returns 201 with the tweet data."""
    user = create_user(client)
    body = create_tweet(client, user["user_id"], text="hello twitter")

    assert body["text"] == "hello twitter"
    assert body["author_id"] == user["user_id"]
    assert "tweet_id" in body
    assert "created_at" in body
    # No hashtags in text → empty hashtags array
    assert body["hashtags"] == []


def test_create_tweet_with_hashtags(client):
    """Creating a tweet with hashtags extracts and returns them."""
    user = create_user(client)
    body = create_tweet(
        client,
        user["user_id"],
        text="loving the #weather today",
    )

    assert len(body["hashtags"]) == 1
    assert body["hashtags"][0]["name"] == "weather"
    assert "hashtag_id" in body["hashtags"][0]


def test_create_tweet_with_client_hashtags(client):
    """Client-supplied hashtags are merged with extracted ones."""
    user = create_user(client)
    body = create_tweet(
        client,
        user["user_id"],
        text="great day",
        hashtags=["vibes", "sunny"],
    )

    hashtag_names = {h["name"] for h in body["hashtags"]}
    assert hashtag_names == {"vibes", "sunny"}


def test_hashtag_deduplication(client):
    """Tweets with the same hashtag reuse the existing hashtag row."""
    user = create_user(client)
    t1 = create_tweet(client, user["user_id"], text="first #trending")
    t2 = create_tweet(client, user["user_id"], text="second #trending")

    h1_ids = {h["hashtag_id"] for h in t1["hashtags"]}
    h2_ids = {h["hashtag_id"] for h in t2["hashtags"]}
    # Both tweets share the same hashtag_id for 'trending'
    assert h1_ids == h2_ids
    assert len(h1_ids) == 1


def test_create_tweet_unknown_author(client):
    """Posting a tweet for a non-existent author returns 404."""
    r = client.post(
        "/api/v1/tweets",
        json={"author_id": "00000000-0000-0000-0000-000000000000", "text": "hello"},
    )
    assert_404(r)


def test_create_tweet_empty_text(client):
    """Posting a tweet with empty text returns 422."""
    user = create_user(client)
    r = client.post(
        "/api/v1/tweets",
        json={"author_id": user["user_id"], "text": ""},
    )
    assert_422(r)


def test_create_tweet_text_too_long(client):
    """Posting a tweet with >280 chars returns 422."""
    user = create_user(client)
    r = client.post(
        "/api/v1/tweets",
        json={"author_id": user["user_id"], "text": "x" * 281},
    )
    assert_422(r)


def test_create_tweet_280_chars_ok(client):
    """A tweet at exactly 280 chars is valid."""
    user = create_user(client)
    body = create_tweet(client, user["user_id"], text="x" * 280)
    assert body["text"] == "x" * 280


def test_get_tweet_detail_200(client):
    """Fetching an existing tweet returns full detail with author."""
    user = create_user(client, username="alice")
    tweet = create_tweet(client, user["user_id"], text="test tweet #demo")

    detail = get_tweet_detail(client, tweet["tweet_id"])
    assert detail["tweet_id"] == tweet["tweet_id"]
    assert detail["text"] == "test tweet #demo"
    assert detail["author"]["user_id"] == user["user_id"]
    assert detail["author"]["username"] == "alice"
    assert len(detail["hashtags"]) == 1
    assert detail["hashtags"][0]["name"] == "demo"


def test_get_tweet_detail_404(client):
    """Fetching a non-existent tweet returns 404."""
    r = client.get("/api/v1/tweets/00000000-0000-0000-0000-000000000000")
    assert_404(r)


def test_multiple_hashtags_in_text(client):
    """A tweet with multiple hashtags extracts all of them."""
    user = create_user(client)
    body = create_tweet(
        client,
        user["user_id"],
        text="check out #rust and #python and #golang",
    )

    hashtag_names = {h["name"] for h in body["hashtags"]}
    assert hashtag_names == {"rust", "python", "golang"}
