"""FR5: Follow/unfollow other users.

POST /api/v1/users/{id}/follow?follower_id= → 200, counters increment
DELETE /api/v1/users/{id}/follow?follower_id= → 200, counters decrement
Duplicate follow → idempotent 200
Self-follow → 422
404 for unknown users
After follow, timeline includes followee's tweets
"""

import time

from verify.acceptance.conftest import (
    assert_404,
    assert_422,
    create_tweet,
    create_user,
    follow_user,
    get_home_timeline,
    get_user_profile,
    unfollow_user,
)


def test_follow_updates_counters(client):
    """Following a user increments both follower and following counts."""
    alice = create_user(client, username="alice5")
    bob = create_user(client, username="bob5")

    result = follow_user(client, bob["user_id"], alice["user_id"])
    assert result["status"] == "following"

    alice_profile = get_user_profile(client, alice["user_id"])
    bob_profile = get_user_profile(client, bob["user_id"])

    assert alice_profile["following_count"] == 1
    assert bob_profile["follower_count"] == 1


def test_unfollow_updates_counters(client):
    """Unfollowing decrements both counters."""
    alice = create_user(client, username="alice6")
    bob = create_user(client, username="bob6")

    follow_user(client, bob["user_id"], alice["user_id"])
    result = unfollow_user(client, bob["user_id"], alice["user_id"])
    assert result["status"] == "unfollowed"

    alice_profile = get_user_profile(client, alice["user_id"])
    bob_profile = get_user_profile(client, bob["user_id"])

    assert alice_profile["following_count"] == 0
    assert bob_profile["follower_count"] == 0


def test_duplicate_follow_idempotent(client):
    """Following the same user twice is idempotent."""
    alice = create_user(client, username="alice7")
    bob = create_user(client, username="bob7")

    follow_user(client, bob["user_id"], alice["user_id"])
    follow_user(client, bob["user_id"], alice["user_id"])

    alice_profile = get_user_profile(client, alice["user_id"])
    assert alice_profile["following_count"] == 1


def test_self_follow_422(client):
    """Following yourself returns 422."""
    user = create_user(client, username="narcissus")
    r = client.post(
        f"/api/v1/users/{user['user_id']}/follow",
        params={"follower_id": user["user_id"]},
    )
    assert_422(r)


def test_follow_unknown_user_404(client):
    """Following a non-existent user returns 404."""
    alice = create_user(client, username="alice8")
    r = client.post(
        "/api/v1/users/00000000-0000-0000-0000-000000000000/follow",
        params={"follower_id": alice["user_id"]},
    )
    assert_404(r)


def test_follow_unknown_follower_404(client):
    """Following with a non-existent follower returns 404."""
    bob = create_user(client, username="bob8")
    r = client.post(
        f"/api/v1/users/{bob['user_id']}/follow",
        params={"follower_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert_404(r)


def test_after_follow_timeline_includes_tweets(client):
    """After following, the follower's home timeline includes the followee's tweets."""
    alice = create_user(client, username="alice9")
    bob = create_user(client, username="bob9")

    # Bob tweets before Alice follows
    t1 = create_tweet(client, bob["user_id"], text="bob's existing tweet")
    time.sleep(0.05)

    # Alice follows Bob — should backfill Bob's tweets into her timeline
    follow_user(client, bob["user_id"], alice["user_id"])

    # Bob tweets again after follow
    time.sleep(0.05)
    t2 = create_tweet(client, bob["user_id"], text="bob's new tweet")

    timeline = get_home_timeline(client, alice["user_id"])
    tweet_ids = [t["tweet_id"] for t in timeline["tweets"]]

    assert t1["tweet_id"] in tweet_ids
    assert t2["tweet_id"] in tweet_ids


def test_unfollow_idempotent(client):
    """Unfollowing someone you don't follow still returns 200."""
    alice = create_user(client, username="alice10")
    bob = create_user(client, username="bob10")

    result = unfollow_user(client, bob["user_id"], alice["user_id"])
    assert result["status"] == "unfollowed"

    alice_profile = get_user_profile(client, alice["user_id"])
    assert alice_profile["following_count"] == 0


def test_follow_multiple_users(client):
    """A user can follow multiple users; counts accumulate correctly."""
    alice = create_user(client, username="alice11")
    bob = create_user(client, username="bob11")
    charlie = create_user(client, username="charlie11")

    follow_user(client, bob["user_id"], alice["user_id"])
    follow_user(client, charlie["user_id"], alice["user_id"])

    alice_profile = get_user_profile(client, alice["user_id"])
    assert alice_profile["following_count"] == 2

    bob_profile = get_user_profile(client, bob["user_id"])
    assert bob_profile["follower_count"] == 1

    charlie_profile = get_user_profile(client, charlie["user_id"])
    assert charlie_profile["follower_count"] == 1
