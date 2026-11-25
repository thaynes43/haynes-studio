"""Verify the worker's direct service transports with synthetic responses."""

import asyncio
import json
from hashlib import sha256

import httpx
import pytest

from haynes_studio.adapters.comfyui import ImageEdit, TextToImage, graph_sha256
from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.fakes import synthetic_png
from haynes_studio.adapters.kokoro import SpeechRequest
from haynes_studio.queue.media_services import ComfyHTTP, WyomingKokoro
from haynes_studio.queue.media_worker import ImageQueueBusy

ORIGIN = "http://image.example.invalid"
PROMPT_ID = "aaa5b8d4-a7a1-4b88-b705-a9a3cb055bee"


@pytest.mark.parametrize("edit", [False, True])
def test_comfy_pinned_graph_fence_queue_and_output(edit):
    data = synthetic_png()
    if edit:
        request = ImageEdit("job-demo", "board-photo", "A tabletop", 7, data)
    else:
        request = TextToImage("job-demo", "board-photo", "A tabletop", 7, 64, 64)
    seen = []
    graph = {}

    def serve(http):
        path = http.url.path
        seen.append(path)
        if path == "/upload/image":
            assert request.upload_name.encode() in http.content
            assert data in http.content
            return httpx.Response(200, json={"name": request.upload_name, "subfolder": ""})
        if path == "/queue":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if path == "/prompt":
            assert seen[-3:] == ["fence", "/queue", "/prompt"]
            payload = json.loads(http.content)
            assert payload["client_id"] == "studio-job-demo"
            graph.update(payload["prompt"])
            save = next(node for node in graph.values() if node["class_type"] == "SaveImage")
            assert save["inputs"]["filename_prefix"] == "studio/job-demo/board-photo"
            return httpx.Response(200, json={"prompt_id": PROMPT_ID})
        if path == f"/history/{PROMPT_ID}":
            return httpx.Response(200, json={PROMPT_ID: {
                "status": {"completed": True}, "outputs": {"1": {"images": [{
                    "filename": "board-photo_00001_.png", "subfolder": "studio/job-demo", "type": "output",
                }]}},
            }})
        assert path == "/view" and dict(http.url.params) == {
            "filename": "board-photo_00001_.png", "subfolder": "studio/job-demo", "type": "output",
        }
        return httpx.Response(200, content=data)

    with httpx.Client(base_url=ORIGIN, transport=httpx.MockTransport(serve)) as http:
        result = ComfyHTTP(http).render(request, before_submit=lambda: seen.append("fence"))
    assert result.prompt_id == PROMPT_ID and result.sha256 == sha256(data).hexdigest()
    assert result.graph_sha256 == graph_sha256(graph)
    expected = ["fence", "/queue", "/prompt", f"/history/{PROMPT_ID}", "/view"]
    assert seen == (["/upload/image", *expected] if edit else expected)


@pytest.mark.parametrize(("queue", "error"), [
    ({"queue_running": [], "queue_pending": [["household"]]}, ImageQueueBusy),
    ({"queue_running": [], "queue_pending": "unknown"}, AdapterError),
])
def test_comfy_busy_or_unknown_queue_never_submits(queue, error):
    def serve(http):
        assert http.method == "GET" and http.url.path == "/queue"
        return httpx.Response(200, json=queue)

    with httpx.Client(base_url=ORIGIN, transport=httpx.MockTransport(serve)) as http:
        client = ComfyHTTP(http)
        request = TextToImage("job-demo", "asset-candidate", "A tabletop", 1, 64, 64)
        with pytest.raises(error):
            client.render(request, before_submit=lambda: None)


@pytest.mark.parametrize("inconsistent", [False, True])
def test_kokoro_wyoming_exchange_is_bounded_and_measures_pcm(monkeypatch, inconsistent):
    wire = bytearray()
    pcm = b"\x00\x00" * 800

    class Writer:
        def write(self, data):
            wire.extend(data)

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    def event(type_, data, audio=b""):
        payload = json.dumps(data).encode()
        frame = {"type": type_, "data_length": len(payload), "payload_length": len(audio)}
        return json.dumps(frame).encode() + b"\n" + payload + audio

    async def open_connection(host, port, *, limit):
        assert (host, port, limit) == ("voice.example.invalid", 10210, 8192)
        fmt = {"channels": 1, "width": 2, "rate": 24000}
        reader = asyncio.StreamReader(limit=limit)
        reader.feed_data(event("audio-start", fmt))
        reader.feed_data(event("audio-chunk", {**fmt, "rate": 16000} if inconsistent else fmt, pcm))
        reader.feed_data(event("audio-stop", {}))
        reader.feed_eof()
        return reader, Writer()

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    client = WyomingKokoro("voice.example.invalid")
    request = SpeechRequest("af_heart", "A small workshop")
    if inconsistent:
        with pytest.raises(AdapterError):
            client.synthesize(request)
    else:
        take = client.synthesize(request)
        assert take.frames == 800 and take.rate == 24000 and take.channels == 1
        assert take.sha256 == sha256(take.wav).hexdigest()
    header, data = wire.split(b"\n", 1)
    assert json.loads(header)["type"] == "synthesize"
    assert json.loads(data) == {"text": request.text, "voice": {"name": request.voice}}
