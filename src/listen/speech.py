from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ListenError

CONTEXT_CHARS = 1000
CHUNK_NAME = re.compile(r"^(\d{3})\.mp3$")

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?\u2026])[\"'\u201d\u2019]?\s+")


def split_paragraphs(text: str) -> list[str]:
    return [block.strip() for block in _PARAGRAPH_BREAK.split(text or "") if block.strip()]


def hard_split(text: str, limit: int) -> list[str]:
    """Last resort for a sentence longer than one chunk: break on word boundaries."""
    pieces: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and len(candidate) > limit:
            pieces.append(current)
            current = word
        else:
            current = candidate
        while len(current) > limit:
            pieces.append(current[:limit])
            current = current[limit:]
    if current:
        pieces.append(current)
    return pieces


def split_paragraph(paragraph: str, limit: int) -> list[str]:
    """Break a paragraph that does not fit in one chunk at sentence boundaries."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_BREAK.split(paragraph):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(hard_split(sentence, limit))
            continue
        candidate = f"{current} {sentence}" if current else sentence
        if current and len(candidate) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def pack_chunks(text: str, limit: int) -> list[str]:
    """Pack whole paragraphs into chunks of at most `limit` characters."""
    if limit < 1:
        raise ListenError(f"chunk size {limit} is not usable; it must be positive")

    pieces: list[str] = []
    for paragraph in split_paragraphs(text):
        if len(paragraph) <= limit:
            pieces.append(paragraph)
        else:
            pieces.extend(split_paragraph(paragraph, limit))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if current and len(candidate) > limit:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        raise ListenError("ffmpeg is not on PATH; install ffmpeg and try again")
    if not ffprobe:
        raise ListenError("ffprobe is not on PATH; install ffmpeg and try again")
    return ffmpeg, ffprobe


def require_api_key() -> str:
    key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    if not key:
        raise ListenError("missing ELEVENLABS_API_KEY; export it and try again")
    return key


def make_client():
    from elevenlabs.client import ElevenLabs

    return ElevenLabs(api_key=require_api_key())


def api_error_parts(error: Exception) -> tuple[int | None, str, str]:
    """Pull the status, the API's own code, and its message out of an ElevenLabs error."""
    status = getattr(error, "status_code", None)
    body = getattr(error, "body", None)
    detail = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(detail, dict):
        detail = body if isinstance(body, dict) else {}

    code = str(detail.get("code") or detail.get("status") or "")
    message = str(detail.get("message") or "").strip()
    if not message and isinstance(detail, dict) and isinstance(body, dict):
        message = str(body.get("message") or "").strip()
    if not message and isinstance(body, str):
        message = body.strip().replace("\n", " ")[:200]
    if not message and getattr(error, "headers", None) is None:
        message = str(error).strip().replace("\n", " ")[:200]
    return status, code, message or "the request was refused"


def describe_api_error(error: Exception, voice_id: str = "") -> str:
    """One line naming what ElevenLabs refused, and what to do about it."""
    status, code, message = api_error_parts(error)
    voice = f" voice {voice_id}" if voice_id else " that voice"

    if code == "paid_plan_required" or status == 402:
        return (
            f"{message} Listen asked for{voice}; run `listen voices` and pick one from your own "
            "account, since voice library voices need a paid plan."
        )
    if status == 401:
        return f"ElevenLabs rejected ELEVENLABS_API_KEY: {message}"
    if status == 404 or code in ("voice_not_found", "not_found"):
        return f"ElevenLabs has no{voice} on your account: {message} Run `listen voices`."
    if status == 429 or code in ("too_many_requests", "quota_exceeded"):
        return f"ElevenLabs is rate limiting or out of quota: {message}"
    return message


@dataclass(frozen=True)
class VoiceChoice:
    voice_id: str
    name: str
    category: str


def list_voices(client) -> list[VoiceChoice]:
    """The voices on this account, default voices first. Legacy library voices are left out."""
    try:
        response = client.voices.get_all(show_legacy=False)
    except Exception as exc:
        raise ListenError(f"could not list voices: {describe_api_error(exc)}") from exc

    choices = [
        VoiceChoice(
            voice_id=voice.voice_id,
            name=(getattr(voice, "name", "") or "").strip(),
            category=(getattr(voice, "category", "") or "").strip(),
        )
        for voice in getattr(response, "voices", []) or []
    ]
    choices.sort(key=lambda choice: (choice.category != "premade", choice.category, choice.name))
    return choices


