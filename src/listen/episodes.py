from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .errors import ListenError

KIND_SOURCE = "source"
KIND_LESSON = "lesson"
STATUS_DRAFT = "draft"
STATUS_READY = "ready"


@dataclass
class Episode:
    id: str
    kind: str
    title: str = ""
    notes: str = ""
    source_url: str | None = None
    prompt: str | None = None
    created_at: str = ""
    status: str = STATUS_DRAFT
    bytes: int = 0
    duration_seconds: int = 0
    directory: Path = field(default=Path("."), compare=False, repr=False)

    @property
    def meta_path(self) -> Path:
        return self.directory / "meta.json"

    @property
    def script_path(self) -> Path:
        return self.directory / "script.txt"

    @property
    def chunks_path(self) -> Path:
        return self.directory / "chunks"

    @property
    def audio_path(self) -> Path:
        return self.directory / "audio.mp3"

    @property
    def is_ready(self) -> bool:
        return self.status == STATUS_READY and self.audio_path.is_file()

    def record(self) -> dict:
        data = asdict(self)
        data.pop("directory")
        return data

    def save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(
            json.dumps(self.record(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def created_datetime(self) -> datetime:
        try:
            parsed = datetime.fromisoformat(self.created_at)
        except ValueError:
            return datetime.fromtimestamp(0, tz=timezone.utc)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create(
    config: Config,
    kind: str,
    title: str,
    script: str,
    notes: str = "",
    source_url: str | None = None,
    prompt: str | None = None,
) -> Episode:
    episode_id = str(uuid.uuid4())
    episode = Episode(
        id=episode_id,
        kind=kind,
        title=title,
        notes=notes,
        source_url=source_url,
        prompt=prompt,
        created_at=now_iso(),
        status=STATUS_DRAFT,
        directory=config.episodes_path / episode_id,
    )
    episode.directory.mkdir(parents=True, exist_ok=True)
    episode.script_path.write_text(script.rstrip("\n") + "\n", encoding="utf-8")
    episode.save()
    return episode


def load(directory: Path) -> Episode:
    meta_path = directory / "meta.json"
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ListenError(f"no episode record at {meta_path}") from exc
    except json.JSONDecodeError as exc:
        raise ListenError(f"{meta_path} is not valid JSON: {exc}") from exc

    return Episode(
        id=str(raw.get("id", directory.name)),
        kind=str(raw.get("kind", KIND_SOURCE)),
        title=str(raw.get("title", "")),
        notes=str(raw.get("notes", "")),
        source_url=raw.get("source_url"),
        prompt=raw.get("prompt"),
        created_at=str(raw.get("created_at", "")),
        status=str(raw.get("status", STATUS_DRAFT)),
        bytes=int(raw.get("bytes", 0) or 0),
        duration_seconds=int(raw.get("duration_seconds", 0) or 0),
        directory=directory,
    )


def all_episodes(config: Config) -> list[Episode]:
    """Every episode on disk, newest first."""
    root = config.episodes_path
    if not root.is_dir():
        return []
    found = [load(child) for child in sorted(root.iterdir()) if (child / "meta.json").is_file()]
    found.sort(key=lambda episode: (episode.created_datetime(), episode.id), reverse=True)
    return found


def ready_episodes(config: Config) -> list[Episode]:
    return [episode for episode in all_episodes(config) if episode.is_ready]


def resolve(config: Config, episode_id: str) -> Episode:
    """Find an episode by its id or by a unique id prefix."""
    directory = config.episodes_path / episode_id
    if (directory / "meta.json").is_file():
        return load(directory)

    matches = [episode for episode in all_episodes(config) if episode.id.startswith(episode_id)]
    if not matches:
        raise ListenError(f"no episode with id {episode_id}")
    if len(matches) > 1:
        ids = ", ".join(sorted(episode.id for episode in matches))
        raise ListenError(f"id {episode_id} matches more than one episode: {ids}")
    return matches[0]


def display_title(episode: Episode) -> str:
    return episode.title.strip() or f"Untitled episode {episode.id[:8]}"
