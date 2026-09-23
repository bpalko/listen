from __future__ import annotations

import threading
from http.client import HTTPConnection

import pytest

from listen import server
from listen.server import UnsatisfiableRange, parse_range

AUDIO = bytes(range(256)) * 8  # 2048 bytes


@pytest.fixture()
def live(config, ready_episode):
    """A running server on localhost plus a helper that makes requests against it."""
    episode = ready_episode(title="Two-Phase Coffee", audio=AUDIO)
    http = server.make_server(config, base="http://10.0.0.5:8765", host="127.0.0.1", port=0, quiet=True)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()

    port = http.server_address[1]

    def request(path, headers=None, method="GET"):
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    try:
        yield request, config, episode
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def test_parse_range_without_a_header_means_the_whole_file():
    assert parse_range(None, 100) is None
    assert parse_range("", 100) is None


def test_parse_range_reads_a_closed_range():
    assert parse_range("bytes=0-99", 500) == (0, 99)
    assert parse_range("bytes=100-199", 500) == (100, 199)


def test_parse_range_reads_an_open_ended_range():
    assert parse_range("bytes=400-", 500) == (400, 499)


def test_parse_range_reads_a_suffix_range():
    assert parse_range("bytes=-100", 500) == (400, 499)
    assert parse_range("bytes=-900", 500) == (0, 499)


def test_parse_range_clamps_an_end_past_the_file():
    assert parse_range("bytes=490-9999", 500) == (490, 499)


def test_parse_range_takes_the_first_of_several_ranges():
    assert parse_range("bytes=0-9,20-29", 500) == (0, 9)


def test_parse_range_ignores_units_it_does_not_know():
    assert parse_range("items=0-9", 500) is None


def test_parse_range_rejects_a_start_past_the_end_of_the_file():
    with pytest.raises(UnsatisfiableRange):
        parse_range("bytes=500-600", 500)
    with pytest.raises(UnsatisfiableRange):
        parse_range("bytes=99-10", 500)
    with pytest.raises(UnsatisfiableRange):
        parse_range("bytes=-0", 500)


def test_the_page_lists_ready_episodes_with_download_links(live):
    request, config, episode = live
    status, headers, body = request(f"/{config.token}/")

    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    text = body.decode("utf-8")
    assert "Two-Phase Coffee" in text
    assert f"/{config.token}/episodes/{episode.id}.mp3" in text


def test_the_feed_is_served_under_the_token(live):
    request, config, _ = live
    status, headers, body = request(f"/{config.token}/feed.xml")

    assert status == 200
    assert "rss" in headers["Content-Type"] or "xml" in headers["Content-Type"]
    assert b"<rss" in body
    assert b"http://10.0.0.5:8765" in body


def test_a_whole_mp3_comes_back_with_accept_ranges(live):
    request, config, episode = live
    status, headers, body = request(f"/{config.token}/episodes/{episode.id}.mp3")

    assert status == 200
    assert headers["Content-Type"] == "audio/mpeg"
    assert headers["Accept-Ranges"] == "bytes"
    assert headers["Content-Length"] == str(len(AUDIO))
    assert body == AUDIO


def test_a_range_request_gets_a_206_with_just_those_bytes(live):
    request, config, episode = live
    status, headers, body = request(
        f"/{config.token}/episodes/{episode.id}.mp3", {"Range": "bytes=100-199"}
    )

    assert status == 206
    assert headers["Content-Range"] == f"bytes 100-199/{len(AUDIO)}"
    assert headers["Content-Length"] == "100"
    assert body == AUDIO[100:200]


def test_an_open_ended_range_runs_to_the_end_of_the_file(live):
    request, config, episode = live
    start = len(AUDIO) - 10
    status, headers, body = request(
        f"/{config.token}/episodes/{episode.id}.mp3", {"Range": f"bytes={start}-"}
    )

    assert status == 206
    assert headers["Content-Range"] == f"bytes {start}-{len(AUDIO) - 1}/{len(AUDIO)}"
    assert body == AUDIO[start:]


def test_ranges_stitched_together_rebuild_the_file(live):
    request, config, episode = live
    pieces = []
    for start in range(0, len(AUDIO), 512):
        end = min(start + 511, len(AUDIO) - 1)
        status, _, body = request(
            f"/{config.token}/episodes/{episode.id}.mp3", {"Range": f"bytes={start}-{end}"}
        )
        assert status == 206
        pieces.append(body)
    assert b"".join(pieces) == AUDIO


def test_a_range_past_the_end_of_the_file_gets_a_416(live):
    request, config, episode = live
    status, headers, _ = request(
        f"/{config.token}/episodes/{episode.id}.mp3", {"Range": "bytes=99999-"}
    )

    assert status == 416
    assert headers["Content-Range"] == f"bytes */{len(AUDIO)}"


def test_head_returns_the_length_without_a_body(live):
    request, config, episode = live
    status, headers, body = request(
        f"/{config.token}/episodes/{episode.id}.mp3", method="HEAD"
    )

    assert status == 200
    assert headers["Content-Length"] == str(len(AUDIO))
    assert headers["Accept-Ranges"] == "bytes"
    assert body == b""


def test_paths_without_the_token_are_404(live):
    request, config, episode = live
    for path in ("/", "/feed.xml", "/wrong-token/feed.xml", f"/{config.token}/nope"):
        status, _, _ = request(path)
        assert status == 404, path


def test_an_unknown_episode_id_is_404(live):
    request, config, _ = live
    status, _, _ = request(f"/{config.token}/episodes/does-not-exist.mp3")
    assert status == 404


def test_a_traversal_attempt_is_404(live):
    request, config, _ = live
    for path in (
        f"/{config.token}/episodes/..%2F..%2Ffeed.xml",
        f"/{config.token}/episodes/....mp3",
        f"/{config.token}/episodes/..%2Faudio.mp3",
    ):
        status, _, _ = request(path)
        assert status == 404, path


def test_drafts_are_not_listed_on_the_page(config, ready_episode):
    from listen import episodes as episode_store

    ready_episode(title="Ready one", audio=AUDIO)
    episode_store.create(config, kind="source", title="Still a draft", script="text")

    from listen.episodes import ready_episodes

    page = server.render_page(config, ready_episodes(config), "http://10.0.0.5:8765")
    assert "Ready one" in page
    assert "Still a draft" not in page


def test_size_label():
    assert server.size_label(1024 * 1024) == "1.0 MB"
    assert server.size_label(25 * 1024 * 1024) == "25 MB"
