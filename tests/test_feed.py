from __future__ import annotations

import xml.etree.ElementTree as ET

from listen import episodes as episode_store
from listen import feed

ITUNES = feed.ITUNES_NS


def parse(text: str) -> ET.Element:
    return ET.fromstring(text)


def test_feed_has_the_rss_2_shape_and_channel_fields(config, ready_episode):
    ready_episode(title="An episode")
    xml = feed.to_xml(feed.build(config, episode_store.ready_episodes(config), "http://10.0.0.5:8765"))
    root = parse(xml)

    assert root.tag == "rss"
    assert root.get("version") == "2.0"
    channel = root.find("channel")
    assert channel.findtext("title") == "Listen"
    assert channel.findtext("language") == "en"
    assert channel.findtext(f"{{{ITUNES}}}block") == "Yes"
    assert "xmlns:itunes" in xml


def test_feed_item_carries_every_required_element(config, ready_episode):
    episode = ready_episode(title="Two-Phase Coffee", notes="https://example.com/coffee")
    root = parse(
        feed.to_xml(feed.build(config, episode_store.ready_episodes(config), "http://10.0.0.5:8765"))
    )
    item = root.find("channel/item")

    assert item.findtext("title") == "Two-Phase Coffee"
    assert item.findtext("description") == "https://example.com/coffee"
    guid = item.find("guid")
    assert guid.text == episode.id
    assert guid.get("isPermaLink") == "false"
    assert item.findtext("pubDate")
    assert item.findtext(f"{{{ITUNES}}}duration") == "12:34"

    enclosure = item.find("enclosure")
    assert enclosure.get("type") == "audio/mpeg"
    assert enclosure.get("length") == str(episode.bytes)
    assert enclosure.get("url") == f"http://10.0.0.5:8765/{config.token}/episodes/{episode.id}.mp3"


def test_feed_enclosure_urls_use_the_lan_base_and_the_token(config, ready_episode):
    ready_episode()
    xml = feed.to_xml(feed.build(config, episode_store.ready_episodes(config), "http://192.168.1.20:8765"))
    assert "localhost" not in xml
    assert "127.0.0.1" not in xml
    assert f"/{config.token}/episodes/" in xml


def test_feed_lists_ready_episodes_newest_first(config, ready_episode):
    older = ready_episode(title="Older")
    older.created_at = "2024-01-01T00:00:00+00:00"
    older.save()
    newer = ready_episode(title="Newer")
    newer.created_at = "2025-06-01T00:00:00+00:00"
    newer.save()

    root = parse(feed.to_xml(feed.build(config, episode_store.ready_episodes(config), "http://10.0.0.5:8765")))
    titles = [item.findtext("title") for item in root.findall("channel/item")]
    assert titles == ["Newer", "Older"]


def test_feed_leaves_out_drafts(config, ready_episode):
    ready_episode(title="Ready one")
    episode_store.create(config, kind="source", title="Still a draft", script="text")

    root = parse(feed.to_xml(feed.build(config, episode_store.ready_episodes(config), "http://10.0.0.5:8765")))
    titles = [item.findtext("title") for item in root.findall("channel/item")]
    assert titles == ["Ready one"]


def test_write_puts_the_feed_at_data_feed_xml(config, ready_episode):
    ready_episode()
    path = feed.write(config, "http://10.0.0.5:8765")
    assert path == config.data_path / "feed.xml"
    assert path.read_text(encoding="utf-8").startswith("<?xml")


def test_an_empty_feed_is_still_valid_xml(config):
    root = parse(feed.to_xml(feed.build(config, [], "http://10.0.0.5:8765")))
    assert root.findall("channel/item") == []
