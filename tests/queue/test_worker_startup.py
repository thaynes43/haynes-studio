"""Run the worker's CLI against a recording HTTP transport."""

import json
import secrets
import string
import sys

import httpx
import pytest

from haynes_studio.model_register import load_model_register
from haynes_studio.queue import worker
from haynes_studio.queue.worker import main

from .fake_wan import STORY


@pytest.mark.parametrize("legacy", [False, True], ids=["registered", "legacy"])
def test_worker_uses_the_registered_bearer_format_for_claims(tmp_path, monkeypatch, legacy):
    secret = (secrets.token_urlsafe(32) if legacy else
              "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(48)))
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
    if legacy:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 2
        assert not requests
        return
    main()
    assert requests == [("POST", "http://studio.example.invalid/internal/v1/work/claim", "Bearer worker_" + secret)]


@pytest.mark.parametrize("lane", ["run", "image", "voice"])
@pytest.mark.parametrize("override", [False, True], ids=["packaged", "override"])
def test_every_worker_lane_reads_packaged_or_overridden_register(
        lane, override, tmp_path, monkeypatch):
    monkeypatch.delenv("STUDIO_MODEL_REGISTER", raising=False)
    document = load_model_register()
    if override:
        document["engines"] = [dict(document["engines"][0], key="fixture-register")]
        path = tmp_path / "models.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        monkeypatch.setenv("STUDIO_MODEL_REGISTER", str(path))
    store, stage = tmp_path / "store", tmp_path / "stage"
    store.mkdir()
    stage.mkdir()
    for name, value in {
        "STUDIO_API_URL": "http://studio.example.invalid",
        "STUDIO_WAN_URL": "http://wan.example.invalid",
        "STUDIO_WAN_STORY_URL": STORY,
        "STUDIO_STORE_ROOT": str(store),
        "STUDIO_BUILD_STAGE_ROOT": str(stage),
        "STUDIO_WORKER_TOKEN": secrets.token_hex(24),
        "STUDIO_ASR_HOST": "asr.example.invalid",
        "STUDIO_TTS_HOST": "tts.example.invalid",
        "STUDIO_COMFYUI_URL": "http://comfyui.example.invalid",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)
    captured = []
    monkeypatch.setattr(worker, "_serve", lambda instance, once: captured.append(instance))
    monkeypatch.setattr(sys, "argv", ["studio-worker", "--lane", lane, "--once"])

    main()

    assert len(captured) == 1
    if lane == "run":
        assert captured[0].register == document
    else:
        assert {engine.key for engine in captured[0].licences.engines} == {
            engine["key"] for engine in document["engines"]}
