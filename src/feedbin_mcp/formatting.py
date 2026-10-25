"""Turns raw Feedbin entries into compact, LLM-friendly dictionaries."""

import re
from html.parser import HTMLParser
from typing import Any

SUMMARY_CHARS = 300
BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "tr"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    extractor = _TextExtractor()
    extractor.feed(html)
    text = "".join(extractor.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def format_entry(
    entry: dict[str, Any],
    feed_titles: dict[int, str],
    include_content: bool = False,
    max_content_chars: int = 20_000,
) -> dict[str, Any]:
    formatted = {
        "id": entry["id"],
        "feed_id": entry.get("feed_id"),
        "feed_title": feed_titles.get(entry.get("feed_id")),
        "title": entry.get("title"),
        "author": entry.get("author"),
        "url": entry.get("url"),
        "published": entry.get("published"),
        "created_at": entry.get("created_at"),
    }
    if include_content:
        formatted["content"] = truncate(html_to_text(entry.get("content")), max_content_chars)
    else:
        summary = html_to_text(entry.get("summary") or entry.get("content"))
        formatted["summary"] = truncate(summary, SUMMARY_CHARS)
    return formatted
