"""Feedbin operations expressed in reader terms (folders, feeds, entries) on top of the raw API client.

Feedbin calls folders "tags": a folder is the set of taggings that share a name. Tools work with
feed ids throughout; subscription ids are resolved internally where the API needs them.
"""

import asyncio
from collections.abc import Iterable
from typing import Any, Literal

from feedbin_mcp.client import FeedbinClient
from feedbin_mcp.errors import FeedbinError
from feedbin_mcp.formatting import format_entry

EntryStatus = Literal["unread", "read", "starred", "all"]

ENTRIES_PER_REQUEST = 100
IDS_PER_UPDATE = 1000
FEED_PAGE_SIZE = 100
TEMP_SEARCH_NAME = "feedbin-mcp temporary search"

STATUS_PARAMS: dict[EntryStatus, dict[str, bool]] = {
    "unread": {"read": False},
    "read": {"read": True},
    "starred": {"starred": True},
    "all": {},
}


class FeedbinService:
    def __init__(self, client: FeedbinClient):
        self._client = client

    # Folders and feeds

    async def list_folders(self) -> list[dict[str, Any]]:
        subscriptions, taggings = await asyncio.gather(self._client.get_subscriptions(), self._client.get_taggings())
        feeds = {sub["feed_id"]: _feed_summary(sub) for sub in subscriptions}
        folders: dict[str, list[dict[str, Any]]] = {}
        for tagging in taggings:
            if tagging["feed_id"] in feeds:
                folders.setdefault(tagging["name"], []).append(feeds[tagging["feed_id"]])
        filed = {tagging["feed_id"] for tagging in taggings}
        result = [{"name": name, "feeds": _by_title(items)} for name, items in sorted(folders.items())]
        unfiled = [feed for feed_id, feed in feeds.items() if feed_id not in filed]
        if unfiled:
            result.append({"name": None, "feeds": _by_title(unfiled)})
        return result

    async def list_feeds(self, folder: str | None = None) -> list[dict[str, Any]]:
        subscriptions, taggings = await asyncio.gather(self._client.get_subscriptions(), self._client.get_taggings())
        folders_by_feed: dict[int, list[str]] = {}
        for tagging in taggings:
            folders_by_feed.setdefault(tagging["feed_id"], []).append(tagging["name"])
        feeds = [
            _feed_summary(sub) | {"feed_url": sub.get("feed_url"), "folders": sorted(folders_by_feed.get(sub["feed_id"], []))}
            for sub in subscriptions
        ]
        if folder is not None:
            name = _resolve_folder_name(folder, taggings)
            feeds = [feed for feed in feeds if name in feed["folders"]]
        return _by_title(feeds)

    async def subscribe(self, feed_url: str, folder: str | None = None) -> dict[str, Any]:
        response = await self._client.create_subscription(feed_url)
        if response.status_code == 300:
            return {
                "subscribed": False,
                "message": "Multiple feeds found; subscribe to one of these feed_urls.",
                "choices": response.json(),
            }
        subscription = response.json()
        if folder:
            await self._client.create_tagging(subscription["feed_id"], folder)
        return {
            "subscribed": True,
            "already_subscribed": response.status_code == 302,
            "feed": _feed_summary(subscription),
            "folder": folder,
        }

    async def unsubscribe(self, feed_id: int) -> None:
        subscription = await self._subscription_for_feed(feed_id)
        await self._client.delete_subscription(subscription["id"])

    async def rename_feed(self, feed_id: int, title: str) -> dict[str, Any]:
        subscription = await self._subscription_for_feed(feed_id)
        return _feed_summary(await self._client.update_subscription(subscription["id"], title))

    async def add_feed_to_folder(self, feed_id: int, folder: str) -> None:
        await self._client.create_tagging(feed_id, folder)

    async def remove_feed_from_folder(self, feed_id: int, folder: str) -> None:
        taggings = await self._client.get_taggings()
        name = _resolve_folder_name(folder, taggings)
        matches = [t for t in taggings if t["feed_id"] == feed_id and t["name"] == name]
        if not matches:
            raise FeedbinError(f"Feed {feed_id} is not in folder '{name}'.")
        await self._client.delete_tagging(matches[0]["id"])

    async def rename_folder(self, folder: str, new_name: str) -> None:
        name = _resolve_folder_name(folder, await self._client.get_taggings())
        await self._client.rename_tag(name, new_name)

    async def delete_folder(self, folder: str) -> None:
        name = _resolve_folder_name(folder, await self._client.get_taggings())
        await self._client.delete_tag(name)

    # Reading entries

    async def list_entries(
        self,
        status: EntryStatus = "unread",
        feed_id: int | None = None,
        folder: str | None = None,
        since: str | None = None,
        page: int = 1,
        per_page: int = 20,
        include_content: bool = False,
    ) -> dict[str, Any]:
        params = STATUS_PARAMS[status] | {"since": since}
        if folder is not None:
            entries, has_more = await self._folder_entries(folder, params, page, per_page)
        else:
            page_params = params | {"page": page, "per_page": per_page}
            if feed_id is not None:
                entries = await self._client.get_feed_entries(feed_id, page_params)
            else:
                entries = await self._client.get_entries(page_params)
            has_more = len(entries) == per_page
        return {
            "entries": await self._format(entries, include_content),
            "next_page": page + 1 if has_more else None,
        }

    async def get_entries(self, entry_ids: list[int], include_content: bool = True) -> list[dict[str, Any]]:
        entries = await self._fetch_entries(entry_ids)
        return await self._format(entries, include_content)

    async def search(
        self,
        query: str,
        feed_id: int | None = None,
        folder: str | None = None,
        page: int = 1,
        per_page: int = 20,
        include_content: bool = False,
    ) -> dict[str, Any]:
        full_query = _scoped_query(query, await self._search_scope(feed_id, folder))
        search_id = await self._client.create_saved_search(TEMP_SEARCH_NAME, full_query)
        try:
            entry_ids = await self._client.get_saved_search_entry_ids(search_id)
        finally:
            await self._client.delete_saved_search(search_id)
        return {"query": full_query} | await self._page_of_ids(entry_ids, page, per_page, include_content)

    async def recently_read(self, limit: int = 20, include_content: bool = False) -> list[dict[str, Any]]:
        entry_ids = (await self._client.get_recently_read_entry_ids())[:limit]
        return await self.get_entries(entry_ids, include_content)

    async def counts(self) -> dict[str, int]:
        unread, starred = await asyncio.gather(self._client.get_unread_entry_ids(), self._client.get_starred_entry_ids())
        return {"unread": len(unread), "starred": len(starred)}

    async def save_page(self, url: str, title: str | None = None) -> dict[str, Any]:
        entry = await self._client.create_page(url, title)
        return format_entry(entry, {})

    # Saved searches

    async def list_saved_searches(self) -> list[dict[str, Any]]:
        searches = await self._client.get_saved_searches()
        return [search for search in searches if search["name"] != TEMP_SEARCH_NAME]

    async def run_saved_search(
        self, saved_search_id: int, page: int = 1, per_page: int = 20, include_content: bool = False
    ) -> dict[str, Any]:
        entry_ids = await self._client.get_saved_search_entry_ids(saved_search_id)
        return await self._page_of_ids(entry_ids, page, per_page, include_content)

    async def create_saved_search(self, name: str, query: str) -> int:
        return await self._client.create_saved_search(name, query)

    async def delete_saved_search(self, saved_search_id: int) -> None:
        await self._client.delete_saved_search(saved_search_id)

    # Read and starred state

    async def mark_read(self, entry_ids: list[int]) -> int:
        return await _in_batches(self._client.mark_read, entry_ids)

    async def mark_unread(self, entry_ids: list[int]) -> int:
        return await _in_batches(self._client.mark_unread, entry_ids)

    async def star(self, entry_ids: list[int]) -> int:
        return await _in_batches(self._client.star, entry_ids)

    async def unstar(self, entry_ids: list[int]) -> int:
        return await _in_batches(self._client.unstar, entry_ids)

    async def mark_all_read(self, feed_id: int | None = None, folder: str | None = None) -> int:
        if feed_id is not None:
            entry_ids = await self._unread_ids_for_feeds([feed_id])
        elif folder is not None:
            entry_ids = await self._unread_ids_for_feeds(await self._feed_ids_in_folder(folder))
        else:
            entry_ids = await self._client.get_unread_entry_ids()
        return await self.mark_read(entry_ids)

    # Helpers

    async def _folder_entries(self, folder: str, params: dict[str, Any], page: int, per_page: int) -> tuple[list[dict[str, Any]], bool]:
        """Merges per-feed results, as Feedbin has no folder entries endpoint. Fetches one extra entry to detect more pages."""
        feed_ids = await self._feed_ids_in_folder(folder)
        end = page * per_page
        results = await asyncio.gather(*(self._feed_entries(feed_id, params, limit=end + 1) for feed_id in feed_ids))
        merged = sorted((entry for entries in results for entry in entries), key=lambda e: e["created_at"], reverse=True)
        return merged[end - per_page : end], len(merged) > end

    async def _unread_ids_for_feeds(self, feed_ids: Iterable[int]) -> list[int]:
        results = await asyncio.gather(*(self._feed_entries(feed_id, {"read": False}) for feed_id in feed_ids))
        return [entry["id"] for entries in results for entry in entries]

    async def _feed_entries(self, feed_id: int, params: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
        """Pages through a feed's entries (the API caps pages at 100) until `limit` entries or the last page."""
        entries: list[dict[str, Any]] = []
        page = 1
        while limit is None or len(entries) < limit:
            batch = await self._client.get_feed_entries(feed_id, params | {"page": page, "per_page": FEED_PAGE_SIZE})
            entries.extend(batch)
            if len(batch) < FEED_PAGE_SIZE:
                break
            page += 1
        return entries[:limit]

    async def _page_of_ids(self, entry_ids: list[int], page: int, per_page: int, include_content: bool) -> dict[str, Any]:
        end = page * per_page
        return {
            "total": len(entry_ids),
            "entries": await self.get_entries(entry_ids[end - per_page : end], include_content),
            "next_page": page + 1 if len(entry_ids) > end else None,
        }

    async def _fetch_entries(self, entry_ids: list[int]) -> list[dict[str, Any]]:
        batches = [entry_ids[i : i + ENTRIES_PER_REQUEST] for i in range(0, len(entry_ids), ENTRIES_PER_REQUEST)]
        results = await asyncio.gather(*(self._client.get_entries({"ids": batch, "per_page": len(batch)}) for batch in batches))
        by_id = {entry["id"]: entry for entries in results for entry in entries}
        return [by_id[entry_id] for entry_id in entry_ids if entry_id in by_id]

    async def _search_scope(self, feed_id: int | None, folder: str | None) -> list[int]:
        if feed_id is not None:
            return [feed_id]
        if folder is not None:
            return await self._feed_ids_in_folder(folder)
        return []

    async def _feed_ids_in_folder(self, folder: str) -> list[int]:
        taggings = await self._client.get_taggings()
        name = _resolve_folder_name(folder, taggings)
        return [tagging["feed_id"] for tagging in taggings if tagging["name"] == name]

    async def _subscription_for_feed(self, feed_id: int) -> dict[str, Any]:
        for subscription in await self._client.get_subscriptions():
            if subscription["feed_id"] == feed_id:
                return subscription
        raise FeedbinError(f"You are not subscribed to feed {feed_id}.")

    async def _format(self, entries: list[dict[str, Any]], include_content: bool) -> list[dict[str, Any]]:
        if not entries:
            return []
        subscriptions = await self._client.get_subscriptions()
        feed_titles = {sub["feed_id"]: sub["title"] for sub in subscriptions}
        return [format_entry(entry, feed_titles, include_content) for entry in entries]


def _feed_summary(subscription: dict[str, Any]) -> dict[str, Any]:
    return {"feed_id": subscription["feed_id"], "title": subscription.get("title"), "site_url": subscription.get("site_url")}


def _by_title(feeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(feeds, key=lambda feed: (feed.get("title") or "").lower())


def _scoped_query(query: str, feed_ids: list[int]) -> str:
    if not feed_ids:
        return query
    return f"{query} ({' OR '.join(f'feed_id:{feed_id}' for feed_id in feed_ids)})"


def _resolve_folder_name(folder: str, taggings: list[dict[str, Any]]) -> str:
    names = {tagging["name"] for tagging in taggings}
    for name in names:
        if name.casefold() == folder.casefold():
            return name
    raise FeedbinError(f"No folder named '{folder}'. Existing folders: {', '.join(sorted(names)) or 'none'}.")


async def _in_batches(update, entry_ids: list[int]) -> int:
    """Applies an id-list update in chunks of the API's per-request limit; returns how many ids it applied to."""
    batches = [entry_ids[i : i + IDS_PER_UPDATE] for i in range(0, len(entry_ids), IDS_PER_UPDATE)]
    results = await asyncio.gather(*(update(batch) for batch in batches))
    return sum(len(result) for result in results)