def chunk_path(chunks_dir: Path, index: int) -> Path:
    return chunks_dir / f"{index:03d}.mp3"


def existing_chunks(chunks_dir: Path) -> list[Path]:
    if not chunks_dir.is_dir():
        return []
    found = [child for child in chunks_dir.iterdir() if CHUNK_NAME.match(child.name)]
    return sorted(found, key=lambda path: path.name)


def drop_stale_chunks(chunks_dir: Path, keep: int) -> None:
    """Remove chunk files past the end of the current script so a join never picks them up."""
    for path in existing_chunks(chunks_dir):
        match = CHUNK_NAME.match(path.name)
        if match and int(match.group(1)) >= keep:
            path.unlink()


def write_audio(payload, destination: Path) -> None:
    """Write an ElevenLabs response, which may be bytes or a stream of byte chunks."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with temporary.open("wb") as handle:
        if isinstance(payload, (bytes, bytearray)):
            handle.write(payload)
        else:
            for piece in payload:
                if piece:
                    handle.write(piece)
    if temporary.stat().st_size == 0:
        temporary.unlink()
        raise ListenError("ElevenLabs returned no audio for a chunk; the episode stays a draft")
    temporary.replace(destination)


def synthesize_chunks(
    client,
    chunks: list[str],
    chunks_dir: Path,
    voice_id: str,
    model_id: str,
    output_format: str,
    force: bool = False,
    log=lambda message: None,
) -> list[Path]:
    """Speak every chunk, skipping files a previous run already wrote."""
    chunks_dir.mkdir(parents=True, exist_ok=True)
    if force:
        for path in existing_chunks(chunks_dir):
            path.unlink()
    drop_stale_chunks(chunks_dir, keep=len(chunks))

    paths: list[Path] = []
    for index, chunk in enumerate(chunks):
        destination = chunk_path(chunks_dir, index)
        if destination.is_file() and destination.stat().st_size > 0:
            log(f"chunk {index + 1}/{len(chunks)} already done, skipping")
            paths.append(destination)
            continue

        log(f"chunk {index + 1}/{len(chunks)} speaking {len(chunk)} characters")
        previous_text = chunks[index - 1][-CONTEXT_CHARS:] if index > 0 else None
        next_text = chunks[index + 1][:CONTEXT_CHARS] if index + 1 < len(chunks) else None
        try:
            payload = client.text_to_speech.convert(
                voice_id=voice_id,
                model_id=model_id,
                output_format=output_format,
                text=chunk,
                previous_text=previous_text,
                next_text=next_text,
            )
            write_audio(payload, destination)
        except ListenError:
            raise
        except Exception as exc:
            raise ListenError(
                f"ElevenLabs failed on chunk {index + 1} of {len(chunks)}: "
                f"{describe_api_error(exc, voice_id)}"
            ) from exc
        paths.append(destination)
    return paths


def join_chunks(paths: list[Path], destination: Path) -> None:
    """Join mp3 chunks with the ffmpeg concat demuxer, copying the codec."""
    ffmpeg, _ = require_ffmpeg()
    if not paths:
        raise ListenError("no audio chunks to join")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        for path in paths:
            escaped = str(path.resolve()).replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")
        list_path = Path(handle.name)

    try:
        result = subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(list_path),
                "-c", "copy", str(destination),
            ],
            capture_output=True,
            text=True,
        )
    finally:
        list_path.unlink(missing_ok=True)

    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        message = detail[-1] if detail else f"exit code {result.returncode}"
        raise ListenError(f"ffmpeg could not join the chunks: {message}")


def probe_duration(path: Path) -> int:
    _, ffprobe = require_ffmpeg()
    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nokey=1:noprint_wrappers=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ListenError(f"ffprobe could not read {path}")
    try:
        return int(round(float(result.stdout.strip())))
    except ValueError as exc:
        raise ListenError(f"ffprobe returned no duration for {path}") from exc


def format_duration(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
