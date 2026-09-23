# Listen — Product Requirements

Listen is a private podcast that runs on your computer. You add episodes from a link or a lesson prompt. With the server running, your phone downloads them over your Wi-Fi, and then they play with the computer off.

## Problem

Reading happens at a desk. You want that material, and short lessons on whatever you are studying, in your ears while you are away from the desk.

## User

One person. No accounts and no sharing.

## Product

Two ways to add an episode, one feed.

- **Source.** You give a URL. Listen pulls the article text out of the page and narrates that text.
- **Lesson.** You name something to learn. A language model writes a short spoken lesson, and Listen narrates that.

The subject is whatever you ask for. Database episodes and cooking episodes are the same kind of thing.

## An episode

- A title
- One MP3
- A few lines of notes. A source episode notes the URL. A lesson episode notes the two questions it ends with.
- A stable id, so regenerating the audio does not create a second copy in the app

## Add a source

1. You pass a URL.
2. Listen fetches the page and extracts the article body. That extracted text is the script. No language model writes it. Listen saves the script and does not call ElevenLabs yet.
3. You can edit the script.
4. You synthesize. Listen writes the MP3 and updates the feed.

## Add a lesson

1. You pass a prompt, such as “explain replication lag”.
2. A language model writes a script of about 8–12 minutes: a concrete situation, the mechanism, how it fails, then two questions. Plain sentences, meant to be read aloud.
3. You can edit the script.
4. You synthesize. The episode joins the same feed.

## Get it on the phone

1. You start the server on your computer.
2. The phone is on the same Wi-Fi.
3. You paste the feed URL into a podcast app that fetches feeds itself, or you open the page URL in the phone’s browser and download the files.
4. You wait until the downloads finish, then stop the server.
5. Playback uses the files on the phone.

The app has to request the feed from the phone. AntennaPod and Podcast Addict do that, so a Wi-Fi address works. Overcast, Pocket Casts, and Apple Podcasts fetch feeds on their own servers, so a feed that exists only on your Wi-Fi does not load there. The browser page is the path that works on either phone.

## v1 requirements

- Add from a URL and from a lesson prompt
- Save the script, and synthesize whatever is saved, so edits are what gets spoken
- Serve one RSS feed and the MP3s on the local network
- Put the computer’s LAN address in every audio link
- Put a secret token in the path
- Print the feed URL and the page URL when the server starts
- Keep the server running only for the download session

## Out of scope

- A server that stays up while you are away
- Tailscale, a VPS, or cloud storage
- A browser extension
- Inbound email
- More than one listener
- Labs, flashcards, or tracking your answers

## Done when

- A URL becomes an episode you can edit, then hear
- A prompt becomes a lesson on that same feed
- On the same Wi-Fi, with the server running, the phone downloads the new episodes
- With the server stopped, those episodes still play
