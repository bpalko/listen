# Listen — Tech Spec

## Stack

Python 3.12. Dependencies are `elevenlabs`, `httpx`, and `trafilatura`. RSS is written by the program. `ffmpeg` and `ffprobe` are required on the machine and used to join audio and read duration.

Voice uses `ELEVENLABS_API_KEY`. Lesson scripts use any OpenAI-compatible chat API: `LISTEN_LLM_BASE_URL`, `LISTEN_LLM_API_KEY`, `LISTEN_LLM_MODEL`.

## Layout

```text
listen.toml
data/
  feed.xml
  episodes/<id>/
    meta.json
    script.txt
    chunks/000.mp3
    audio.mp3
```

`listen.toml` holds the voice id, ElevenLabs model id (`eleven_multilingual_v2`), output format (`mp3_44100_128`), port `8765`, a random path token, the data directory, and a chunk size of 4000 characters. A `base_url` field overrides LAN detection when it is set.

## Commands

| Command | Effect |
| --- | --- |
| `listen init` | Writes `listen.toml` and the data directory |
| `listen add url <url>` | Fetches the page, extracts the article, writes that text as a draft script |
| `listen add lesson <prompt>` | Asks a language model for a lesson script, saves a draft |
| `listen synth <id>` | Speaks the saved script, marks the episode ready, rebuilds the episode list |
| `listen serve` | Rewrites feed URLs to the current LAN address and serves |

`add` prints the episode id and the script path. It does not synthesize.

## Episode record

```json
{
  "id": "uuid",
  "kind": "source",
  "title": "",
  "notes": "",
  "source_url": null,
  "prompt": null,
  "created_at": "ISO-8601",
  "status": "draft",
  "bytes": 0,
  "duration_seconds": 0
}
```

`kind` is `source` or `lesson`. `status` is `draft` or `ready`. The feed includes ready episodes only.

## Source extraction

`httpx` fetches the URL with a 30 second timeout. `trafilatura` returns the title and the article text. An empty extract stops the command and writes no episode. The script is that text with whitespace collapsed and lines that are only URLs removed. No language model is involved. The extractor's plain text is written to `script.txt`.

## Lesson script

The chat request asks for a script to be read aloud: no markdown, no headings, about 1100–1600 words, in the shape above, ending with exactly two questions. The model’s first line is `Title: ...`. That line becomes the episode title and is removed from the script. The prompt is stored on the episode. The two questions are copied into `notes`.

## Speech

Split `script.txt` on blank lines. Pack whole paragraphs into chunks of at most 4000 characters. For each chunk, call `text_to_speech.convert` with the configured voice and model. Pass the previous chunk, trimmed to 1000 characters, as `previous_text`, and the next chunk, trimmed the same way, as `next_text`. Write `chunks/NNN.mp3`.

Join the chunks with the ffmpeg concat demuxer, codec copy, into `audio.mp3`. Read the duration with `ffprobe`. Set `bytes`, `duration_seconds`, and `status: ready`.

If a chunk request fails, leave the episode in `draft` and keep the chunk files. A later `synth` skips chunk files that already exist.

## Feed

`listen serve` rebuilds `feed.xml` before it listens. Every enclosure URL uses the LAN base, never `localhost`. The base is `base_url` from config, or otherwise the address chosen by opening a UDP socket to `8.8.8.8` and reading the local address.

The feed is RSS 2.0 with the iTunes namespace. Channel title `Listen`, language `en`, `itunes:block` set to `Yes`. Each item has `title`, `description` from `notes`, `guid` equal to the episode id with `isPermaLink="false"`, `pubDate`, `itunes:duration`, and an `enclosure` of type `audio/mpeg` with the file length. Items are listed newest first.

## Server

Bind `0.0.0.0` on the configured port. Routes under the secret token:

- `GET /<token>/feed.xml`
- `GET /<token>/episodes/<id>.mp3`, with `Range` support and `206` responses
- `GET /<token>/`, an HTML list of ready episodes with a download link each

Anything else is 404. On startup, print the feed URL and the page URL using the LAN base.

`Range` matters because podcast apps request byte ranges while downloading. A handler that only returns the whole file will fail in some of them.

## Failure behavior

A missing key, a missing `ffmpeg`, or an empty extract exits with a single line naming what is missing. A failed synthesis leaves a draft and the chunks already written. The feed changes only after `audio.mp3` exists.
