# feedbin-mcp

An [MCP](https://modelcontextprotocol.io) server for the [Feedbin](https://feedbin.com) RSS reader. It lets an AI assistant browse folders and feeds, read and search entries, star items, mark things read or unread and manage subscriptions.

## Credentials

Feedbin's API uses HTTP Basic auth with your Feedbin **email and password**. It has no API keys. The server reads them from environment variables, which you set in your MCP client's config. They are never stored in this repo.

| Variable           | Value                   |
| ------------------ | ----------------------- |
| `FEEDBIN_USERNAME` | Your Feedbin login email |
| `FEEDBIN_PASSWORD` | Your Feedbin password    |

## Adding the server

Requires [uv](https://docs.astral.sh/uv/).

### Claude Code

```bash
claude mcp add feedbin --scope user \
  -e FEEDBIN_USERNAME=you@example.com \
  -e FEEDBIN_PASSWORD='your-password' \
  -- uv run --directory /path/to/feedbin-mcp feedbin-mcp
```

`--scope user` keeps the credentials in your user config (`~/.claude.json`) rather than in a project's `.mcp.json`. If you do want a shared `.mcp.json`, reference variables from your shell instead of writing the values:

```json
{
  "mcpServers": {
    "feedbin": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/feedbin-mcp", "feedbin-mcp"],
      "env": {
        "FEEDBIN_USERNAME": "${FEEDBIN_USERNAME}",
        "FEEDBIN_PASSWORD": "${FEEDBIN_PASSWORD}"
      }
    }
  }
}
```

### Claude Desktop and other clients

Add the same block to the client's MCP config (for Claude Desktop, `claude_desktop_config.json`) with your real values in `env`.

## Tools

| Area | Tools |
| --- | --- |
| Folders and feeds | `list_folders`, `list_feeds`, `subscribe`, `unsubscribe`, `rename_feed`, `add_feed_to_folder`, `remove_feed_from_folder`, `rename_folder`, `delete_folder` |
| Reading | `list_entries` (unread / read / starred / all, by feed or folder, paginated), `get_entries` (full text), `search_entries`, `list_recently_read`, `get_counts`, `save_page` |
| State | `mark_as_read`, `mark_as_unread`, `mark_all_as_read` (all, per feed or per folder), `star_entries`, `unstar_entries` |
| Saved searches | `list_saved_searches`, `run_saved_search`, `create_saved_search`, `delete_saved_search` |

Notes:

- Feedbin calls folders "tags". Folder names are matched case-insensitively.
- Feeds are referred to by `feed_id` everywhere. The server works out subscription ids for you.
- Entry listings return a short plain-text summary. Use `get_entries` or `include_content=true` for the full article.
- The Feedbin API has no direct search endpoint, so `search_entries` creates a temporary saved search, reads its results and deletes it. It supports [Feedbin's search syntax](https://feedbin.com/help/search-syntax/), e.g. `title:rust is:unread published:>now-7d`.

## Development

```bash
uv sync
uv run pytest
```
