from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from listen import config as config_module  # noqa: E402
from listen import episodes as episode_store  # noqa: E402


@pytest.fixture()
def config(tmp_path):
    made, _ = config_module.init(tmp_path)
    return made


@pytest.fixture()
def ready_episode(config):
    """A ready episode with a small but real mp3-shaped payload on disk."""

    def make(title="An episode", notes="Some notes", audio=b"ID3" + b"\x00" * 997, **fields):
        episode = episode_store.create(
            config,
            kind=fields.pop("kind", episode_store.KIND_SOURCE),
            title=title,
            script="Hello.\n\nThere.\n",
            notes=notes,
            **fields,
        )
        episode.audio_path.write_bytes(audio)
        episode.bytes = len(audio)
        episode.duration_seconds = 754
        episode.status = episode_store.STATUS_READY
        episode.save()
        return episode

    return make
