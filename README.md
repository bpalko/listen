# Listen

A private podcast that runs on your own machine. You add an episode from a link or a lesson
prompt, Listen narrates it with ElevenLabs, and your phone downloads the MP3 over your Wi-Fi.
Then you stop the server and the episodes play with the computer off.

One person, no accounts, no cloud. See `PRD.md`, `MVP.md`, and `TECH_SPEC.md` for the product
and the design this implements.

## Requirements

- Python 3.12
- `ffmpeg` and `ffprobe` on `PATH` (used to join the audio chunks and read duration)
- An ElevenLabs API key
- For lessons only: any OpenAI-compatible chat API

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .            # add [dev] for the tests: pip install -e ".[dev]"
```

## Environment

| Variable | Needed for | What it is |
| --- | --- | --- |
| `ELEVENLABS_API_KEY` | `listen synth` | Your ElevenLabs key |
| `LISTEN_LLM_BASE_URL` | `listen add lesson` | Chat API base, e.g. `https://api.openai.com/v1` |
| `LISTEN_LLM_API_KEY` | `listen add lesson` | Key for that API |
| `LISTEN_LLM_MODEL` | `listen add lesson` | Model name to ask for |
| `LISTEN_CONFIG` | optional | Path to a `listen.toml` to use instead of searching upward |

Keep keys out of the repo. Export them in your shell or a file you do not commit.

## Set up a library

```bash
mkdir ~/listen && cd ~/listen
listen init
```

`init` writes `listen.toml` next to a `data/` directory and puts a fresh random token in it.
Every later command finds that config in the current directory or a parent, so run them from
anywhere inside `~/listen`.

Then pick a voice. `voice_id` starts empty, and `synth` refuses to run until you set it:

```bash
export ELEVENLABS_API_KEY='...'
listen voices                    # ids, category, and name for the voices on your account
```

Put one of those ids in `listen.toml`. Use a voice the API will actually give you: a free plan
can use the default voices and your own clones, but not voices from the shared voice library,
which fail with `paid_plan_required`. `listen voices` lists the voices on your account and
leaves out the legacy ones. A library voice can still be in that list and still be refused on a
free plan; if `synth` says so, pick a premade or cloned voice instead.

`listen.toml`:

| Field | Default | Meaning |
| --- | --- | --- |
| `voice_id` | empty | The voice that reads your episodes. Set it from `listen voices`. |
| `model_id` | `eleven_multilingual_v2` | ElevenLabs model |
| `output_format` | `mp3_44100_128` | ElevenLabs output format |
| `port` | `8765` | Port `listen serve` binds |
| `token` | random | Secret path segment for every URL. Treat it like a password. |
| `data_dir` | `data` | Where episodes and the feed live |
| `chunk_chars` | `4000` | Largest text chunk sent to ElevenLabs |
| `base_url` | empty | Set it to override LAN detection, e.g. `http://192.168.1.20:8765` |

## The desk to phone flow

At the desk, add something. Adding never calls ElevenLabs, so it is cheap and fast.

```bash
listen add url https://www.enterpriseintegrationpatterns.com/ramblings/18_starbucks.html
listen add lesson "explain replication lag"
```

Each prints the episode id and the path to `script.txt`:

```text
248d3c78-faa0-4955-adcf-b1cf2be093d0
  title  Starbucks Does Not Use Two-Phase Commit
  script /home/you/listen/data/episodes/248d3c78-.../script.txt (782 words)
  next   listen synth 248d3c78
```

Open that file and edit it if you want. Whatever is saved there is what gets spoken.

Then narrate it. An id prefix is enough as long as it is unique.

```bash
listen synth 248d3c78
```

That speaks the script in chunks, joins them into `audio.mp3`, marks the episode ready, and
rebuilds the feed. `listen list` shows what you have and which episodes are still drafts.

Now hand it to the phone.

```bash
listen serve
# page http://192.168.1.20:8765/Kp30Z9t_Ynv_80mkBE3hSA/
# feed http://192.168.1.20:8765/Kp30Z9t_Ynv_80mkBE3hSA/feed.xml
```

On the phone, on the same Wi-Fi, either:

- open the **page** URL in the browser and tap Download MP3 on each new episode, or
- paste the **feed** URL into a podcast app that fetches feeds from the phone itself, such as
  AntennaPod or Podcast Addict, and let it download.

Overcast, Pocket Casts, and Apple Podcasts fetch feeds on their own servers, which cannot see
your Wi-Fi, so the feed will not load there. The browser page works on any phone.

Wait for the downloads to finish, then press Ctrl-C. **The server is only for the download
session.** Nothing about playback needs it: the files are on the phone, and the computer can be
asleep or off.

## What is on disk

```text
listen.toml
data/
  feed.xml
  episodes/<id>/
    meta.json        id, kind, title, notes, status, bytes, duration
    script.txt       what gets spoken; edit it freely
    chunks/000.mp3   one file per ElevenLabs call
    audio.mp3        the joined episode
```

The id is stable, so re-synthesizing an episode replaces the audio instead of creating a second
copy in your podcast app.

## Behavior worth knowing

- **Drafts stay out of the feed.** Only episodes with an `audio.mp3` are listed or served.
- **Chunks resume.** If ElevenLabs fails partway, the episode stays a draft and the chunks
  already written stay on disk. The next `listen synth` skips those files and speaks only what is
  missing. `listen synth <id> --force` respeaks everything, which is what you want after editing
  the script.
- **Range requests are supported.** MP3s answer `Range` with `206 Partial Content`, because
  podcast apps fetch byte ranges while downloading and some fail without it.
- **Every URL sits under the token**, and anything outside it is a 404. The audio links always
  use the LAN address, never `localhost`.
- **Failures are one line.** A missing key, a missing `ffmpeg`, a page with no article text: each
  exits with a single line naming what is missing, and an empty extract writes no episode. What
  ElevenLabs refuses is translated too, so a rejected key, an unknown voice, a voice your plan
  cannot use, and a rate limit each read as a sentence instead of a raw 4xx body.

## Commands

| Command | Effect |
| --- | --- |
| `listen init [dir]` | Write `listen.toml` and the data directory |
| `listen add url <url>` | Extract a page's article text into a draft script |
| `listen add lesson <prompt>` | Have a language model write an 8–12 minute lesson script |
| `listen synth <id>` | Speak the saved script, join the audio, mark the episode ready |
| `listen serve` | Serve the page, the feed, and the MP3s on the LAN |
| `listen list` | Show every episode, draft and ready |
| `listen voices` | Show the ElevenLabs voices on your account |

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The suite needs no API keys and makes no network calls. It covers the extraction helpers, chunk
packing, the lesson parser, the feed XML, the `Range` handler against a live local server, and an
end-to-end pass through add, synth, serve, and download with the ElevenLabs and chat calls stubbed
out. The end-to-end tests do use real `ffmpeg`, so they are skipped when it is missing.
