from __future__ import annotations

import pytest

from listen.errors import ListenError
from listen.speech import (
    CONTEXT_CHARS,
    describe_api_error,
    drop_stale_chunks,
    format_duration,
    list_voices,
    pack_chunks,
    require_api_key,
    synthesize_chunks,
    write_audio,
)


class FakeApiError(Exception):
    """Shaped like elevenlabs.core.api_error.ApiError."""

    def __init__(self, status_code, body):
        super().__init__(f"status_code: {status_code}, body: {body}")
        self.status_code = status_code
        self.body = body


class FakeTextToSpeech:
    def __init__(self):
        self.calls = []

    def convert(self, *, voice_id, model_id, output_format, text, previous_text, next_text):
        self.calls.append(
            {
                "voice_id": voice_id,
                "model_id": model_id,
                "output_format": output_format,
                "text": text,
                "previous_text": previous_text,
                "next_text": next_text,
            }
        )
        return iter([b"ID3", text.encode("utf-8")])


class FakeClient:
    def __init__(self):
        self.text_to_speech = FakeTextToSpeech()


class FailingClient:
    class _TTS:
        def __init__(self, fail_at):
            self.fail_at = fail_at
            self.calls = 0

        def convert(self, *, text, **_):
            self.calls += 1
            if self.calls == self.fail_at:
                raise RuntimeError("upstream said no")
            return [b"ID3", text.encode("utf-8")]

    def __init__(self, fail_at):
        self.text_to_speech = self._TTS(fail_at)


def test_pack_chunks_keeps_short_paragraphs_together():
    text = "one\n\ntwo\n\nthree"
    assert pack_chunks(text, 4000) == ["one\n\ntwo\n\nthree"]


def test_pack_chunks_never_exceeds_the_limit():
    paragraphs = ["word " * 40 for _ in range(20)]
    chunks = pack_chunks("\n\n".join(paragraphs), 500)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)


def test_pack_chunks_splits_on_paragraph_boundaries():
    text = "a" * 300 + "\n\n" + "b" * 300
    assert pack_chunks(text, 400) == ["a" * 300, "b" * 300]


def test_pack_chunks_splits_an_oversized_paragraph_at_sentence_boundaries():
    sentences = " ".join(f"Sentence number {index} here." for index in range(60))
    chunks = pack_chunks(sentences, 200)
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert all(chunk.endswith(".") for chunk in chunks)
    assert "".join(chunks).count("Sentence") == 60


def test_pack_chunks_splits_a_sentence_longer_than_the_limit():
    chunks = pack_chunks("word " * 200, 100)
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert sum(chunk.count("word") for chunk in chunks) == 200


def test_pack_chunks_preserves_every_word():
    text = "\n\n".join(f"Paragraph {index} has a few words in it." for index in range(30))
    joined = " ".join(pack_chunks(text, 120)).split()
    assert joined == text.replace("\n\n", " ").split()


def test_pack_chunks_on_empty_text():
    assert pack_chunks("   \n\n ", 4000) == []


def test_pack_chunks_rejects_a_bad_limit():
    with pytest.raises(ListenError):
        pack_chunks("hello", 0)


def test_format_duration():
    assert format_duration(0) == "0:00"
    assert format_duration(59) == "0:59"
    assert format_duration(754) == "12:34"
    assert format_duration(3725) == "1:02:05"


def test_write_audio_rejects_an_empty_response(tmp_path):
    with pytest.raises(ListenError):
        write_audio(iter([b""]), tmp_path / "000.mp3")
    assert not (tmp_path / "000.mp3").exists()
    assert not (tmp_path / "000.mp3.part").exists()


def test_synthesize_chunks_writes_numbered_files_with_neighbour_context(tmp_path):
    client = FakeClient()
    chunks = ["first chunk", "second chunk", "third chunk"]
    paths = synthesize_chunks(
        client,
        chunks,
        tmp_path / "chunks",
        voice_id="voice",
        model_id="model",
        output_format="mp3_44100_128",
    )

    assert [path.name for path in paths] == ["000.mp3", "001.mp3", "002.mp3"]
    assert all(path.is_file() for path in paths)
    calls = client.text_to_speech.calls
    assert calls[0]["previous_text"] is None
    assert calls[0]["next_text"] == "second chunk"
    assert calls[1]["previous_text"] == "first chunk"
    assert calls[2]["next_text"] is None


def test_synthesize_chunks_trims_neighbour_context_to_1000_characters(tmp_path):
    client = FakeClient()
    long_chunks = ["a" * 3000, "b" * 3000, "c" * 3000]
    synthesize_chunks(
        client,
        long_chunks,
        tmp_path / "chunks",
        voice_id="voice",
        model_id="model",
        output_format="mp3_44100_128",
    )
    middle = client.text_to_speech.calls[1]
    assert middle["previous_text"] == "a" * 1000
    assert middle["next_text"] == "c" * 1000


def test_synthesize_chunks_skips_files_a_previous_run_wrote(tmp_path):
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    (chunks_dir / "000.mp3").write_bytes(b"already here")

    client = FakeClient()
    synthesize_chunks(
        client,
        ["first chunk", "second chunk"],
        chunks_dir,
        voice_id="voice",
        model_id="model",
        output_format="mp3_44100_128",
    )

    assert (chunks_dir / "000.mp3").read_bytes() == b"already here"
    assert [call["text"] for call in client.text_to_speech.calls] == ["second chunk"]


