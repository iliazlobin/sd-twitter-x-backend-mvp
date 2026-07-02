"""FR4: Search tweets by keyword and hashtag.

GET /api/v1/search?q=&cursor= → 200
Finds tweets matching keyword in text
Finds tweets by hashtag name
Results ranked by relevance (ts_rank)
Empty query → empty results
Cursor pagination
"""

from verify.acceptance.conftest import (
    create_tweet,
    create_user,
    search_content,
)


def test_search_by_keyword(client):
    """Searching by a keyword finds matching tweets."""
    user = create_user(client, username="searcher")
    t1 = create_tweet(client, user["user_id"], text="learning rust is fun")
    t2 = create_tweet(client, user["user_id"], text="python is great too")

    results = search_content(client, "rust")
    tweet_ids = {r["tweet_id"] for r in results["results"] if r.get("type") == "tweet"}
    assert t1["tweet_id"] in tweet_ids
    assert t2["tweet_id"] not in tweet_ids


def test_search_by_hashtag_name(client):
    """Searching by a hashtag name finds tweets with that hashtag."""
    user = create_user(client, username="hashtagger")
    create_tweet(client, user["user_id"], text="cool #opensource project")
    create_tweet(client, user["user_id"], text="building #closedsource stuff")

    results = search_content(client, "opensource")

    # Should find the tweet with #opensource
    found = any(
        r.get("type") == "tweet" and "opensource" in str(r.get("text", "")).lower()
        for r in results["results"]
    )
    assert found, f"Expected to find #opensource tweet in results: {results}"


def test_search_empty_query(client):
    """Empty query returns empty results (200)."""
    results = search_content(client, "")
    assert results["results"] == []


def test_search_no_results(client):
    """A query matching nothing returns empty results."""
    results = search_content(client, "xyznonexistent12345")
    assert results["results"] == []


def test_search_cursor_pagination(client):
    """Cursor pagination works for search results."""
    user = create_user(client, username="searchpager")

    # Create tweets with the same keyword to fill multiple pages
    for i in range(25):
        create_tweet(client, user["user_id"], text=f"pagination test tweet {i}")

    page1 = search_content(client, "pagination")
    assert len(page1["results"]) == 20
    assert page1["next_cursor"] is not None

    page2 = search_content(client, "pagination", cursor=page1["next_cursor"])
    assert len(page2["results"]) >= 1
    assert page2["next_cursor"] is None

    p1_ids = {r.get("tweet_id") for r in page1["results"] if r.get("tweet_id")}
    p2_ids = {r.get("tweet_id") for r in page2["results"] if r.get("tweet_id")}
    assert p1_ids.isdisjoint(p2_ids)


def test_search_results_have_author(client):
    """Search results include author info for tweet results."""
    user = create_user(client, username="searchauthor")
    create_tweet(client, user["user_id"], text="unique_author_test_tweet")

    results = search_content(client, "unique_author_test_tweet")
    tweet_results = [r for r in results["results"] if r.get("type") == "tweet"]
    assert len(tweet_results) >= 1

    tweet = tweet_results[0]
    assert "author" in tweet
    assert tweet["author"]["user_id"] == user["user_id"]
    assert tweet["author"]["username"] == "searchauthor"
