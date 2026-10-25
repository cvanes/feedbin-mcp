import os
from dataclasses import dataclass

from feedbin_mcp.errors import FeedbinError


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str


def load_credentials() -> Credentials:
    username = os.environ.get("FEEDBIN_USERNAME", "").strip()
    password = os.environ.get("FEEDBIN_PASSWORD", "")
    if not username or not password:
        raise FeedbinError(
            "Feedbin credentials are not configured. Set FEEDBIN_USERNAME and FEEDBIN_PASSWORD in the MCP server's env configuration."
        )
    return Credentials(username=username, password=password)
