# Listen — MVP

The MVP is done when you can add an episode at your desk, download it to your phone over Wi-Fi, stop the server, and listen.

## Hypothesis

You will listen to material you would otherwise leave unread, and to short lessons on a subject you are studying, if adding one is a single command and the audio is on your phone before you leave.

## In

- Pass a URL. Listen fetches the page and saves the extracted article text as the script. It does not speak yet.
- Pass a lesson prompt. A language model writes an 8–12 minute script: a situation, the mechanism, how it fails, then two questions.
- Edit the script on disk. Synthesize speaks the saved file.
- One MP3 per episode, joined from ElevenLabs chunks.
- A local page that lists ready episodes as download links.
- An RSS feed whose audio links use the computer’s LAN address.
- The server runs only while the phone is downloading.

## Out

These stay in the PRD and wait until the loop above works.

- A server that stays up while you are away
- Tailscale, a VPS, or cloud storage
- A browser extension
- Inbound email
- Chunk resume after a failed ElevenLabs call. A failed episode stays a draft and `synth` starts that episode over.
- HTTP `Range` responses. The MVP download is the whole file from the phone’s browser.
- More than one listener

## Flow

1. `listen add url` or `listen add lesson` writes a draft and prints the script path.
2. You edit `script.txt` if you want to.
3. `listen synth <id>` writes `audio.mp3` and marks the episode ready.
4. `listen serve` prints a page URL and a feed URL on your LAN address.
5. On the phone, same Wi-Fi, you open the page and download the new files.
6. You stop the server. The phone plays the files it already has.

The feed URL is there for a podcast app that fetches from the phone, such as AntennaPod or Podcast Addict. The page is the check that defines done, because it works on either phone.

## Build order

1. URL extraction, synthesize, and the download page. This is the first time audio reaches the phone.
2. Lesson scripts.
3. The RSS feed.

Each step is usable before the next one exists.

## First episodes

These are the first URLs to run through `listen add url`, in listening order. The first three are one sitting each. The Log is about an hour to read, so the audio will run longer.

1. [Starbucks Does Not Use Two-Phase Commit](https://www.enterpriseintegrationpatterns.com/ramblings/18_starbucks.html) — Gregor Hohpe. A coffee shop as a distributed system.
2. [Notes on Distributed Systems for Young Bloods](https://www.somethingsimilar.com/2013/01/14/notes-on-distributed-systems-for-young-bloods/) — Jeff Hodges. Short lessons on coordination, backpressure, and failure.
3. [Please stop calling databases CP or AP](https://martin.kleppmann.com/2015/05/11/please-stop-calling-databases-cp-or-ap.html) — Martin Kleppmann. Why “CP” and “AP” are the wrong labels for a database.
4. [The Log](https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying) — Jay Kreps. The commit log underneath databases, replication, and stream processing.

## Done when

- A URL becomes an MP3 you can download on the phone and play with the server stopped.
- A lesson prompt becomes an episode on that same page.
- Stopping the server does not remove episodes already downloaded.
