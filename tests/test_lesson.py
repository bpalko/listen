from __future__ import annotations

import pytest

from listen.errors import ListenError
from listen.lesson import (
    LLMSettings,
    content_from_response,
    last_two_questions,
    parse_reply,
    settings_from_env,
)

REPLY = """Title: Replication Lag

A read hits the follower a moment after the write hit the leader.

The mechanism is a stream of changes the follower applies in order.

It fails when the follower falls behind and a user reads their own stale profile.

Where in your system would a stale read be invisible? What would you measure to notice it?
"""


def test_parse_reply_takes_the_title_line_off_the_script():
    lesson = parse_reply(REPLY, "explain replication lag")
    assert lesson.title == "Replication Lag"
    assert not lesson.script.startswith("Title:")
    assert lesson.script.startswith("A read hits the follower")


def test_parse_reply_copies_the_last_two_questions_into_notes():
    lesson = parse_reply(REPLY, "explain replication lag")
    assert lesson.notes.splitlines() == [
        "Where in your system would a stale read be invisible?",
        "What would you measure to notice it?",
    ]


def test_parse_reply_tolerates_a_bold_or_quoted_title():
    assert parse_reply('**Title:** "Backpressure"\n\nBody text here.\n', "p").title == "Backpressure"


def test_parse_reply_falls_back_to_the_prompt_when_there_is_no_title():
    lesson = parse_reply("Body text with no title line.\n", "explain write amplification.")
    assert lesson.title == "explain write amplification"


def test_parse_reply_collapses_whitespace_and_keeps_paragraphs():
    lesson = parse_reply("Title: T\n\nfirst   line\n\n\n\nsecond line\n", "p")
    assert lesson.script == "first line\n\nsecond line"


def test_parse_reply_rejects_an_empty_answer():
    with pytest.raises(ListenError):
        parse_reply("   ", "p")
    with pytest.raises(ListenError):
        parse_reply("Title: Only a title\n", "p")


def test_last_two_questions_picks_the_final_pair():
    script = "Is this one? Not a question. Is this two? And is this three?"
    assert last_two_questions(script) == ["Is this two?", "And is this three?"]


def test_notes_fall_back_to_the_prompt_when_there_are_no_questions():
    lesson = parse_reply("Title: T\n\nA script with no questions at all.\n", "explain quorums")
    assert lesson.notes == "Lesson prompt: explain quorums"


def test_settings_from_env_needs_all_three_variables():
    with pytest.raises(ListenError) as error:
        settings_from_env({"LISTEN_LLM_BASE_URL": "https://api.example.com/v1"})
    message = str(error.value)
    assert "LISTEN_LLM_API_KEY" in message and "LISTEN_LLM_MODEL" in message


def test_settings_from_env_reads_all_three(monkeypatch):
    settings = settings_from_env(
        {
            "LISTEN_LLM_BASE_URL": "https://api.example.com/v1",
            "LISTEN_LLM_API_KEY": "not-a-real-key",
            "LISTEN_LLM_MODEL": "some-model",
        }
    )
    assert settings.model == "some-model"
    assert settings.endpoint == "https://api.example.com/v1/chat/completions"


def test_endpoint_does_not_double_the_path():
    settings = LLMSettings("https://api.example.com/v1/chat/completions/", "k", "m")
    assert settings.endpoint == "https://api.example.com/v1/chat/completions"


def test_content_from_response_reads_the_first_choice():
    data = {"choices": [{"message": {"content": "hello"}}]}
    assert content_from_response(data) == "hello"


def test_content_from_response_fails_loudly_on_a_shape_it_does_not_know():
    with pytest.raises(ListenError):
        content_from_response({"error": "nope"})
