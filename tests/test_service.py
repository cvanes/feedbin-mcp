import json

import httpx
import pytest
from conftest import entry, subscription, tagging

from feedbin_mcp.errors import FeedbinError
from feedbin_mcp.service import TEMP_SEARCH_NAME

pytestmark = pytest.mark.anyio


@pytest.fixture
def library(fake):
    fake.on("GET", "subscriptions.json", [subscription(1, 10, "Zeta"), subscription(2, 20, "alpha"), subscription(3, 30, "Loose")])
    fake.on("GET", "taggings.json", [tagging(100, 10, "Tech"), tagging(101, 20, "Tech"), tagging(102, 20, "News")])
    return fake


async def test_list_folders_groups_feeds_and_puts_unfiled_last(library, service):
    folders = await service.list_folders()

    assert [(f["name"], [feed["title"] for feed in f["feeds"]]) for f in folders] == [
        ("News", ["alpha"]),
        ("Tech", ["alpha", "Zeta"]),
        (None, ["Loose"]),
    ]


async def test_list_feeds_filters_by_folder_case_insensitively(library, service):
    feeds = await service.list_feeds("tech")

    assert [feed["feed_id"] for feed in feeds] == [20, 10]


async def test_unknown_folder_lists_existing_folders(library, service):
    with pytest.raises(FeedbinError, match="Existing folders: News, Tech"):
        await service.list_feeds("Sport")


async def test_folder_entries_merge_feeds_newest_first(library, service):
    library.on("GET", "feeds/10/entries.json", [entry(1, 10, "2026-10-03T00:00:00Z"), entry(2, 10, "2026-10-01T00:00:00Z")])
    library.on("GET", "feeds/20/entries.json", [entry(3, 20, "2026-10-02T00:00:00Z")])

    result = await service.list_entries(folder="Tech", per_page=2)

    assert [e["id"] for e in result["entries"]] == [1, 3]
    assert result["next_page"] == 2
    assert library.sent("GET", "feeds/10/entries.json")[0].url.params["read"] == "false"


async def test_folder_entries_page_beyond_the_api_page_size_limit(library, service):
    def two_full_pages(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json=[entry(page * 1000 + i, 10) for i in range(100)] if page <= 2 else [])

    library.on("GET", "feeds/10/entries.json", two_full_pages)
    library.on("GET", "feeds/20/entries.json", two_full_pages)

    result = await service.list_entries(folder="Tech", page=2, per_page=100)

    requested_sizes = {int(r.url.params["per_page"]) for r in library.requests if "/feeds/" in r.url.path}
    assert requested_sizes == {100}
    assert len(result["entries"]) == 100
    assert result["next_page"] == 3


async def test_folder_entries_last_page_has_no_next_page(library, service):
    library.on("GET", "feeds/10/entries.json", [entry(1, 10)])
    library.on("GET", "feeds/20/entries.json", [entry(2, 20)])

    result = await service.list_entries(folder="Tech", per_page=2)

    assert len(result["entries"]) == 2
    assert result["next_page"] is None


async def test_starred_entries_request_starred_filter(library, service):
    library.on("GET", "entries.json", [entry(5, 10)])

    result = await service.list_entries(status="starred")

    assert result["entries"][0]["feed_title"] == "Zeta"
    assert library.sent("GET", "entries.json")[0].url.params["starred"] == "true"
    assert result["next_page"] is None


async def test_get_entries_preserves_requested_order(library, service):
    library.on("GET", "entries.json", [entry(1, 10), entry(2, 10)])

    entries = await service.get_entries([2, 1])

    assert [e["id"] for e in entries] == [2, 1]


async def test_search_scopes_to_folder_and_removes_temporary_search(library, service):
    library.on("POST", "saved_searches.json", lambda request: httpx.Response(201, json={"id": 9}))
    library.on("GET", "saved_searches/9.json", [1])
    library.on("GET", "entries.json", [entry(1, 10)])
    library.on("DELETE", "saved_searches/9.json", lambda request: httpx.Response(204))

    result = await service.search("rust", folder="Tech")

    assert library.bodies("POST", "saved_searches.json") == [{"name": TEMP_SEARCH_NAME, "query": "rust (feed_id:10 OR feed_id:20)"}]
    assert [e["id"] for e in result["entries"]] == [1]
    assert len(library.sent("DELETE", "saved_searches/9.json")) == 1


