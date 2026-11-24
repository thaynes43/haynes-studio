"""Fake Wyoming event stream for the production worker's ASR transport."""

import json

import pytest

from haynes_studio.build.errors import BuildError
from haynes_studio.queue.asr import WyomingTranscriber
from tests.support.synthetic import write_sine_wav


@pytest.mark.parametrize("response", ["transcript", "error"])
def test_wyoming_transcriber_sends_pcm_and_reads_a_bounded_response(tmp_path, monkeypatch, response):
    transmitted = []

    class Writer:
        def write(self, data):
            transmitted.append(data)

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def connection(host, port, *, limit):
        from asyncio import StreamReader

        assert (host, port, limit) == ("asr.example.invalid", 10300, 8192)
        stream = StreamReader(limit=limit)
        data = json.dumps({"text": "Fixture transcript"}).encode()
        stream.feed_data(json.dumps({"type": response, "data_length": len(data)}).encode() + b"\n" + data)
        stream.feed_eof()
        return stream, Writer()

    monkeypatch.setattr("asyncio.open_connection", connection)
    wav = write_sine_wav(tmp_path / "fixture.wav", seconds=0.1).read_bytes()
    transcriber = WyomingTranscriber("asr.example.invalid")
    if response == "error":
        with pytest.raises(BuildError, match="Wyoming did not return"):
            transcriber.transcribe(wav)
    else:
        assert transcriber.transcribe(wav) == "Fixture transcript"
    events = [json.loads(raw.split(b"\n", 1)[0]) for raw in transmitted]
    assert [item["type"] for item in events] == ["transcribe", "audio-start", "audio-chunk", "audio-stop"]
    assert events[2]["payload_length"] == 3200
