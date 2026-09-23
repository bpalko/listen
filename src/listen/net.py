from __future__ import annotations

import socket

from .config import Config

PROBE_TARGET = ("8.8.8.8", 80)


def lan_address() -> str:
    """The address of this machine on the local network, never localhost."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.settimeout(1.0)
        probe.connect(PROBE_TARGET)
        address = probe.getsockname()[0]
    except OSError:
        address = ""
    finally:
        probe.close()

    if not address or address.startswith("127."):
        try:
            address = socket.gethostbyname(socket.gethostname())
        except OSError:
            address = ""
    return address or "127.0.0.1"


def base_url(config: Config, port: int | None = None) -> str:
    """`base_url` from config when it is set, otherwise the detected LAN address."""
    if config.base_url:
        return config.base_url.rstrip("/")
    return f"http://{lan_address()}:{port or config.port}"


def root_url(config: Config, base: str | None = None) -> str:
    return f"{base or base_url(config)}/{config.token}"


def page_url(config: Config, base: str | None = None) -> str:
    return root_url(config, base) + "/"


def feed_url(config: Config, base: str | None = None) -> str:
    return f"{root_url(config, base)}/feed.xml"


def episode_url(config: Config, episode_id: str, base: str | None = None) -> str:
    return f"{root_url(config, base)}/episodes/{episode_id}.mp3"
