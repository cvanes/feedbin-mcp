import pytest
from mcp.server.mcpserver.exceptions import ToolError

from feedbin_mcp.server import get_service, mcp

pytestmark = pytest.mark.anyio


async def test_feedbin_errors_reach_the_client_with_their_message(monkeypatch):
    monkeypatch.delenv("FEEDBIN_USERNAME", raising=False)
    monkeypatch.delenv("FEEDBIN_PASSWORD", raising=False)
    get_service.cache_clear()

    with pytest.raises(ToolError, match="FEEDBIN_USERNAME"):
        await mcp.call_tool("list_folders", {})
