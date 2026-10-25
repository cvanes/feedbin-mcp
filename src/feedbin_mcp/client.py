"""Thin async wrapper around the Feedbin v2 REST API (https://github.com/feedbin/feedbin-api)."""

from typing import Any

import httpx

from feedbin_mcp.errors import FeedbinError

BASE_URL = "https://api.feedbin.com/v2/"

Json = Any


class FeedbinClient:
    def __init__(self, username: str, password: str, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            auth=(username, password),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=30.0,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # Subscriptions

    async def get_subscriptions(self) -> Json:
        return await self._get("subscriptions.json")

    async def create_subscription(self, feed_url: str) -> httpx.Response:
        response = await self._request("POST", "subscriptions.json", json={"feed_url": feed_url}, ok=(200, 201, 300, 302, 404))
        if response.status_code == 404:
            raise FeedbinError(f"No feed found at {feed_url}.")
        return response

    async def update_subscription(self, subscription_id: int, title: str) -> Json:
        response = await self._request("POST", f"subscriptions/{subscription_id}/update.json", json={"title": title})
        return response.json()

    async def delete_subscription(self, subscription_id: int) -> None:
        await self._request("DELETE", f"subscriptions/{subscription_id}.json")

    # Entries

    async def get_entries(self, params: dict[str, Any]) -> Json:
        return await self._get("entries.json", params)

    async def get_feed_entries(self, feed_id: int, params: dict[str, Any]) -> Json:
        response = await self._request("GET", f"feeds/{feed_id}/entries.json", params=params, ok=(200, 404))
        if response.status_code == 404:
            if params.get("page", 1) > 1:
                return []
            raise FeedbinError(f"Feed {feed_id} not found.")
        return response.json()

    async def get_entry(self, entry_id: int) -> Json:
        return await self._get(f"entries/{entry_id}.json")

    # Unread, starred and recently read entry ids

    async def get_unread_entry_ids(self) -> list[int]:
        return await self._get("unread_entries.json")

    async def mark_unread(self, entry_ids: list[int]) -> list[int]:
        response = await self._request("POST", "unread_entries.json", json={"unread_entries": entry_ids})
        return response.json()

    async def mark_read(self, entry_ids: list[int]) -> list[int]:
        response = await self._request("POST", "unread_entries/delete.json", json={"unread_entries": entry_ids})
        return response.json()

    async def get_starred_entry_ids(self) -> list[int]:
        return await self._get("starred_entries.json")

    async def star(self, entry_ids: list[int]) -> list[int]:
        response = await self._request("POST", "starred_entries.json", json={"starred_entries": entry_ids})
        return response.json()

    async def unstar(self, entry_ids: list[int]) -> list[int]:
        response = await self._request("POST", "starred_entries/delete.json", json={"starred_entries": entry_ids})
        return response.json()

    async def get_recently_read_entry_ids(self) -> list[int]:
        return await self._get("recently_read_entries.json")

    # Taggings (folders) and tags

    async def get_taggings(self) -> Json:
        return await self._get("taggings.json")

    async def create_tagging(self, feed_id: int, name: str) -> Json:
        response = await self._request("POST", "taggings.json", json={"feed_id": feed_id, "name": name}, ok=(200, 201, 302))
        return response.json()

    async def delete_tagging(self, tagging_id: int) -> None:
        await self._request("DELETE", f"taggings/{tagging_id}.json")

    async def rename_tag(self, old_name: str, new_name: str) -> Json:
        response = await self._request("POST", "tags.json", json={"old_name": old_name, "new_name": new_name})
        return response.json()

    async def delete_tag(self, name: str) -> Json:
        response = await self._request("DELETE", "tags.json", json={"name": name})
        return response.json()

    # Saved searches

    async def get_saved_searches(self) -> Json:
        return await self._get("saved_searches.json")

    async def get_saved_search_entry_ids(self, saved_search_id: int) -> list[int]:
        """Returns matching entry ids in result order (Feedbin caps this at 1,000)."""
        return await self._get(f"saved_searches/{saved_search_id}.json")

    async def create_saved_search(self, name: str, query: str) -> int:
        response = await self._request("POST", "saved_searches.json", json={"name": name, "query": query})
        return _created_id(response)

    async def delete_saved_search(self, saved_search_id: int) -> None:
        await self._request("DELETE", f"saved_searches/{saved_search_id}.json")

    # Pages

    async def create_page(self, url: str, title: str | None) -> Json:
        body = {"url": url} | ({"title": title} if title else {})
        response = await self._request("POST", "pages.json", json=body)
        return response.json()

    # Plumbing

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Json:
        response = await self._request("GET", path, params=params)
        return response.json()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Json = None,
        ok: tuple[int, ...] = (200, 201, 204),
    ) -> httpx.Response:
        try:
            response = await self._http.request(method, path, params=_encode_params(params), json=json)
        except httpx.HTTPError as error:
            raise FeedbinError(f"Could not reach Feedbin: {error}") from error
        if response.status_code not in ok:
            raise FeedbinError(_describe_failure(method, path, response))
        return response


def _encode_params(params: dict[str, Any] | None) -> dict[str, str] | None:
    if params is None:
        return None
    return {key: _encode_value(value) for key, value in params.items() if value is not None}


def _encode_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def _created_id(response: httpx.Response) -> int:
    if response.content:
        return response.json()["id"]
    return int(response.headers["Location"].rstrip("/").split("/")[-1].removesuffix(".json"))


def _describe_failure(method: str, path: str, response: httpx.Response) -> str:
    match response.status_code:
        case 401:
            return "Feedbin rejected the credentials. Check FEEDBIN_USERNAME and FEEDBIN_PASSWORD."
        case 403:
            return f"Feedbin denied access to {path} (you may not own or subscribe to it)."
        case 404:
            return f"Not found: {path}."
        case status:
            return f"Feedbin {method} {path} failed with HTTP {status}: {response.text[:200]}"
