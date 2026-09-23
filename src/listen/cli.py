from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_module
from . import episodes as episode_store
from . import extract, feed, lesson, net, server, speech
from .errors import ListenError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="listen",
        description="A private podcast on your own machine: add, synthesize, serve to your phone.",
    )
    commands = parser.add_subparsers(dest="command", metavar="command")

    init = commands.add_parser("init", help="write listen.toml and the data directory")
    init.add_argument("directory", nargs="?", default=".", help="where to write listen.toml")
    init.add_argument("--force", action="store_true", help="overwrite an existing listen.toml")
    init.set_defaults(handler=command_init)

    add = commands.add_parser("add", help="add a draft episode")
    kinds = add.add_subparsers(dest="kind", metavar="kind")

    add_url = kinds.add_parser("url", help="save a page's article text as a draft script")
    add_url.add_argument("url")
    add_url.add_argument("--title", default="", help="override the extracted title")
    add_url.set_defaults(handler=command_add_url)

    add_lesson = kinds.add_parser("lesson", help="have a language model write a lesson script")
    add_lesson.add_argument("prompt", nargs="+", help="what you want to learn")
    add_lesson.set_defaults(handler=command_add_lesson)

    synth = commands.add_parser("synth", help="speak a saved script and mark the episode ready")
    synth.add_argument("id", help="episode id, or a unique prefix of one")
    synth.add_argument("--force", action="store_true", help="respeak chunks that already exist")
    synth.set_defaults(handler=command_synth)

    serve = commands.add_parser("serve", help="serve the feed, the page, and the MP3s on the LAN")
    serve.add_argument("--port", type=int, default=None, help="override the configured port")
    serve.add_argument("--host", default="0.0.0.0", help="interface to bind")
    serve.set_defaults(handler=command_serve)

    listing = commands.add_parser("list", help="show the episodes on disk")
    listing.set_defaults(handler=command_list)

    return parser


def command_init(args: argparse.Namespace) -> int:
    config, created = config_module.init(Path(args.directory), force=args.force)
    if created:
        print(f"wrote {config.path}")
    else:
        print(f"{config.path} already exists, left it alone")
    print(f"data directory {config.data_path}")
    print(f"set a voice with voice_id in {config.path.name}, then: listen add url <url>")
    return 0


def command_add_url(args: argparse.Namespace) -> int:
    config = config_module.load()
    url = extract.normalize_url(args.url)
    extracted = extract.from_url(url)
    episode = episode_store.create(
        config,
        kind=episode_store.KIND_SOURCE,
        title=args.title.strip() or extracted.title,
        script=extracted.text,
        notes=url,
        source_url=url,
    )
    return report_draft(episode)


def command_add_lesson(args: argparse.Namespace) -> int:
    config = config_module.load()
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        raise ListenError("no lesson prompt given")
    written = lesson.write_lesson(prompt)
    episode = episode_store.create(
        config,
        kind=episode_store.KIND_LESSON,
        title=written.title,
        script=written.script,
        notes=written.notes,
        prompt=prompt,
    )
    return report_draft(episode)


def report_draft(episode) -> int:
    words = len(episode.script_path.read_text(encoding="utf-8").split())
    print(f"{episode.id}")
    print(f"  title  {episode_store.display_title(episode)}")
    print(f"  script {episode.script_path} ({words} words)")
    print(f"  next   listen synth {episode.id[:8]}")
    return 0


def command_synth(args: argparse.Namespace) -> int:
    config = config_module.load()
    episode = episode_store.resolve(config, args.id)
    speech.require_ffmpeg()

    try:
        script = episode.script_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ListenError(f"no script at {episode.script_path}") from exc

    chunks = speech.pack_chunks(script, config.chunk_chars)
    if not chunks:
        raise ListenError(f"{episode.script_path} is empty; nothing to speak")

    client = speech.make_client()
    print(f"{episode_store.display_title(episode)}: {len(chunks)} chunk(s)")
    paths = speech.synthesize_chunks(
        client,
        chunks,
        episode.chunks_path,
        voice_id=config.voice_id,
        model_id=config.model_id,
        output_format=config.output_format,
        force=args.force,
        log=lambda message: print(f"  {message}", flush=True),
    )

    speech.join_chunks(paths, episode.audio_path)
    episode.bytes = episode.audio_path.stat().st_size
    episode.duration_seconds = speech.probe_duration(episode.audio_path)
    episode.status = episode_store.STATUS_READY
    episode.save()
    feed.write(config)

    print(f"  audio {episode.audio_path}")
    print(f"  ready {speech.format_duration(episode.duration_seconds)}, "
          f"{server.size_label(episode.bytes)}")
    return 0


def command_serve(args: argparse.Namespace) -> int:
    config = config_module.load()
    port = args.port or config.port
    base = net.base_url(config, port=port)
    feed.write(config, base)

    ready = episode_store.ready_episodes(config)
    try:
        http = server.make_server(config, base=base, host=args.host, port=port)
    except OSError as error:
        raise ListenError(f"could not bind {args.host}:{port}: {error}") from error

    print(f"page {net.page_url(config, base)}")
    print(f"feed {net.feed_url(config, base)}")
    print(f"{len(ready)} ready episode(s). Same Wi-Fi on the phone. Ctrl-C stops the server.")
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped; downloaded episodes stay on the phone")
    finally:
        http.server_close()
    return 0


def command_list(args: argparse.Namespace) -> int:
    config = config_module.load()
    found = episode_store.all_episodes(config)
    if not found:
        print("no episodes yet; try: listen add url <url>")
        return 0
    for episode in found:
        mark = "ready" if episode.is_ready else "draft"
        detail = (
            f"{speech.format_duration(episode.duration_seconds)} {server.size_label(episode.bytes)}"
            if episode.is_ready
            else episode.kind
        )
        print(f"{episode.id[:8]}  {mark}  {detail:>16}  {episode_store.display_title(episode)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except ListenError as error:
        print(f"listen: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
