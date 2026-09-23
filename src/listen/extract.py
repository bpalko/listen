from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .errors import ListenError

FETCH_TIMEOUT_SECONDS = 30
USER_AGENT = "Mozilla/5.0 (compatible; listen/0.1; +local podcast tool)"

_URL_ONLY = re.compile(r"^<?(?:https?://|www\.)\S+>?$", re.IGNORECASE)
_WHITESPACE = re.compile(r"[^\S\n]+")


@dataclass(frozen=True)
class Extracted:
    title: str
    text: str


def as_paragraphs(text: str) -> str:
    """trafilatura puts one block per line; speech splits on blank lines, so widen the gaps."""
    lines = [line.strip() for line in (text or "").splitlines()]
    return "\n\n".join(line for line in lines if line)


def clean_script(text: str) -> str:
    """Collapse whitespace, drop lines that are only a URL, keep paragraph breaks."""
    lines: list[str] = []
    for raw_line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _WHITESPACE.sub(" ", raw_line).strip()
        if line and _URL_ONLY.match(line):
            continue
        lines.append(line)

    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs)


def title_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug, flags=re.IGNORECASE)
    words = [word for word in re.split(r"[-_+]+", slug) if word]
    if words:
        return " ".join(words).strip().capitalize()
    return parsed.netloc or url


def fetch(url: str) -> str:
    import httpx

    try:
        response = httpx.get(
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ListenError(f"{url} returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ListenError(f"could not fetch {url}: {exc}") from exc
    return response.text


def extract_html(html: str, url: str) -> Extracted:
    """Pull the article title and body out of a page. Raises when the body is empty."""
    import trafilatura

    text = trafilatura.extract(
        html,
        url=url,
        favor_precision=True,
        include_comments=False,
        include_tables=False,
        include_images=False,
        include_links=False,
    )
    script = clean_script(as_paragraphs(text or ""))
    if not script:
        raise ListenError(f"no article text found at {url}; nothing was saved")

    title = ""
    try:
        metadata = trafilatura.extract_metadata(html, default_url=url)
    except Exception:
        metadata = None
    if metadata is not None and getattr(metadata, "title", None):
        title = str(metadata.title).strip()

    return Extracted(title=title or title_from_url(url), text=script)


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ListenError("no URL given")
    parsed = urlparse(url)
    if not parsed.scheme:
        return "https://" + url
    if parsed.scheme not in ("http", "https"):
        raise ListenError(f"{url} is not an http or https URL")
    return url


def from_url(url: str) -> Extracted:
    return extract_html(fetch(url), url)
