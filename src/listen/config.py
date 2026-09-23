from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ListenError

CONFIG_NAME = "listen.toml"

DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_PORT = 8765
DEFAULT_DATA_DIR = "data"
DEFAULT_CHUNK_CHARS = 4000


@dataclass(frozen=True)
class Config:
    root: Path
    voice_id: str = DEFAULT_VOICE_ID
    model_id: str = DEFAULT_MODEL_ID
    output_format: str = DEFAULT_OUTPUT_FORMAT
    port: int = DEFAULT_PORT
    token: str = ""
    data_dir: str = DEFAULT_DATA_DIR
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    base_url: str = ""

    @property
    def path(self) -> Path:
        return self.root / CONFIG_NAME

    @property
    def data_path(self) -> Path:
        data = Path(self.data_dir)
        return data if data.is_absolute() else self.root / data

    @property
    def episodes_path(self) -> Path:
        return self.data_path / "episodes"

    @property
    def feed_path(self) -> Path:
        return self.data_path / "feed.xml"


def render(config: Config) -> str:
    """Render a config as the listen.toml text written by `listen init`."""
    return (
        "# Listen configuration. Edit voice_id to pick an ElevenLabs voice.\n"
        f'voice_id = "{config.voice_id}"\n'
        f'model_id = "{config.model_id}"\n'
        f'output_format = "{config.output_format}"\n'
        f"port = {config.port}\n"
        "# Secret path segment for the local server. Treat it like a password.\n"
        f'token = "{config.token}"\n'
        f'data_dir = "{config.data_dir}"\n'
        f"chunk_chars = {config.chunk_chars}\n"
        "# Set base_url to override LAN detection, e.g. http://192.168.1.20:8765\n"
        f'base_url = "{config.base_url}"\n'
    )


def new_config(root: Path) -> Config:
    return Config(root=root.resolve(), token=secrets.token_urlsafe(16))


def find_config_path(start: Path | None = None) -> Path | None:
    """Look for listen.toml in LISTEN_CONFIG, then the cwd and its parents."""
    from_env = os.environ.get("LISTEN_CONFIG")
    if from_env:
        candidate = Path(from_env).expanduser()
        return candidate if candidate.is_file() else None

    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load(start: Path | None = None) -> Config:
    path = find_config_path(start)
    if path is None:
        raise ListenError(f"no {CONFIG_NAME} found here or above; run `listen init` first")
    return load_path(path)


def load_path(path: Path) -> Config:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    config = Config(
        root=path.resolve().parent,
        voice_id=str(raw.get("voice_id", DEFAULT_VOICE_ID)),
        model_id=str(raw.get("model_id", DEFAULT_MODEL_ID)),
        output_format=str(raw.get("output_format", DEFAULT_OUTPUT_FORMAT)),
        port=int(raw.get("port", DEFAULT_PORT)),
        token=str(raw.get("token", "")),
        data_dir=str(raw.get("data_dir", DEFAULT_DATA_DIR)),
        chunk_chars=int(raw.get("chunk_chars", DEFAULT_CHUNK_CHARS)),
        base_url=str(raw.get("base_url", "")).rstrip("/"),
    )
    if not config.token:
        raise ListenError(f"{path} has no token; add one or run `listen init` in a new directory")
    if config.chunk_chars < 1:
        raise ListenError(f"{path} has a chunk_chars of {config.chunk_chars}; it must be positive")
    return config


def init(root: Path, force: bool = False) -> tuple[Config, bool]:
    """Write listen.toml and the data directory. Returns the config and whether it was created."""
    root = root.resolve()
    path = root / CONFIG_NAME
    created = False

    if path.is_file() and not force:
        config = load_path(path)
    else:
        config = new_config(root)
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(render(config), encoding="utf-8")
        created = True

    config.episodes_path.mkdir(parents=True, exist_ok=True)
    return config, created
