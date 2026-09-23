from __future__ import annotations

import re
import socket
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import feed, net
from .config import Config
from .episodes import Episode, display_title, ready_episodes
from .speech import format_duration

SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
COPY_BLOCK = 64 * 1024

PAGE_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0 auto; padding: 2rem 1.25rem 4rem; max-width: 46rem;
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
p.lede { margin: 0 0 2rem; opacity: .7; }
ul { list-style: none; margin: 0; padding: 0; }
li { padding: 1rem 0; border-top: 1px solid rgba(128,128,128,.3); }
li:last-child { border-bottom: 1px solid rgba(128,128,128,.3); }
.title { font-weight: 600; font-size: 1.05rem; }
.meta { font-size: .85rem; opacity: .65; margin-top: .15rem; }
.notes { font-size: .9rem; opacity: .8; margin-top: .45rem; white-space: pre-wrap; }
a.download {
  display: inline-block; margin-top: .7rem; padding: .5rem .9rem;
  border-radius: .5rem; border: 1px solid currentColor;
  text-decoration: none; font-size: .9rem; font-weight: 600;
}
footer { margin-top: 2.5rem; font-size: .85rem; opacity: .65; }
code { font-size: .85em; word-break: break-all; }
"""


class UnsatisfiableRange(Exception):
    """A Range header that names bytes the file does not have."""

    def __init__(self, size: int) -> None:
        super().__init__(f"range outside 0-{max(size - 1, 0)}")
        self.size = size


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Turn a Range header into inclusive byte offsets. None means serve the whole file."""
    if not header:
        return None
    header = header.strip()
    if not header.lower().startswith("bytes="):
        return None

    first = header[len("bytes=") :].split(",")[0].strip()
    if "-" not in first:
        return None
    start_text, _, end_text = first.partition("-")

    try:
        if not start_text:
            if not end_text:
                return None
            suffix = int(end_text)
            if suffix <= 0 or size == 0:
                raise ValueError(first)
            start = max(size - suffix, 0)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError:
        raise UnsatisfiableRange(size) from None

    if start < 0 or start >= size or end < start:
        raise UnsatisfiableRange(size)
    return start, min(end, size - 1)


def size_label(byte_count: int) -> str:
    megabytes = byte_count / (1024 * 1024)
    if megabytes >= 10:
        return f"{megabytes:.0f} MB"
    return f"{megabytes:.1f} MB"


def render_page(config: Config, episodes: list[Episode], base: str) -> str:
    rows: list[str] = []
    for episode in episodes:
        meta = [
            episode.created_datetime().strftime("%b %d, %Y"),
            format_duration(episode.duration_seconds),
            size_label(episode.bytes),
            episode.kind,
        ]
        notes = escape(episode.notes.strip()) if episode.notes.strip() else ""
        rows.append(
            "<li>"
            f'<div class="title">{escape(display_title(episode))}</div>'
            f'<div class="meta">{escape(" · ".join(meta))}</div>'
            + (f'<div class="notes">{notes}</div>' if notes else "")
            + f'<a class="download" href="{escape(net.episode_url(config, episode.id, base))}" '
            f'download="{escape(episode.id)}.mp3">Download MP3</a>'
            "</li>"
        )

    body = (
        "<ul>" + "".join(rows) + "</ul>"
        if rows
        else "<p>No ready episodes yet. Run <code>listen synth &lt;id&gt;</code> first.</p>"
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Listen</title>"
        f"<style>{PAGE_STYLE}</style></head><body>"
        "<h1>Listen</h1>"
        f"<p class=\"lede\">{len(episodes)} ready episode{'' if len(episodes) == 1 else 's'}. "
        "Tap a download, wait for it to finish, then stop the server.</p>"
        f"{body}"
        f"<footer>Podcast app feed: <code>{escape(net.feed_url(config, base))}</code></footer>"
        "</body></html>\n"
    )


class ListenHandler(BaseHTTPRequestHandler):
    server_version = "listen/0.1"
    protocol_version = "HTTP/1.1"
    config: Config
    base: str
    quiet: bool = False

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        if not self.quiet:
            print(f"  {self.address_string()} {format % args}", flush=True)

    def do_GET(self) -> None:
        self.handle_request(body=True)

    def do_HEAD(self) -> None:
        self.handle_request(body=False)

    def handle_request(self, body: bool) -> None:
        path = unquote(urlsplit(self.path).path)
        prefix = f"/{self.config.token}"
        if path != prefix and not path.startswith(prefix + "/"):
            self.fail(HTTPStatus.NOT_FOUND)
            return

        rest = path[len(prefix) :]
        if rest in ("", "/"):
            self.send_page(body)
        elif rest == "/feed.xml":
            self.send_feed(body)
        elif rest.startswith("/episodes/") and rest.endswith(".mp3"):
            self.send_episode(rest[len("/episodes/") : -len(".mp3")], body)
        else:
            self.fail(HTTPStatus.NOT_FOUND)

    def send_page(self, body: bool) -> None:
        episodes = ready_episodes(self.config)
        payload = render_page(self.config, episodes, self.base).encode("utf-8")
        self.send_bytes(payload, "text/html; charset=utf-8", body)

    def send_feed(self, body: bool) -> None:
        tree = feed.build(self.config, ready_episodes(self.config), self.base)
        payload = feed.to_xml(tree).encode("utf-8")
        self.send_bytes(payload, "application/rss+xml; charset=utf-8", body)

    def send_episode(self, episode_id: str, body: bool) -> None:
        if not SAFE_ID.match(episode_id) or episode_id in {".", ".."}:
            self.fail(HTTPStatus.NOT_FOUND)
            return
        root = self.config.episodes_path.resolve()
        path = (root / episode_id / "audio.mp3").resolve()
        if not path.is_relative_to(root) or not path.is_file():
            self.fail(HTTPStatus.NOT_FOUND)
            return
        self.send_file(path, "audio/mpeg", body)

    def send_bytes(self, payload: bytes, content_type: str, body: bool) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.write(payload)

    def send_file(self, path: Path, content_type: str, body: bool) -> None:
        size = path.stat().st_size
        try:
            span = parse_range(self.headers.get("Range"), size)
        except UnsatisfiableRange:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        start, end = span if span else (0, max(size - 1, 0))
        length = size if span is None else end - start + 1

        self.send_response(HTTPStatus.PARTIAL_CONTENT if span else HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if span:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not body or length == 0:
            return

        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                block = handle.read(min(COPY_BLOCK, remaining))
                if not block:
                    break
                if not self.write(block):
                    return
                remaining -= len(block)

    def write(self, payload: bytes) -> bool:
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return False
        return True

    def fail(self, status: HTTPStatus) -> None:
        message = f"{status.value} {status.phrase}\n".encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(message)))
        self.end_headers()
        self.write(message)


class ListenServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()


def make_server(
    config: Config,
    base: str | None = None,
    host: str = "0.0.0.0",
    port: int | None = None,
    quiet: bool = False,
) -> ListenServer:
    resolved_base = (base or net.base_url(config)).rstrip("/")
    handler = type(
        "BoundListenHandler",
        (ListenHandler,),
        {"config": config, "base": resolved_base, "quiet": quiet},
    )
    return ListenServer((host, config.port if port is None else port), handler)
