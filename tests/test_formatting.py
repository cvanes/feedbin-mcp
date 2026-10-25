from feedbin_mcp.formatting import format_entry, html_to_text


def test_html_to_text_strips_markup_and_keeps_paragraphs():
    html = "<p>Hello <b>world</b> &amp; friends</p><script>evil()</script><p>Second</p>"

    text = html_to_text(html)

    assert text == "Hello world & friends\n\nSecond"


def test_format_entry_truncates_summary_and_names_feed():
    raw = {"id": 1, "feed_id": 7, "title": "T", "summary": "x" * 500}

    formatted = format_entry(raw, {7: "My Feed"})

    assert formatted["feed_title"] == "My Feed"
    assert len(formatted["summary"]) == 301
    assert "content" not in formatted


def test_format_entry_includes_plain_text_content_when_requested():
    raw = {"id": 1, "feed_id": 7, "content": "<p>Full <i>article</i></p>"}

    formatted = format_entry(raw, {}, include_content=True)

    assert formatted["content"] == "Full article"
