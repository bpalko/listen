from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import format_datetime
from pathlib import Path
from xml.dom import minidom

from . import net
from .config import Config
from .episodes import Episode, display_title, ready_episodes
from .speech import format_duration

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CHANNEL_TITLE = "Listen"
CHANNEL_DESCRIPTION = "Articles and lessons, read aloud, on your own network."

ET.register_namespace("itunes", ITUNES_NS)


def _itunes(tag: str) -> str:
    return f"{{{ITUNES_NS}}}{tag}"


def _text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    element = ET.SubElement(parent, tag)
    element.text = value
    return element


def item_description(episode: Episode) -> str:
    notes = (episode.notes or "").strip()
    if notes:
        return notes
    return display_title(episode)


def build(config: Config, episodes: list[Episode], base: str | None = None) -> ET.ElementTree:
    base = (base or net.base_url(config)).rstrip("/")

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    _text(channel, "title", CHANNEL_TITLE)
    _text(channel, "link", net.page_url(config, base))
    _text(channel, "description", CHANNEL_DESCRIPTION)
    _text(channel, "language", "en")
    _text(channel, _itunes("block"), "Yes")

    for episode in episodes:
        item = ET.SubElement(channel, "item")
        _text(item, "title", display_title(episode))
        _text(item, "description", item_description(episode))
        guid = _text(item, "guid", episode.id)
        guid.set("isPermaLink", "false")
        _text(item, "pubDate", format_datetime(episode.created_datetime()))
        _text(item, _itunes("duration"), format_duration(episode.duration_seconds))
        ET.SubElement(
            item,
            "enclosure",
            {
                "url": net.episode_url(config, episode.id, base),
                "length": str(episode.bytes),
                "type": "audio/mpeg",
            },
        )

    return ET.ElementTree(rss)


def to_xml(tree: ET.ElementTree) -> str:
    raw = ET.tostring(tree.getroot(), encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")
    return pretty.decode("utf-8")


def write(config: Config, base: str | None = None) -> Path:
    """Rebuild feed.xml from the ready episodes, newest first."""
    tree = build(config, ready_episodes(config), base)
    config.feed_path.parent.mkdir(parents=True, exist_ok=True)
    config.feed_path.write_text(to_xml(tree), encoding="utf-8")
    return config.feed_path
