"""MCP tool definitions. Each tool delegates to FeedbinService and surfaces Feedbin errors as tool errors."""

import functools
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, ParamSpec, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from feedbin_mcp.client import FeedbinClient
from feedbin_mcp.config import load_credentials
from feedbin_mcp.errors import FeedbinError
from feedbin_mcp.service import EntryStatus, FeedbinService

P = ParamSpec("P")
R = TypeVar("R")

mcp = MCPServer(
    name="feedbin",
    instructions=(
        "Tools for the Feedbin RSS reader. Feedbin calls folders 'tags'; feeds are identified by feed_id and "
        "entries (articles) by entry id. Use list_folders or list_feeds to discover feed ids, list_entries to "
        "browse unread/starred items and search_entries for full-text search. Entry lists return short summaries; "
        "call get_entries for full article text."
    ),
)

EntryIds = Annotated[list[int], Field(description="Entry ids, as returned by the entry listing tools.", min_length=1)]
FeedId = Annotated[int, Field(description="Feed id, as returned by list_feeds or list_folders.")]
FolderName = Annotated[str, Field(description="Folder (Feedbin tag) name; matched case-insensitively.")]
OptionalFeedId = Annotated[int | None, Field(description="Limit to this feed id.")]
OptionalFolder = Annotated[str | None, Field(description="Limit to feeds in this folder.")]
Page = Annotated[int, Field(description="Page number, starting at 1.", ge=1)]
PerPage = Annotated[int, Field(description="Entries per page.", ge=1, le=100)]
IncludeContent = Annotated[bool, Field(description="Include full article text instead of a short summary.")]


@functools.cache
def get_service() -> FeedbinService:
    credentials = load_credentials()
    return FeedbinService(FeedbinClient(credentials.username, credentials.password))


def feedbin_tool(*, read_only: bool, destructive: bool = False):
    """Registers an async tool, converting FeedbinError into a ToolError so its message reaches the client."""

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await fn(*args, **kwargs)
            except FeedbinError as error:
                raise ToolError(str(error)) from error

        annotations = ToolAnnotations(read_only_hint=read_only, destructive_hint=destructive, open_world_hint=True)
        mcp.tool(annotations=annotations)(wrapper)
        return wrapper

    return decorator


# Folders and feeds


@feedbin_tool(read_only=True)
async def list_folders() -> list[dict[str, Any]]:
    """List all folders with the feeds inside each. Feeds not in any folder are grouped under name null."""
    return await get_service().list_folders()


@feedbin_tool(read_only=True)
async def list_feeds(folder: OptionalFolder = None) -> list[dict[str, Any]]:
    """List subscribed feeds with their feed_id, title, URLs and folders, optionally only those in one folder."""
    return await get_service().list_feeds(folder)


@feedbin_tool(read_only=False)
async def subscribe(
    feed_url: Annotated[str, Field(description="Feed URL or website URL (Feedbin discovers the feed).")],
    folder: Annotated[str | None, Field(description="Optionally put the new feed in this folder (created if needed).")] = None,
) -> dict[str, Any]:
    """Subscribe to a feed. If the site exposes several feeds, returns the choices to subscribe to instead."""
    return await get_service().subscribe(feed_url, folder)


@feedbin_tool(read_only=False, destructive=True)
async def unsubscribe(feed_id: FeedId) -> str:
    """Unsubscribe from a feed."""
    await get_service().unsubscribe(feed_id)
    return f"Unsubscribed from feed {feed_id}."


@feedbin_tool(read_only=False)
async def rename_feed(feed_id: FeedId, title: Annotated[str, Field(description="New display title.")]) -> dict[str, Any]:
    """Set a custom title for a feed."""
    return await get_service().rename_feed(feed_id, title)


@feedbin_tool(read_only=False)
async def add_feed_to_folder(
    feed_id: FeedId, folder: Annotated[str, Field(description="Folder name; created if it does not exist.")]
) -> str:
    """Put a feed in a folder. A feed can be in several folders."""
    await get_service().add_feed_to_folder(feed_id, folder)
    return f"Added feed {feed_id} to folder '{folder}'."


@feedbin_tool(read_only=False)
async def remove_feed_from_folder(feed_id: FeedId, folder: FolderName) -> str:
    """Take a feed out of a folder (the subscription itself is kept)."""
    await get_service().remove_feed_from_folder(feed_id, folder)
    return f"Removed feed {feed_id} from folder '{folder}'."


@feedbin_tool(read_only=False)
async def rename_folder(folder: FolderName, new_name: Annotated[str, Field(description="New folder name.")]) -> str:
    """Rename a folder."""
    await get_service().rename_folder(folder, new_name)
    return f"Renamed folder '{folder}' to '{new_name}'."


@feedbin_tool(read_only=False, destructive=True)
async def delete_folder(folder: FolderName) -> str:
    """Delete a folder. Its feeds stay subscribed but are no longer filed in it."""
    await get_service().delete_folder(folder)
    return f"Deleted folder '{folder}'."


# Entries


