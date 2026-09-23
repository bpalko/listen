from __future__ import annotations

import json

import pytest

from listen import config as config_module
from listen import episodes as episode_store
from listen import net
from listen.errors import ListenError


def test_init_writes_the_config_and_the_data_directory(tmp_path):
    config, created = config_module.init(tmp_path)

    assert created is True
    assert config.path == tmp_path / "listen.toml"
    assert config.episodes_path.is_dir()
    assert config.token


def test_init_defaults_match_the_spec(tmp_path):
    config, _ = config_module.init(tmp_path)
    assert config.model_id == "eleven_multilingual_v2"
    assert config.output_format == "mp3_44100_128"
    assert config.port == 8765
    assert config.data_dir == "data"
    assert config.chunk_chars == 4000
    assert config.base_url == ""


def test_init_is_safe_to_run_twice_and_keeps_the_token(tmp_path):
    first, _ = config_module.init(tmp_path)
    second, created = config_module.init(tmp_path)
    assert created is False
    assert second.token == first.token


def test_init_force_writes_a_new_token(tmp_path):
    first, _ = config_module.init(tmp_path)
    second, created = config_module.init(tmp_path, force=True)
    assert created is True
    assert second.token != first.token


def test_config_round_trips_through_toml(tmp_path):
    written, _ = config_module.init(tmp_path)
    loaded = config_module.load_path(written.path)
    assert loaded == written


def test_load_finds_the_config_in_a_parent_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("LISTEN_CONFIG", raising=False)
    config_module.init(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert config_module.load(nested).root == tmp_path.resolve()


def test_load_without_a_config_says_to_run_init(tmp_path, monkeypatch):
    monkeypatch.delenv("LISTEN_CONFIG", raising=False)
    with pytest.raises(ListenError) as error:
        config_module.load(tmp_path)
    assert "listen init" in str(error.value)


def test_create_writes_the_episode_record_from_the_spec(config):
    episode = episode_store.create(
        config,
        kind=episode_store.KIND_SOURCE,
        title="Two-Phase Coffee",
        script="A paragraph.\n\nAnother one.",
        notes="https://example.com/coffee",
        source_url="https://example.com/coffee",
    )

    record = json.loads(episode.meta_path.read_text(encoding="utf-8"))
    assert set(record) == {
        "id",
        "kind",
        "title",
        "notes",
        "source_url",
        "prompt",
        "created_at",
        "status",
        "bytes",
        "duration_seconds",
    }
    assert record["status"] == "draft"
    assert record["prompt"] is None
    assert record["bytes"] == 0
    assert episode.script_path.read_text(encoding="utf-8") == "A paragraph.\n\nAnother one.\n"


def test_resolve_accepts_a_full_id_or_a_unique_prefix(config):
    episode = episode_store.create(config, kind="source", title="T", script="text")
    assert episode_store.resolve(config, episode.id).id == episode.id
    assert episode_store.resolve(config, episode.id[:8]).id == episode.id


def test_resolve_on_an_unknown_id(config):
    with pytest.raises(ListenError):
        episode_store.resolve(config, "nope")


def test_an_id_stays_stable_when_the_audio_is_rebuilt(config, ready_episode):
    episode = ready_episode()
    first_id = episode.id
    episode.status = episode_store.STATUS_DRAFT
    episode.save()
    reloaded = episode_store.resolve(config, first_id)
    assert reloaded.id == first_id


def test_ready_needs_the_audio_file_on_disk(config, ready_episode):
    episode = ready_episode()
    assert episode.is_ready
    episode.audio_path.unlink()
    assert not episode_store.load(episode.directory).is_ready


def test_base_url_prefers_the_config_override(config):
    from dataclasses import replace

    overridden = replace(config, base_url="http://listen.local:9000")
    assert net.base_url(overridden) == "http://listen.local:9000"


def test_base_url_falls_back_to_a_lan_address_never_localhost(config):
    base = net.base_url(config)
    assert base.startswith("http://")
    assert "localhost" not in base
    assert base.endswith(f":{config.port}")


def test_urls_all_sit_under_the_token(config):
    base = "http://10.0.0.5:8765"
    assert net.page_url(config, base) == f"{base}/{config.token}/"
    assert net.feed_url(config, base) == f"{base}/{config.token}/feed.xml"
    assert net.episode_url(config, "abc", base) == f"{base}/{config.token}/episodes/abc.mp3"