async def test_search_removes_temporary_search_when_fetch_fails(library, service):
    library.on("POST", "saved_searches.json", lambda request: httpx.Response(201, json={"id": 9}))
    library.on("GET", "saved_searches/9.json", lambda request: httpx.Response(500))
    library.on("DELETE", "saved_searches/9.json", lambda request: httpx.Response(204))

    with pytest.raises(FeedbinError):
        await service.search("rust")

    assert len(library.sent("DELETE", "saved_searches/9.json")) == 1


async def test_list_saved_searches_hides_temporary_searches(fake, service):
    fake.on("GET", "saved_searches.json", [{"id": 1, "name": "Mine", "query": "q"}, {"id": 2, "name": TEMP_SEARCH_NAME, "query": "q"}])

    searches = await service.list_saved_searches()

    assert [s["id"] for s in searches] == [1]


async def test_mark_read_splits_large_requests_into_api_sized_batches(fake, service):
    fake.on("POST", "unread_entries/delete.json", lambda request: httpx.Response(200, json=json.loads(request.content)["unread_entries"]))

    count = await service.mark_read(list(range(2500)))

    assert [len(body["unread_entries"]) for body in fake.bodies("POST", "unread_entries/delete.json")] == [1000, 1000, 500]
    assert count == 2500


async def test_mark_all_read_for_feed_pages_through_unread_entries(library, service):
    def feed_entries(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json=[entry(page * 1000 + i, 10) for i in range(100 if page == 1 else 3)])

    library.on("GET", "feeds/10/entries.json", feed_entries)
    library.on("POST", "unread_entries/delete.json", lambda request: httpx.Response(200, json=list(range(103))))

    count = await service.mark_all_read(feed_id=10)

    assert len(library.bodies("POST", "unread_entries/delete.json")[0]["unread_entries"]) == 103
    assert count == 103


async def test_unsubscribe_deletes_subscription_for_feed(library, service):
    library.on("DELETE", "subscriptions/2.json", lambda request: httpx.Response(204))

    await service.unsubscribe(20)

    assert len(library.sent("DELETE", "subscriptions/2.json")) == 1


async def test_unsubscribe_from_unknown_feed_fails(library, service):
    with pytest.raises(FeedbinError, match="not subscribed to feed 99"):
        await service.unsubscribe(99)


async def test_subscribe_files_new_feed_in_folder(fake, service):
    fake.on("POST", "subscriptions.json", lambda request: httpx.Response(201, json=subscription(5, 50, "New")))
    fake.on("POST", "taggings.json", lambda request: httpx.Response(201, json=tagging(1, 50, "Tech")))

    result = await service.subscribe("new.test", folder="Tech")

    assert result["subscribed"] is True
    assert fake.bodies("POST", "taggings.json") == [{"feed_id": 50, "name": "Tech"}]


async def test_subscribe_returns_choices_when_site_has_several_feeds(fake, service):
    choices = [{"feed_url": "https://a.test/rss", "title": "A"}, {"feed_url": "https://a.test/atom", "title": "A Atom"}]
    fake.on("POST", "subscriptions.json", lambda request: httpx.Response(300, json=choices))

    result = await service.subscribe("a.test")

    assert result["subscribed"] is False
    assert result["choices"] == choices


async def test_remove_feed_from_folder_deletes_matching_tagging(library, service):
    library.on("DELETE", "taggings/102.json", lambda request: httpx.Response(204))

    await service.remove_feed_from_folder(20, "news")

    assert len(library.sent("DELETE", "taggings/102.json")) == 1


async def test_search_returns_requested_page_of_matches_with_total(library, service):
    library.on("POST", "saved_searches.json", lambda request: httpx.Response(201, json={"id": 9}))
    library.on("GET", "saved_searches/9.json", list(range(1, 46)))
    library.on(
        "GET", "entries.json", lambda request: httpx.Response(200, json=[entry(int(i), 10) for i in request.url.params["ids"].split(",")])
    )
    library.on("DELETE", "saved_searches/9.json", lambda request: httpx.Response(204))

    result = await service.search("rust", page=2, per_page=20)

    assert [e["id"] for e in result["entries"]] == list(range(21, 41))
    assert (result["total"], result["next_page"]) == (45, 3)
