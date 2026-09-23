from __future__ import annotations

import pytest

from listen.errors import ListenError
from listen.extract import (
    as_paragraphs,
    clean_script,
    extract_html,
    normalize_url,
    title_from_url,
)

HTML = """
<html><head><title>Two-Phase Coffee</title>
<meta property="og:title" content="Two-Phase Coffee"></head>
<body><article>
<h1>Two-Phase Coffee</h1>
<p>The barista    writes your name on the cup
and starts the drink before you have paid.</p>
<p>https://example.com/only-a-link</p>
<p>That is optimistic, and it usually works.</p>
</article></body></html>
"""


def test_clean_script_collapses_whitespace_within_a_paragraph():
    assert clean_script("one   two\tthree\n four") == "one two three four"


def test_clean_script_keeps_one_blank_line_between_paragraphs():
    assert clean_script("first\n\n\n\nsecond\n") == "first\n\nsecond"


def test_clean_script_drops_lines_that_are_only_a_url():
    text = "Read this.\nhttps://example.com/a\nwww.example.com\n<https://example.com/b>\nDone."
    assert clean_script(text) == "Read this. Done."


def test_clean_script_keeps_a_url_inside_a_sentence():
    assert clean_script("See https://example.com/a for more.") == "See https://example.com/a for more."


def test_clean_script_on_empty_input():
    assert clean_script("") == ""
    assert clean_script("   \n\n  \n") == ""


def test_as_paragraphs_turns_each_extracted_block_into_a_paragraph():
    assert as_paragraphs("one\ntwo\n\nthree") == "one\n\ntwo\n\nthree"


def test_title_from_url_uses_the_last_path_segment():
    assert title_from_url("https://example.com/ramblings/18_starbucks.html") == "18 starbucks"
    assert title_from_url("https://example.com/") == "example.com"


def test_normalize_url_adds_a_scheme():
    assert normalize_url("example.com/a") == "https://example.com/a"
    assert normalize_url(" https://example.com/a ") == "https://example.com/a"


def test_normalize_url_rejects_other_schemes():
    with pytest.raises(ListenError):
        normalize_url("ftp://example.com/a")
    with pytest.raises(ListenError):
        normalize_url("   ")


def test_extract_html_returns_a_title_and_a_clean_script():
    extracted = extract_html(HTML, "https://example.com/coffee")
    assert extracted.title == "Two-Phase Coffee"
    assert "barista writes your name" in extracted.text
    assert "only-a-link" not in extracted.text
    assert "\n\n" in extracted.text


def test_extract_html_fails_on_a_page_with_no_article():
    with pytest.raises(ListenError) as error:
        extract_html("<html><head><title>Nothing</title></head><body></body></html>",
                     "https://example.com/empty")
    assert "no article text" in str(error.value)
    assert "nothing was saved" in str(error.value)
