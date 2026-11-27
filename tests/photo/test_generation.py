from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import replace

import pytest
from PIL import Image

from haynes_studio.adapters.comfyui import ImageClient
from haynes_studio.adapters.fakes import FakeComfyUI, FakeRunner
from haynes_studio.canonical.derive import photo_state
from haynes_studio.errors import ContractError
from haynes_studio.layered.photo import compose_photo
from haynes_studio.library import Library
from haynes_studio.photo import (
    can_select_photo,
    compose_layered_photo,
    generate_photo,
    photo_facts,
    plan_photo,
    record_photo,
)
from tests.library.fixtures import register
from tests.photo.conftest import BY, NOW


def test_generation_uses_one_edit_with_all_frozen_sources(world):
    story, board, library, ids, fetch, publish = world
    plan = plan_photo(story, board, library)
    fake = FakeComfyUI()
    prepared = generate_photo(plan, client=ImageClient(FakeRunner(fake)), fetch=fetch,
                              job="photo-test", seed=17, licences=register())
    outcome = record_photo(prepared, library, publish=publish, by=BY, now=NOW)
    document = outcome.library.document(outcome.version.id)
    gen = document["provenance"]["generator"]
    assert document["provenance"]["origin"] == "generated"
    assert document["provenance"]["created_by"] == {"kind": "agent", "key_id": BY.key_id}
    assert document["provenance"]["external"] is None
    assert document["licence"]["commercial_use"] == "noncommercial"
    assert gen["source_asset_version_ids"] == list(ids[:2])
    assert gen["params"]["source_assets"] == [
        {"version_id": ident, "sha256": library.version(ident).content.sha256} for ident in ids[:2]
    ]
    assert gen["prompt"] == board.photo.prompt and gen["seed"] == 17
    assert gen["model"] == "Qwen-Image 2.1"
    assert gen["engine_job_id"] and len(gen["workflow_sha256"]) == 64
    assert gen["params"]["input_signature"] == plan.input_signature

    payload, = fake.payloads
    canvas = base64.b64decode(payload["upload"]["b64"])
    assert hashlib.sha256(canvas).hexdigest() == gen["params"]["reference_png_sha256"]
    with Image.open(io.BytesIO(canvas)) as image:
        assert image.size == (720, 1280)
        assert image.getpixel((360, 320)) == (255, 0, 0)
        assert image.getpixel((360, 960)) == (0, 0, 255)
    assert can_select_photo(outcome.version, plan, story, board, outcome.library)
    with pytest.raises(TypeError):
        outcome.version.provenance["generator"]["params"]["input_signature"] = "changed"
    assert Library.from_version_documents([document]).document(outcome.version.id) == document


def test_photo_facts_use_metadata_from_recorded_only_source(world):
    story, board, library, ids, fetch, publish = world
    plan = plan_photo(story, board, library)
    prepared = generate_photo(plan, client=ImageClient(FakeRunner(FakeComfyUI())), fetch=fetch,
                              job="photo-archive", seed=17)
    outcome = record_photo(prepared, library, publish=publish, by=BY, now=NOW)
    archived = Library.from_version_documents(
        {**doc, "recorded_without_media": True} if doc["id"] == ids[0] else doc
        for doc in outcome.library.documents()
    )
    selected = replace(board, photo=replace(board.photo, current_version_id=outcome.version.id))
    assert photo_state(selected, photo_facts(replace(story, boards=(selected,)), archived)) == "current"


@pytest.mark.parametrize("edit", ["prompt", "asset", "order", "selection", "removed", "aspect"])
def test_edits_during_generation_preserve_the_result_without_selecting_it(world, edit):
    story, board, library, ids, fetch, publish = world
    plan = plan_photo(story, board, library)
    live_story, live_board = story, board

    class EditingClient(ImageClient):
        def render(self, request):
            nonlocal live_story, live_board
            photo = live_board.photo
            if edit == "prompt":
                photo = replace(photo, prompt="A different prompt.")
            elif edit == "asset":
                photo = replace(photo, input_asset_version_ids=(ids[0], ids[2]))
            elif edit == "order":
                photo = replace(photo, input_asset_version_ids=ids[:2][::-1])
            elif edit == "selection":
                photo = replace(photo, current_version_id=ids[2])
            elif edit == "aspect":
                live_story = replace(live_story, media_kind="video")
            live_board = None if edit == "removed" else replace(live_board, photo=photo)
            return super().render(request)

    prepared = generate_photo(plan, client=EditingClient(FakeRunner(FakeComfyUI())),
                              fetch=fetch, job="photo-race", seed=5)
    outcome = record_photo(prepared, library, publish=publish, by=BY, now=NOW)
    assert outcome.library.get(outcome.version.id) is outcome.version
    assert not can_select_photo(outcome.version, plan, live_story, live_board, outcome.library)
    if edit in {"prompt", "asset", "order", "aspect"}:
        selected = replace(live_board, photo=replace(live_board.photo,
                                                   current_version_id=outcome.version.id))
        embedded = replace(live_story, boards=(selected,))
        facts = outcome.library.facts().merged(photo_facts(embedded, outcome.library))
        assert photo_state(selected, facts) == "stale"


