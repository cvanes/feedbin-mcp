import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from feedbin_mcp.client import FeedbinClient
from feedbin_mcp.service import FeedbinService

Route = Callable[[httpx.Request], httpx.Response] | Any


class FakeFeedbin:
    """Routes requests by method and path (relative to /v2/); static routes return their value as JSON."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Route] = {}
        self.requests: list[httpx.Request] = []

    def on(self, method: str, path: str, route: Route) -> None:
        self.routes[(method, path)] = route

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get((request.method, request.url.path.removeprefix("/v2/")))
        if route is None:
            return httpx.Response(404)
        if callable(route):
            return route(request)
        return httpx.Response(200, json=route)

    def sent(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == f"/v2/{path}"]

    def bodies(self, method: str, path: str) -> list[Any]:
        return [json.loads(r.content) for r in self.sent(method, path)]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake() -> FakeFeedbin:
    return FakeFeedbin()


@pytest.fixture
def client(fake: FakeFeedbin) -> FeedbinClient:
    return FeedbinClient("me@example.com", "secret", transport=httpx.MockTransport(fake.handle))


@pytest.fixture
def service(client: FeedbinClient) -> FeedbinService:
    return FeedbinService(client)


def subscription(sub_id: int, feed_id: int, title: str) -> dict[str, Any]:
    return {
        "id": sub_id,
        "feed_id": feed_id,
        "title": title,
        "feed_url": f"https://{feed_id}.test/feed",
        "site_url": f"https://{feed_id}.test",
    }


def tagging(tagging_id: int, feed_id: int, name: str) -> dict[str, Any]:
    return {"id": tagging_id, "feed_id": feed_id, "name": name}


def entry(entry_id: int, feed_id: int, created_at: str = "2026-10-01T00:00:00Z", **fields: Any) -> dict[str, Any]:
    return {
        "id": entry_id,
        "feed_id": feed_id,
        "title": f"Entry {entry_id}",
        "created_at": created_at,
        "summary": "",
        "content": "",
    } | fields
