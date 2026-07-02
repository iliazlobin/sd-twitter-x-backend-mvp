"""FR2: View a home timeline of tweets from followed users.

GET /api/v1/timeline/home?user_id=&cursor= → 200
Timeline contains tweets from followed users (not unfollowed)
Reverse-chronological ordering
Cursor pagination (20 tweets/page)
Empty timeline for new user with no follows
404 for unknown user
"""

import time

from verify.acceptance.conftest import (
    assert_404,
    create_tweet,
    create_user,
    follow_user,
    get_home_timeline,
    unfollow_user,
)


def test_timeline_returns_followed_users_tweets(client):
    """Home timeline includes tweets from followed users."""
    alice = create_user(client, username="alice")
    bob = create_user(client, username="bob")
    charlie = create_user(client, username="charlie")

    # Alice follows Bob
    follow_user(client, bob["user_id"], alice["user_id"])

    # Bob tweets; Charlie tweets
    t1 = create_tweet(client, bob["user_id"], text="bob's first tweet")
    t2 = create_tweet(client, charlie["user_id"], text="charlie's tweet")

    # Small delay so timestamps differ
    time.sleep(0.1)

    # Alice's timeline should contain Bob's tweet but not Charlie's
    timeline = get_home_timeline(client, alice["user_id"])
    tweet_ids = [t["tweet_id"] for t in timeline["tweets"]]
    assert t1["tweet_id"] in tweet_ids
    assert t2["tweet_id"] not in tweet_ids


def test_timeline_reverse_chronological(client):
    """Timeline tweets are ordered newest first."""
    alice = create_user(client, username="alice")
    bob = create_user(client, username="bob")

    follow_user(client, bob["user_id"], alice["user_id"])

    t1 = create_tweet(client, bob["user_id"], text="first")
    time.sleep(0.15)
    t2 = create_tweet(client, bob["user_id"], text="second")
    time.sleep(0.15)
    t3 = create_tweet(client, bob["user_id"], text="third")

    timeline = get_home_timeline(client, alice["user_id"])
    tweet_ids = [t["tweet_id"] for t in timeline["tweets"]]

    # Should be third, second, first
    assert tweet_ids[0] == t3["tweet_id"]
    assert tweet_ids[1] == t2["tweet_id"]
    assert tweet_ids[2] == t1["tweet_id"]


def test_timeline_cursor_pagination(client):
    """Cursor pagination returns pages of 20 and a valid next_cursor."""
    alice = create_user(client, username="alice")
    bob = create_user(client, username="bob")

    follow_user(client, bob["user_id"], alice["user_id"])

    # Create 25 tweets — should span 2 pages
    for i in range(25):
        create_tweet(client, bob["user_id"], text=f"tweet {i}")
        time.sleep(0.02)

    page1 = get_home_timeline(client, alice["user_id"])
    assert len(page1["tweets"]) == 20
    assert page1["next_cursor"] is not None

    page2 = get_home_timeline(client, alice["user_id"], cursor=page1["next_cursor"])
    assert len(page2["tweets"]) == 5
    assert page2["next_cursor"] is None

    # No overlap between pages
    p1_ids = {t["tweet_id"] for t in page1["tweets"]}
    p2_ids = {t["tweet_id"] for t in page2["tweets"]}
    assert p1_ids.isdisjoint(p2_ids)


def test_timeline_empty_for_new_user(client):
    """A new user with no follows sees an empty timeline."""
    user = create_user(client)
    timeline = get_home_timeline(client, user["user_id"])
    assert timeline["tweets"] == []
    assert timeline["next_cursor"] is None


def test_timeline_unknown_user_404(client):
    """Requesting timeline for a non-existent user returns 404."""
    r = client.get(
        "/api/v1/timeline/home",
        params={"user_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert_404(r)


def test_timeline_excludes_unfollowed(client):
    """After unfollowing, the user's tweets no longer appear."""
    alice = create_user(client, username="alice2")
    bob = create_user(client, username="bob2")

    follow_user(client, bob["user_id"], alice["user_id"])
    create_tweet(client, bob["user_id"], text="while following")

    # Verify tweet appears
    t1 = get_home_timeline(client, alice["user_id"])
    assert len(t1["tweets"]) == 1

    unfollow_user(client, bob["user_id"], alice["user_id"])

    # After unfollow, tweet no longer appears
    t2 = get_home_timeline(client, alice["user_id"])
    assert len(t2["tweets"]) == 0


def test_timeline_includes_tweet_author_info(client):
    """Each tweet in the timeline includes author details."""
    alice = create_user(client, username="alice3")
    bob = create_user(client, username="bob3")

    follow_user(client, bob["user_id"], alice["user_id"])
    create_tweet(client, bob["user_id"], text="with author info")

    timeline = get_home_timeline(client, alice["user_id"])
    tweet = timeline["tweets"][0]
    assert tweet["author"]["user_id"] == bob["user_id"]
    assert tweet["author"]["username"] == "bob3"
