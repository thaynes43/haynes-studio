from __future__ import annotations

import hashlib
import io
from dataclasses import replace

import pytest
from PIL import Image

from haynes_studio.adapters.comfyui import ImageClient
from haynes_studio.adapters.fakes import FakeComfyUI, FakeRunner
from haynes_studio.assets import candidate_result, generate_candidate, plan_candidate, record_candidate
from haynes_studio.canonical import Story
from haynes_studio.canonical.model import Principal, to_document
from haynes_studio.errors import ContractError
from haynes_studio.library import EMPTY, Library, promote, set_labels
from haynes_studio.photo import generate_photo, plan_photo
from haynes_studio.store import PRESENT, LocalStore
from tests.canonical.fixtures import example
from tests.library.fixtures import register

BY = Principal("human", iss="https://issuer.invalid", sub="operator")
NOW = "2026-11-24T20:00:00Z"
LATER = "2026-11-24T20:15:00Z"
JOB_ID = "job_00000000000000000000000001"
ASSET_ID = "ast_00000000000000000000000001"
PRODUCTION_ID = "prd_00000000000000000000000001"


def plan(**changes):
    fields = dict(job_id=JOB_ID, asset_id=ASSET_ID, kind="cast", name=" Cafe\u0301 doll ",
                  prompt="A felt doll at a cafe\u0301", production_id=PRODUCTION_ID,
                  seed=408, labels=("invented",), by=BY)
    return plan_candidate(**(fields | changes))


@pytest.mark.parametrize(("kind", "capability"), [
    ("cast", "opaque_photo"), ("costume", "opaque_photo"),
    ("set", "opaque_plate"), ("prop", "opaque_photo"),
])
def test_generate_record_and_promote(tmp_path, kind, capability):
    fake = FakeComfyUI(waited_s=1.25, render_s=2.5)
    store = LocalStore(tmp_path)
    job_plan = plan(kind=kind)
    assert candidate_result(EMPTY, job_plan) is None
    prepared = generate_candidate(job_plan, client=ImageClient(FakeRunner(fake)), licences=register())
    made = record_candidate(prepared, EMPTY, store=store, now=NOW)
    candidate = made.version
    assert made.created and (candidate.asset_id, candidate.number) == (ASSET_ID, 1)
    assert (candidate.kind, candidate.state, candidate.capabilities) == (kind, "candidate", (capability,))
    assert made.library.search(kind=kind, production_id=PRODUCTION_ID) == ()
    assert made.library.latest(ASSET_ID) is None
    assert made.library.search(include_candidates=True) == (candidate,)
    assert candidate_result(made.library, job_plan) == candidate

    payload, = fake.payloads
    digest = hashlib.sha256(prepared.image.png).hexdigest()
    doc = made.library.document(candidate.id)
    gen = doc["provenance"]["generator"]
    assert "upload" not in payload
    assert doc["name"] == "Café doll"
    assert doc["provenance"]["source_key"] == f"asset-candidate:{JOB_ID}"
    assert doc["provenance"]["created_by"] == {"kind": "human", "iss": BY.iss, "sub": BY.sub}
    assert doc["provenance"]["origin"] == "generated"
    assert gen["model"] == "Qwen-Image 2.1" and gen["engine_job_id"]
    assert gen["seed"] == 408 and gen["prompt"] == "A felt doll at a café"
    assert len(gen["workflow_sha256"]) == 64
    assert gen["params"]["input_signature"] == job_plan.input_signature
    assert (gen["params"]["waited_s"], gen["params"]["render_s"]) == (1.25, 2.5)
    assert doc["licence"]["commercial_use"] == "noncommercial"
    assert made.library.pin(candidate.id) == digest
    assert store.verify(candidate.content.locator, digest) == PRESENT
    with store.open(candidate.content.locator) as file, Image.open(file) as image:
        assert image.mode == "RGB" and image.size == (candidate.content.width, candidate.content.height)

    reloaded = Library.from_version_documents([doc])
    promoted = promote(reloaded, candidate.id, by=BY, now=LATER)
    again = promote(promoted.library, candidate.id, by=BY, now=LATER)
    assert not again.created and again.library is promoted.library
    assert promoted.version == replace(candidate, state="promoted")
    assert promoted.library.pin(candidate.id) == digest
    assert promoted.library.latest(ASSET_ID) == promoted.version
    assert promoted.library.search(kind=kind, production_id=PRODUCTION_ID, labels=["invented"]) == (promoted.version,)
    assert promoted.library.search(production_id="prd_00000000000000000000000002") == ()

    renamed = set_labels(promoted.library, ASSET_ID, ["new label"], now=LATER)
    writes = []
    retry = record_candidate(prepared, renamed, store=LocalStore(tmp_path, on_step=writes.append), now=LATER)
    assert not writes and not retry.created
    assert retry.library is renamed and retry.version == promoted.version
    assert retry.library.asset(ASSET_ID).labels == ("new label",)


