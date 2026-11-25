"""Run the worker's CLI against a recording HTTP transport."""

import secrets
import string
import sys

import httpx

from haynes_studio.queue.worker import main

from .fake_wan import STORY


def test_worker_uses_the_registered_bearer_format_for_claims(tmp_path, monkeypatch):
    secret = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(48))
    model_register = tmp_path / "models.json"
    model_register.write_text("{}", encoding="utf-8")
    store, stage = tmp_path / "store", tmp_path / "stage"
    store.mkdir()
    stage.mkdir()
    for name, value in {
        "STUDIO_API_URL": "http://studio.example.invalid",
        "STUDIO_WAN_URL": "http://wan.example.invalid",
        "STUDIO_WAN_STORY_URL": STORY,
        "STUDIO_MODEL_REGISTER": str(model_register),
        "STUDIO_STORE_ROOT": str(store),
        "STUDIO_BUILD_STAGE_ROOT": str(stage),
        "STUDIO_WORKER_TOKEN": secret,
        "STUDIO_ASR_HOST": "asr.example.invalid",
    }.items():
        monkeypatch.setenv(name, value)

    requests = []

    def record(request):
        requests.append((request.method, str(request.url), request.headers.get("Authorization")))
        return httpx.Response(204)

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **options: real_client(transport=httpx.MockTransport(record), **options))
    monkeypatch.setattr(sys, "argv", ["studio-worker", "--once"])
    main()
    assert requests == [("POST", "http://studio.example.invalid/internal/v1/work/claim", "Bearer worker_" + secret)]