def test_synthesize_chunks_force_respeaks_everything(tmp_path):
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    (chunks_dir / "000.mp3").write_bytes(b"stale")

    client = FakeClient()
    synthesize_chunks(
        client,
        ["first chunk"],
        chunks_dir,
        voice_id="voice",
        model_id="model",
        output_format="mp3_44100_128",
        force=True,
    )
    assert (chunks_dir / "000.mp3").read_bytes() != b"stale"


def test_synthesize_chunks_keeps_written_chunks_when_a_call_fails(tmp_path):
    chunks_dir = tmp_path / "chunks"
    client = FailingClient(fail_at=2)
    with pytest.raises(ListenError) as error:
        synthesize_chunks(
            client,
            ["one", "two", "three"],
            chunks_dir,
            voice_id="voice",
            model_id="model",
            output_format="mp3_44100_128",
        )

    assert "chunk 2 of 3" in str(error.value)
    assert (chunks_dir / "000.mp3").is_file()
    assert not (chunks_dir / "001.mp3").exists()


def test_require_api_key_names_the_missing_variable(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(ListenError) as error:
        require_api_key()
    assert "ELEVENLABS_API_KEY" in str(error.value)

    monkeypatch.setenv("ELEVENLABS_API_KEY", "   ")
    with pytest.raises(ListenError):
        require_api_key()


def test_the_installed_sdk_accepts_every_argument_we_send():
    """Catch SDK drift without a key: the live call is the one path tests cannot run."""
    import inspect

    from elevenlabs.text_to_speech.client import TextToSpeechClient

    accepted = inspect.signature(TextToSpeechClient.convert).parameters
    for name in ("voice_id", "model_id", "output_format", "text", "previous_text", "next_text"):
        assert name in accepted, f"the elevenlabs SDK no longer accepts {name}"
    assert CONTEXT_CHARS == 1000


def test_a_library_voice_on_a_free_plan_says_what_to_do():
    error = FakeApiError(
        402,
        {
            "detail": {
                "status": "payment_required",
                "code": "paid_plan_required",
                "message": "Free users cannot use library voices via the API. Please upgrade your "
                "subscription to use this voice.",
                "request_id": "6711580824f9e3f2291077269ce4eef2",
            }
        },
    )
    line = describe_api_error(error, voice_id="21m00Tcm4TlvDq8ikWAM")

    assert "Free users cannot use library voices" in line
    assert "21m00Tcm4TlvDq8ikWAM" in line
    assert "listen voices" in line
    assert "\n" not in line


def test_a_rejected_key_names_the_variable():
    error = FakeApiError(401, {"detail": {"message": "Invalid API key."}})
    assert "ELEVENLABS_API_KEY" in describe_api_error(error)


def test_an_unknown_voice_points_at_the_voice_list():
    error = FakeApiError(404, {"detail": {"message": "A voice for the voice_id was not found."}})
    line = describe_api_error(error, voice_id="nope")
    assert "no voice nope" in line
    assert "listen voices" in line


def test_a_rate_limit_says_so():
    error = FakeApiError(429, {"detail": {"status": "too_many_requests", "message": "Slow down."}})
    assert "rate limiting or out of quota" in describe_api_error(error)


def test_an_error_with_no_api_body_still_gives_one_line():
    line = describe_api_error(RuntimeError("connection reset by peer"))
    assert line == "connection reset by peer"


def test_a_refusal_does_not_print_response_headers():
    error = FakeApiError(500, None)
    error.headers = {"xi-api-key": "secret-key-value"}
    error.args = (f"headers: {error.headers}, status_code: 500, body: None",)
    line = describe_api_error(error)
    assert line == "the request was refused"
    assert "secret-key-value" not in line


def test_a_failed_chunk_carries_the_api_explanation(tmp_path):
    class RefusingClient:
        def __init__(self):
            self.text_to_speech = self

        def convert(self, **_):
            raise FakeApiError(402, {"detail": {"code": "paid_plan_required", "message": "Nope."}})

    with pytest.raises(ListenError) as error:
        synthesize_chunks(
            RefusingClient(),
            ["one"],
            tmp_path / "chunks",
            voice_id="21m00Tcm4TlvDq8ikWAM",
            model_id="model",
            output_format="mp3_44100_128",
        )
    message = str(error.value)
    assert "chunk 1 of 1" in message
    assert "listen voices" in message


def test_list_voices_puts_the_default_voices_first():
    class Voice:
        def __init__(self, voice_id, name, category):
            self.voice_id, self.name, self.category = voice_id, name, category

    class Response:
        voices = [
            Voice("c1", "My clone", "cloned"),
            Voice("p2", "Roger", "premade"),
            Voice("p1", "Aria", "premade"),
        ]

    class FakeVoicesClient:
        def __init__(self):
            self.voices = self
            self.kwargs = None

        def get_all(self, **kwargs):
            self.kwargs = kwargs
            return Response()

    client = FakeVoicesClient()
    found = list_voices(client)

    assert [voice.name for voice in found] == ["Aria", "Roger", "My clone"]
    assert client.kwargs == {"show_legacy": False}, "legacy library voices are left out"


def test_list_voices_reports_a_refusal_as_one_line():
    class FailingVoicesClient:
        def __init__(self):
            self.voices = self

        def get_all(self, **_):
            raise FakeApiError(401, {"detail": {"message": "Invalid API key."}})

    with pytest.raises(ListenError) as error:
        list_voices(FailingVoicesClient())
    assert "could not list voices" in str(error.value)
    assert "ELEVENLABS_API_KEY" in str(error.value)


def test_drop_stale_chunks_removes_files_past_the_new_end(tmp_path):
    for index in range(4):
        (tmp_path / f"{index:03d}.mp3").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("keep me")

    drop_stale_chunks(tmp_path, keep=2)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["000.mp3", "001.mp3", "notes.txt"]