@feedbin_tool(read_only=True)
async def list_entries(
    status: Annotated[EntryStatus, Field(description="Which entries: unread, read, starred or all.")] = "unread",
    feed_id: OptionalFeedId = None,
    folder: OptionalFolder = None,
    since: Annotated[
        str | None,
        Field(description="Only entries added to Feedbin after this ISO 8601 timestamp; pass an entry's created_at exactly as returned."),
    ] = None,
    page: Page = 1,
    per_page: PerPage = 20,
    include_content: IncludeContent = False,
) -> dict[str, Any]:
    """List entries newest first, e.g. unread items, starred items, or everything from a feed or folder.

    Returns entries plus next_page (null when there are no more)."""
    return await get_service().list_entries(status, feed_id, folder, since, page, per_page, include_content)


@feedbin_tool(read_only=True)
async def get_entries(entry_ids: EntryIds, include_content: IncludeContent = True) -> list[dict[str, Any]]:
    """Fetch specific entries by id, with full article text by default."""
    return await get_service().get_entries(entry_ids, include_content)


@feedbin_tool(read_only=True)
async def search_entries(
    query: Annotated[
        str,
        Field(
            description=(
                'Feedbin search query. Supports AND/OR/NOT, "exact phrases", field filters such as title:, '
                "content:, author:, url:, link:example.com, is:unread, is:starred, published:>now-7d, "
                "type:podcast, and sort:asc|desc|relevance."
            )
        ),
    ],
    feed_id: OptionalFeedId = None,
    folder: OptionalFolder = None,
    page: Page = 1,
    per_page: PerPage = 20,
    include_content: IncludeContent = False,
) -> dict[str, Any]:
    """Full-text search across all feeds, optionally limited to one feed or folder.

    Returns entries, total matches (Feedbin caps this at 1,000) and next_page (null when there are no more)."""
    return await get_service().search(query, feed_id, folder, page, per_page, include_content)


@feedbin_tool(read_only=True)
async def list_recently_read(
    limit: Annotated[int, Field(description="Maximum entries to return.", ge=1, le=100)] = 20,
    include_content: IncludeContent = False,
) -> list[dict[str, Any]]:
    """List entries you have recently read, most recent first."""
    return await get_service().recently_read(limit, include_content)


@feedbin_tool(read_only=True)
async def get_counts() -> dict[str, int]:
    """Total number of unread and starred entries."""
    return await get_service().counts()


@feedbin_tool(read_only=False)
async def save_page(
    url: Annotated[str, Field(description="Web page URL to save to Feedbin for reading later.")],
    title: Annotated[str | None, Field(description="Fallback title if Feedbin cannot find one.")] = None,
) -> dict[str, Any]:
    """Save a web page to Feedbin as an entry (read later)."""
    return await get_service().save_page(url, title)


# Read and starred state


@feedbin_tool(read_only=False)
async def mark_as_read(entry_ids: EntryIds) -> str:
    """Mark entries as read."""
    count = await get_service().mark_read(entry_ids)
    return f"Marked {count} entries as read."


@feedbin_tool(read_only=False)
async def mark_as_unread(entry_ids: EntryIds) -> str:
    """Mark entries as unread."""
    count = await get_service().mark_unread(entry_ids)
    return f"Marked {count} entries as unread."


@feedbin_tool(read_only=False)
async def mark_all_as_read(feed_id: OptionalFeedId = None, folder: OptionalFolder = None) -> str:
    """Mark every unread entry as read: in one feed, in one folder, or (with neither) across all feeds."""
    count = await get_service().mark_all_read(feed_id, folder)
    return f"Marked {count} entries as read."


@feedbin_tool(read_only=False)
async def star_entries(entry_ids: EntryIds) -> str:
    """Star entries."""
    count = await get_service().star(entry_ids)
    return f"Starred {count} entries."


@feedbin_tool(read_only=False)
async def unstar_entries(entry_ids: EntryIds) -> str:
    """Remove the star from entries."""
    count = await get_service().unstar(entry_ids)
    return f"Unstarred {count} entries."


# Saved searches


@feedbin_tool(read_only=True)
async def list_saved_searches() -> list[dict[str, Any]]:
    """List your saved searches (id, name, query)."""
    return await get_service().list_saved_searches()


@feedbin_tool(read_only=True)
async def run_saved_search(
    saved_search_id: Annotated[int, Field(description="Saved search id from list_saved_searches.")],
    page: Page = 1,
    per_page: PerPage = 20,
    include_content: IncludeContent = False,
) -> dict[str, Any]:
    """Get the entries matching a saved search, with total matches and next_page."""
    return await get_service().run_saved_search(saved_search_id, page, per_page, include_content)


@feedbin_tool(read_only=False)
async def create_saved_search(
    name: Annotated[str, Field(description="Display name.")],
    query: Annotated[str, Field(description="Feedbin search query (same syntax as search_entries).")],
) -> str:
    """Create a saved search."""
    saved_search_id = await get_service().create_saved_search(name, query)
    return f"Created saved search {saved_search_id}."


@feedbin_tool(read_only=False, destructive=True)
async def delete_saved_search(saved_search_id: Annotated[int, Field(description="Saved search id.")]) -> str:
    """Delete a saved search."""
    await get_service().delete_saved_search(saved_search_id)
    return f"Deleted saved search {saved_search_id}."
