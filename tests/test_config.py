import pytest

from feedbin_mcp.config import load_credentials
from feedbin_mcp.errors import FeedbinError


def test_missing_credentials_explain_which_env_vars_to_set(monkeypatch):
    monkeypatch.delenv("FEEDBIN_USERNAME", raising=False)
    monkeypatch.setenv("FEEDBIN_PASSWORD", "secret")

    with pytest.raises(FeedbinError, match="FEEDBIN_USERNAME and FEEDBIN_PASSWORD"):
        load_credentials()


def test_credentials_are_read_from_env(monkeypatch):
    monkeypatch.setenv("FEEDBIN_USERNAME", "me@example.com")
    monkeypatch.setenv("FEEDBIN_PASSWORD", "secret")

    credentials = load_credentials()

    assert (credentials.username, credentials.password) == ("me@example.com", "secret")
