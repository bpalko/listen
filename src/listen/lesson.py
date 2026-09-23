from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .errors import ListenError
from .extract import clean_script

REQUEST_TIMEOUT_SECONDS = 180

SYSTEM_PROMPT = (
    "You write short spoken lessons that a text-to-speech voice reads aloud."
    " Write plain sentences with no markdown, no headings, no bullet points, no stage"
    " directions, and no numbers used as list markers."
    " Length is 1100 to 1600 words, which is eight to twelve minutes of speech."
    " Follow this shape: open with one concrete situation, explain the mechanism behind it,"
    " describe how it fails in practice, then end with exactly two questions for the listener."
    " The two questions are the last two sentences and each ends with a question mark."
    " Your first line is the title in the form 'Title: <the title>' and nothing else."
    " Leave a blank line between paragraphs."
)

_QUESTION = re.compile(r"[^.!?\n]*\?")


@dataclass(frozen=True)
class Lesson:
    title: str
    script: str
    notes: str


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    api_key: str
    model: str

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def settings_from_env(env: dict[str, str] | None = None) -> LLMSettings:
    source = os.environ if env is None else env
    base_url = (source.get("LISTEN_LLM_BASE_URL") or "").strip()
    api_key = (source.get("LISTEN_LLM_API_KEY") or "").strip()
    model = (source.get("LISTEN_LLM_MODEL") or "").strip()

    missing = [
        name
        for name, value in (
            ("LISTEN_LLM_BASE_URL", base_url),
            ("LISTEN_LLM_API_KEY", api_key),
            ("LISTEN_LLM_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise ListenError(f"missing {', '.join(missing)}; lessons need an OpenAI-compatible chat API")
    return LLMSettings(base_url=base_url, api_key=api_key, model=model)


def last_two_questions(script: str) -> list[str]:
    questions = [match.group(0).strip() for match in _QUESTION.finditer(script)]
    return [question for question in questions if question][-2:]


def parse_reply(reply: str, prompt: str) -> Lesson:
    """Split the model's reply into a title, the spoken script, and notes."""
    body = (reply or "").strip()
    if not body:
        raise ListenError("the language model returned an empty lesson; nothing was saved")

    title = ""
    lines = body.split("\n")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^title\s*:\s*(.+)$", stripped.replace("*", "").strip(), flags=re.IGNORECASE)
        if match:
            title = match.group(1).strip().strip("\"'\u201c\u201d").strip()
            lines = lines[index + 1 :]
        break

    script = clean_script("\n".join(lines))
    if not script:
        raise ListenError("the language model returned only a title; nothing was saved")

    if not title:
        title = prompt.strip().rstrip(".?!")[:80] or "Lesson"

    questions = last_two_questions(script)
    notes = "\n".join(questions) if questions else f"Lesson prompt: {prompt.strip()}"
    return Lesson(title=title, script=script, notes=notes)


def request_script(prompt: str, settings: LLMSettings | None = None) -> str:
    import httpx

    settings = settings or settings_from_env()
    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Write the lesson for this request, read aloud start to finish: {prompt.strip()}"
                ),
            },
        ],
    }
    try:
        response = httpx.post(
            settings.endpoint,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip().replace("\n", " ")[:200]
        raise ListenError(
            f"the chat API returned HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ListenError(f"could not reach the chat API at {settings.endpoint}: {exc}") from exc
    except ValueError as exc:
        raise ListenError(f"the chat API did not return JSON: {exc}") from exc

    return content_from_response(data)


def content_from_response(data: dict) -> str:
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ListenError("the chat API response had no message content") from exc


def write_lesson(prompt: str, settings: LLMSettings | None = None) -> Lesson:
    return parse_reply(request_script(prompt, settings), prompt)