def test_generation_refuses_damaged_source_or_engine_bytes(world):
    story, board, library, _, fetch, _ = world
    plan = plan_photo(story, board, library)
    fake = FakeComfyUI()
    client = ImageClient(FakeRunner(fake))
    with pytest.raises(ContractError, match=r"photo.hash_mismatch at /photo/source"):
        generate_photo(plan, client=client, fetch=lambda *_: b"wrong", job="photo-test", seed=1)
    assert not fake.payloads

    class WrongHash(ImageClient):
        def render(self, request):
            return replace(super().render(request), sha256="0" * 64)

    with pytest.raises(ContractError, match=r"photo.hash_mismatch at /photo/result"):
        generate_photo(plan, client=WrongHash(FakeRunner(fake)), fetch=fetch,
                       job="photo-test", seed=1)


def test_text_only_generation_and_non_input_edits(world):
    story, board, library, _, fetch, publish = world
    board = replace(board, photo=replace(board.photo, prompt="A quiet café", input_asset_version_ids=()))
    plan = plan_photo(story, board, library)
    fake = FakeComfyUI()
    prepared = generate_photo(plan, client=ImageClient(FakeRunner(fake)), fetch=fetch,
                              job="photo-test", seed=7)
    payload, = fake.payloads
    assert "upload" not in payload
    assert (payload["graph"]["5"]["inputs"]["width"], payload["graph"]["5"]["inputs"]["height"]) == (720, 1280)
    outcome = record_photo(prepared, library, publish=publish, by=BY, now=NOW)
    edited = replace(board, title="New title", photo=replace(board.photo, prompt="A quiet cafe\u0301"))
    assert can_select_photo(outcome.version, plan, story, edited, outcome.library)
    chosen = replace(edited, photo=replace(edited.photo, current_version_id=outcome.version.id))
    facts = photo_facts(replace(story, boards=(chosen,)), outcome.library)
    assert photo_state(chosen, facts) == "current"


def test_d51_uses_the_layered_adapter_and_ignores_photo_prompt(world):
    story, board, library, ids, fetch, publish = world
    original = story.ordered_boards()[0]
    board = replace(board, method=original.method,
                    cast=(replace(original.cast[0], asset_version_id=ids[0]),))
    story = replace(story, set=replace(story.set, asset_version_id=ids[1]))
    plan = plan_photo(story, board, library)
    prepared = compose_layered_photo(plan, fetch=fetch)

    def read(digest):
        source = next(item for item in plan.sources if item.content.sha256 == digest)
        return io.BytesIO(fetch(source.content.locator, digest))

    assert prepared.image.png == compose_photo(plan.layers, read)
    outcome = record_photo(prepared, library, publish=publish, by=BY, now=NOW)
    doc = outcome.library.document(outcome.version.id)
    assert doc["provenance"]["origin"] == "derived"
    assert doc["provenance"]["generator"]["role"] == "composite"
    assert doc["provenance"]["generator"]["params"]["composite"] == plan.layers.document()
    assert (doc["content"]["width"], doc["content"]["height"]) == (1080, 1920)

    # Even a typed, derived composite must have signed the role list to pin masks.
    doc["provenance"]["generator"]["params"]["composite"]["foreground"] = {
        "roles": [{"version_id": ids[2], "name": "reference"}],
    }
    selected = replace(board, photo=replace(board.photo, current_version_id=outcome.version.id))
    recorded = Library.from_version_documents([*library.documents(), doc])
    assert photo_state(selected, photo_facts(replace(story, boards=(selected,)), recorded)) == "current"

    edited = replace(board, photo=replace(board.photo, prompt="Does not affect D51"))
    assert can_select_photo(outcome.version, plan, story, edited, outcome.library)
    changed = replace(story, set=replace(story.set, asset_version_id=ids[2]))
    assert not can_select_photo(outcome.version, plan, changed, board, outcome.library)
    with pytest.raises(ContractError, match="photo.method_invalid"):
        generate_photo(plan, client=ImageClient(FakeRunner()), fetch=fetch, job="photo-test", seed=1)
