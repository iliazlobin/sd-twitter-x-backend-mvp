"""FR3: View a user's profile timeline.

GET /api/v1/users/{id}/tweets?cursor= → 200
Returns only that user's tweets
Reverse-chronological ordering
Cursor pagination (20 tweets/page)
404 for unknown user
"""

import time

from verify.acceptance.conftest import (
    assert_404,
    create_tweet,
    create_user,
    get_profile_timeline,
)


def test_profile_timeline_returns_own_tweets(client):
    """Profile timeline contains only the specified user's tweets."""
    alice = create_user(client, username="alice4")
    bob = create_user(client, username="bob4")

    t_alice = create_tweet(client, alice["user_id"], text="alice's tweet")
    create_tweet(client, bob["user_id"], text="bob's tweet")

    timeline = get_profile_timeline(client, alice["user_id"])
    tweet_ids = [t["tweet_id"] for t in timeline["tweets"]]
    assert t_alice["tweet_id"] in tweet_ids
    # Should not contain Bob's tweet
    for t in timeline["tweets"]:
        assert "author" not in t or t.get("author", {}).get("user_id") != bob["user_id"]


def test_profile_timeline_reverse_chronological(client):
    """Profile tweets are ordered newest first."""
    user = create_user(client, username="chrono")

    t1 = create_tweet(client, user["user_id"], text="oldest")
    time.sleep(0.15)
    t2 = create_tweet(client, user["user_id"], text="middle")
    time.sleep(0.15)
    t3 = create_tweet(client, user["user_id"], text="newest")

    timeline = get_profile_timeline(client, user["user_id"])
    tweet_ids = [t["tweet_id"] for t in timeline["tweets"]]
    assert tweet_ids == [t3["tweet_id"], t2["tweet_id"], t1["tweet_id"]]


def test_profile_timeline_cursor_pagination(client):
    """Cursor pagination works for profile timelines."""
    user = create_user(client, username="pager")

    for i in range(25):
        create_tweet(client, user["user_id"], text=f"tweet {i}")
        time.sleep(0.02)

    page1 = get_profile_timeline(client, user["user_id"])
    assert len(page1["tweets"]) == 20
    assert page1["next_cursor"] is not None

    page2 = get_profile_timeline(client, user["user_id"], cursor=page1["next_cursor"])
    assert len(page2["tweets"]) == 5
    assert page2["next_cursor"] is None

    p1_ids = {t["tweet_id"] for t in page1["tweets"]}
    p2_ids = {t["tweet_id"] for t in page2["tweets"]}
    assert p1_ids.isdisjoint(p2_ids)


def test_profile_timeline_empty_for_new_user(client):
    """A new user with no tweets has an empty profile timeline."""
    user = create_user(client, username="empty")
    timeline = get_profile_timeline(client, user["user_id"])
    assert timeline["tweets"] == []
    assert timeline["next_cursor"] is None


def test_profile_timeline_404(client):
    """Requesting profile timeline for a non-existent user returns 404."""
    r = client.get(
        "/api/v1/users/00000000-0000-0000-0000-000000000000/tweets",
    )
    assert_404(r)
