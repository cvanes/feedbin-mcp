import httpx
import pytest

from feedbin_mcp.errors import FeedbinError

pytestmark = pytest.mark.anyio


async def test_rejected_credentials_raise_helpful_error(fake, client):
    fake.on("GET", "subscriptions.json", lambda request: httpx.Response(401))

    with pytest.raises(FeedbinError, match="rejected the credentials"):
        await client.get_subscriptions()


async def test_requests_use_basic_auth(fake, client):
    fake.on("GET", "taggings.json", [])

    await client.get_taggings()

    assert fake.requests[0].headers["Authorization"].startswith("Basic ")


async def test_created_saved_search_id_falls_back_to_location_header(fake, client):
    location = {"Location": "https://api.feedbin.com/v2/saved_searches/42.json"}
    fake.on("POST", "saved_searches.json", lambda request: httpx.Response(201, headers=location))

    saved_search_id = await client.create_saved_search("name", "query")

    assert saved_search_id == 42


async def test_boolean_and_list_params_use_feedbin_encoding(fake, client):
    fake.on("GET", "entries.json", [])

    await client.get_entries({"read": False, "ids": [1, 2], "since": None})

    assert dict(fake.requests[0].url.params) == {"read": "false", "ids": "1,2"}


async def test_writes_send_the_content_type_feedbin_requires(fake, client):
    fake.on("POST", "starred_entries.json", [1])

    await client.star([1])

    assert fake.requests[0].headers["Content-Type"] == "application/json; charset=utf-8"


async def test_subscribing_to_url_without_feed_explains_why(fake, client):
    fake.on("POST", "subscriptions.json", lambda request: httpx.Response(404))

    with pytest.raises(FeedbinError, match="No feed found at nothing.test"):
        await client.create_subscription("nothing.test")