def test_declined_candidate_retained_after_another_is_promoted_and_used_in_board_photo(tmp_path):
    original = Story.from_document(example("valid/story-winter-menu-r4.json"))
    store = LocalStore(tmp_path)
    fake = FakeComfyUI()
    client = ImageClient(FakeRunner(fake))
    first = plan(production_id=None)
    declined = record_candidate(generate_candidate(first, client=client), EMPTY, store=store, now=NOW)
    second = plan(job_id=JOB_ID[:-1] + "2", asset_id=ASSET_ID[:-1] + "2",
                  production_id=original.production_id, seed=409)
    fresh = record_candidate(generate_candidate(second, client=client), declined.library, store=store, now=NOW)
    picked = promote(fresh.library, fresh.version.id, by=BY, now=LATER)
    assert picked.library.capabilities(picked.version.id) == {"opaque_photo"}
    assert picked.library.search(production_id=original.production_id) == (picked.version,)
    assert candidate_result(picked.library, first) == declined.version
    assert declined.version.content.locator.startswith("library/")
    assert store.verify(declined.version.content.locator, declined.version.content.sha256) == PRESENT

    board = original.ordered_boards()[0]
    board = replace(board, method=replace(board.method, layer="whole_frame"),
                    photo=replace(board.photo, prompt="A portrait of the felt doll",
                                  input_asset_version_ids=(picked.version.id,)))
    assert picked.library.search(board=to_document(board)) == (picked.version,)

    def fetch(locator, expected_sha256):
        assert locator == picked.version.content.locator and expected_sha256 == picked.version.content.sha256
        with store.open(locator) as file:
            return file.read()

    photo = generate_photo(plan_photo(original, board, picked.library), client=client, fetch=fetch,
                           job="candidate-reference-test", seed=10)
    assert photo.generator["source_asset_version_ids"] == (picked.version.id,)
    assert photo.generator["params"]["source_assets"][0]["sha256"] == picked.library.pin(picked.version.id)
    assert "upload" in fake.payloads[-1] and len(fake.payloads) == 3


def test_job_conflict_cannot_replace_a_candidate_or_publish_another_result(tmp_path):
    store = LocalStore(tmp_path)
    client = ImageClient(FakeRunner(FakeComfyUI()))
    job_plan = plan()
    prepared = generate_candidate(job_plan, client=client)
    made = record_candidate(prepared, EMPTY, store=store, now=NOW)
    with pytest.raises(ContractError, match=r"idempotency.mismatch at /job_id") as error:
        candidate_result(made.library, plan(seed=409))
    assert error.value.violations[0].status == "conflict"
    with pytest.raises(ContractError, match=r"ref.duplicate at /asset_id"):
        candidate_result(made.library, plan(job_id=JOB_ID[:-1] + "2"))

    different = generate_candidate(plan(seed=409), client=client)
    new_sha256 = hashlib.sha256(different.image.png).hexdigest()
    assert new_sha256 != made.version.content.sha256
    with pytest.raises(ContractError, match=r"idempotency.mismatch at /job_id"):
        record_candidate(replace(prepared, image=different.image), made.library, store=store, now=NOW)
    assert not list(tmp_path.rglob(new_sha256 + ".png"))
    assert candidate_result(made.library, job_plan) == made.version


def test_retry_after_metadata_commit_failure_reuses_the_private_blob(tmp_path):
    fake = FakeComfyUI()
    job_plan = plan()
    prepared = generate_candidate(job_plan, client=ImageClient(FakeRunner(fake)))
    store = LocalStore(tmp_path)
    uncommitted = record_candidate(prepared, EMPTY, store=store, now=NOW)
    committed = record_candidate(prepared, EMPTY, store=store, now=LATER)
    assert committed.created and committed.version.content == uncommitted.version.content
    assert len(list(tmp_path.rglob("*.png"))) == 1
    assert len(fake.payloads) == 1


def test_human_only_and_invalid_candidate_inputs(tmp_path):
    actor = Principal("agent", key_id="key_00000000000000000000000001")
    with pytest.raises(ValueError, match="generate_asset_candidate requires a human"):
        plan(by=actor)
    with pytest.raises(ContractError, match="schema.invalid at /kind"):
        plan(kind="motion")
    with pytest.raises(ContractError, match="id.malformed at /job_id"):
        plan(job_id="../another-job")
    with pytest.raises(ContractError, match="ref.duplicate at /labels/1"):
        plan(labels=("café", "cafe\u0301"))
    prepared = generate_candidate(plan(), client=ImageClient(FakeRunner(FakeComfyUI())))
    made = record_candidate(prepared, EMPTY, store=LocalStore(tmp_path), now=NOW)
    with pytest.raises(ValueError, match="promote_asset_version requires a human"):
        promote(made.library, made.version.id, by=actor, now=LATER)


def test_generation_refuses_corrupt_or_invalid_engine_output():
    class InvalidPng(ImageClient):
        def render(self, request):
            data = b"not an image"
            return replace(super().render(request), png=data, sha256=hashlib.sha256(data).hexdigest())

    class InvalidDigest(ImageClient):
        def render(self, request):
            return replace(super().render(request), sha256="0" * 64)

    with pytest.raises(ContractError, match=r"photo.image_invalid at /content"):
        generate_candidate(plan(), client=InvalidPng(FakeRunner(FakeComfyUI())))
    with pytest.raises(ContractError, match=r"photo.hash_mismatch at /content/sha256"):
        generate_candidate(plan(), client=InvalidDigest(FakeRunner(FakeComfyUI())))
