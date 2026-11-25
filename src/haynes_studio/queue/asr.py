"""Direct Wyoming transport for the build's existing transcript check."""

import asyncio
import io
import json
import wave

from haynes_studio.adapters.whisper import MAX_ANSWER_BYTES, TranscriptRequest
from haynes_studio.build.errors import BuildError


class WyomingTranscriber:
    name = "Wyoming ASR (Studio transcript check)"

    def __init__(self, host, port=10300):
        self.host, self.port = host, port

    def transcribe(self, wav):
        request = TranscriptRequest(wav)
        try:
            return asyncio.run(asyncio.wait_for(self._transcribe(request.wav), timeout=45))
        except (OSError, ValueError, EOFError) as error:
            raise BuildError("asr.unavailable", "Wyoming did not return a transcript",
                             stage="checks") from error

    async def _transcribe(self, wav):
        reader, writer = await asyncio.open_connection(self.host, self.port, limit=8192)
        try:
            with wave.open(io.BytesIO(wav), "rb") as audio:
                format_ = {"rate": audio.getframerate(), "width": audio.getsampwidth(),
                           "channels": audio.getnchannels()}
                await _send(writer, "transcribe", {"language": "en"})
                await _send(writer, "audio-start", format_)
                while chunk := audio.readframes(8000):
                    await _send(writer, "audio-chunk", format_, chunk)
                await _send(writer, "audio-stop", {})
            while header := await reader.readline():
                event = json.loads(header)
                if not isinstance(event, dict):
                    break
                data_length = event.get("data_length", 0)
                payload_length = event.get("payload_length", 0)
                if any(type(length) is not int or not 0 <= length <= MAX_ANSWER_BYTES
                       for length in (data_length, payload_length)):
                    break
                data = event.get("data", {})
                if data_length:
                    data = json.loads(await reader.readexactly(data_length))
                if payload_length:
                    await reader.readexactly(payload_length)
                if event.get("type") == "transcript" and isinstance(data, dict) and isinstance(data.get("text"), str):
                    return data["text"]
                if event.get("type") == "error":
                    break
            raise ValueError("Missing Wyoming transcript")
        finally:
            writer.close()
            await writer.wait_closed()


async def _send(writer, event, data, payload=b""):
    encoded = json.dumps(data).encode()
    header = {"type": event, "data_length": len(encoded), "payload_length": len(payload)}
    writer.write(json.dumps(header).encode() + b"\n" + encoded + payload)
    await writer.drain()
