"""The MVP loop end to end: add, synth, serve, download. No live API keys involved."""

from __future__ import annotations

import shutil
import subprocess
import threading
import xml.etree.ElementTree as ET
from http.client import HTTPConnection

import pytest

from listen import cli
from listen import config as config_module
from listen import episodes as episode_store
from listen import extract, lesson, server, speech

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg and ffprobe are required to join audio",
)

ARTICLE = """
<html><head><title>Starbucks Does Not Use Two-Phase Commit</title></head><body><article>
<p>The barista writes your name on the cup and starts your drink before you have paid.</p>
<p>https://example.com/footer-link</p>
<p>That is optimistic concurrency, and the shop reconciles at the register.</p>
</article></body></html>
"""

LESSON_REPLY = """Title: Replication Lag

A read hits the follower a moment after the write hit the leader.

The follower applies a stream of changes in order, so it is always a little behind.

It fails when a user saves their profile and then reads a stale copy of it.

Where would a stale read be invisible in your system? What would you measure to notice it?
"""


@pytest.fixture(scope="module")
def tone_mp3(tmp_path_factory) -> bytes:
    """A real one-second mp3, so ffmpeg concat and ffprobe do actual work."""
    path = tmp_path_factory.mktemp("tone") / "tone.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "libmp3lame", "-b:a", "128k", str(path),
        ],
        check=True,
    )
    return path.read_bytes()


class FakeElevenLabs:
    def __init__(self, audio: bytes):
        self.audio = audio
        self.texts: list[str] = []
        self.text_to_speech = self

    def convert(self, *, text, **_):
        self.texts.append(text)
        return iter([self.audio])


@pytest.fixture()
def workspace(tmp_path, monkeypatch, tone_mp3):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LISTEN_CONFIG", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "a-fake-key-for-tests")
    monkeypatch.setattr(extract, "fetch", lambda url: ARTICLE)
    monkeypatch.setattr(lesson, "request_script", lambda prompt, settings=None: LESSON_REPLY)
    fake = FakeElevenLabs(tone_mp3)
    monkeypatch.setattr(speech, "make_client", lambda: fake)

    assert cli.main(["init"]) == 0
    return config_module.load(tmp_path), fake


def only_episode(config, kind: str):
    found = [e for e in episode_store.all_episodes(config) if e.kind == kind]
    assert len(found) == 1
    return found[0]


def test_a_url_becomes_a_draft_then_a_downloadable_mp3(workspace, capsys):
    config, _ = workspace

    assert cli.main(["add", "url", "https://example.com/coffee"]) == 0
    episode = only_episode(config, episode_store.KIND_SOURCE)
    assert episode.status == "draft"
    assert episode.title == "Starbucks Does Not Use Two-Phase Commit"
    assert episode.source_url == "https://example.com/coffee"
    script = episode.script_path.read_text(encoding="utf-8")
    assert "barista writes your name" in script
    assert "footer-link" not in script
    assert not episode.audio_path.exists(), "add must not synthesize"

    # An edit to the script is what gets spoken.
    episode.script_path.write_text("First paragraph.\n\nSecond paragraph.\n", encoding="utf-8")
    assert cli.main(["synth", episode.id[:8]]) == 0

    done = episode_store.resolve(config, episode.id)
    assert done.status == "ready"
    assert done.audio_path.is_file()
    assert done.bytes == done.audio_path.stat().st_size > 0
    assert done.duration_seconds >= 1
    assert done.id == episode.id, "the id survives synthesis"

    feed_xml = config.feed_path.read_text(encoding="utf-8")
    assert done.id in feed_xml

    # The phone downloads it from the page, whole file and by range.
    http = server.make_server(config, base="http://10.0.0.5:8765", host="127.0.0.1", port=0, quiet=True)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        port = http.server_address[1]

        def get(path, headers=None):
            connection = HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request("GET", path, headers=headers or {})
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()

        status, _, page = get(f"/{config.token}/")
        assert status == 200
        assert f"/{config.token}/episodes/{done.id}.mp3" in page.decode("utf-8")

        status, _, whole = get(f"/{config.token}/episodes/{done.id}.mp3")
        assert status == 200
        assert whole == done.audio_path.read_bytes()

        status, headers, head = get(
            f"/{config.token}/episodes/{done.id}.mp3", {"Range": "bytes=0-1023"}
        )
        assert status == 206
        assert headers["Content-Range"] == f"bytes 0-1023/{done.bytes}"
        assert head == whole[:1024]
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)

    # Stopping the server leaves the episode on disk.
    assert done.audio_path.is_file()


def test_a_lesson_prompt_becomes_an_episode_on_the_same_feed(workspace, monkeypatch):
    config, _ = workspace
    monkeypatch.setenv("LISTEN_LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("LISTEN_LLM_API_KEY", "a-fake-key-for-tests")
    monkeypatch.setenv("LISTEN_LLM_MODEL", "a-model")

    assert cli.main(["add", "url", "https://example.com/coffee"]) == 0
    assert cli.main(["add", "lesson", "explain", "replication", "lag"]) == 0

    episode = only_episode(config, episode_store.KIND_LESSON)
    assert episode.title == "Replication Lag"
    assert episode.prompt == "explain replication lag"
    assert episode.notes.splitlines() == [
        "Where would a stale read be invisible in your system?",
        "What would you measure to notice it?",
    ]
    assert "Title:" not in episode.script_path.read_text(encoding="utf-8")

    for kind in (episode_store.KIND_SOURCE, episode_store.KIND_LESSON):
        assert cli.main(["synth", only_episode(config, kind).id]) == 0

    root = ET.fromstring(config.feed_path.read_text(encoding="utf-8"))
    titles = [item.findtext("title") for item in root.findall("channel/item")]
    assert set(titles) == {"Replication Lag", "Starbucks Does Not Use Two-Phase Commit"}
    assert len(root.findall("channel/item")) == 2


def test_a_failed_chunk_leaves_a_draft_and_keeps_what_was_written(workspace, tone_mp3, monkeypatch):
    config, _ = workspace
    assert cli.main(["add", "url", "https://example.com/coffee"]) == 0
    episode = only_episode(config, episode_store.KIND_SOURCE)
    episode.script_path.write_text("a" * 300 + "\n\n" + "b" * 300 + "\n", encoding="utf-8")

    class HalfBrokenClient:
        def __init__(self):
            self.calls = 0
            self.text_to_speech = self

        def convert(self, *, text, **_):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("elevenlabs is having a day")
            return iter([tone_mp3])

    config.path.write_text(
        config.path.read_text(encoding="utf-8").replace("chunk_chars = 4000", "chunk_chars = 400"),
        encoding="utf-8",
    )
    broken = HalfBrokenClient()
    monkeypatch.setattr(speech, "make_client", lambda: broken)
    assert cli.main(["synth", episode.id]) == 1

    still_draft = episode_store.resolve(config, episode.id)
    assert still_draft.status == "draft"
    assert not still_draft.audio_path.exists()
    assert (still_draft.chunks_path / "000.mp3").is_file(), "the written chunk stays"

    # A later synth skips the chunk that already exists and finishes the episode.
    good = FakeElevenLabs(tone_mp3)
    monkeypatch.setattr(speech, "make_client", lambda: good)
    assert cli.main(["synth", episode.id]) == 0

    assert len(good.texts) == 1, "only the missing chunk is respoken"
    assert episode_store.resolve(config, episode.id).status == "ready"
