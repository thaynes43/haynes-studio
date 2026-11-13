"""Motion versions in the library (story 457): the same record imported twice is the
same version; a changed input is the next version, and the earlier one stays
unchanged (D15, D17)."""

from __future__ import annotations

import copy

import pytest

from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError
from haynes_studio.library import EMPTY, Library, VersionRequest, import_version, pin
from haynes_studio.library.model import Content, Licence, Scope, content_fields, locator_for
from haynes_studio.motion.winter_menu import complete_block
from tests.motion.fixtures import NOW, PRODUCTION, loop_block, sha, timed_block, version

BY = Principal.cli("studio motion import", "https://authentik.example.invalid/", "subject")
KEY = "fixture:loop:a-proud"


def request(block, clip=sha("c"), *, job="job-311", state="promoted"):
    block = complete_block(block, clip)
    return VersionRequest(
        kind="motion", name="A proud doll loop", scope=Scope(PRODUCTION),
        capabilities=("motion_clip",),
        content=Content(sha256=clip, bytes=1234, media_type="video/mp4",
                        locator=locator_for(clip, "video/mp4", PRODUCTION)),
        provenance={"origin": "generated",
                    "generator": {"role": "video", "model": "Wan2.2 TI2V-5B",
                                  "engine_job_id": job},
                    "external": None, "source_key": KEY},
        licence=Licence.unknown("fixture"), state=state, motion=block)


def _with_source(block, job):
    block = copy.deepcopy(block)
    block["source"]["engine_job_id"] = job
    return block


def imported(*requests):
    library, outcomes = EMPTY, []
    for item in requests:
        outcome = import_version(library, item, by=BY, now=NOW)
        library = outcome.library
        outcomes.append(outcome)
    return library, outcomes


def test_the_same_record_imported_twice_is_the_same_version():
    library, (first, second) = imported(request(loop_block()), request(loop_block()))
    assert first.created and not second.created
    assert second.version == first.version
    assert len(library.versions) == 1


def test_a_version_pins_its_identity():
    library, (outcome,) = imported(request(loop_block()))
    version = outcome.version
    assert library.pin(version.id) == version.motion["keys"]["identity"]
    assert library.pin(version.id) != version.content.sha256


def test_a_motion_version_without_a_block_still_pins_its_bytes():
    library = Library.from_version_documents([version(None, n=10, clip=sha("c"))])
    only = next(iter(library.versions.values()))
    assert library.pin(only.id) == sha("c")
    assert only.motion is None


@pytest.mark.parametrize("change", [
    lambda b: b["keying"].update(decal_version="erase-v3"),
    lambda b: b["keying"].update(key_thresholds={"lo": 25, "hi": 70}),
    lambda b: b["source"].update(seed=312),
    lambda b: b.update(still_sha256=sha("e")),
    lambda b: b["source"].update(image_sha256=sha("7")),
])
def test_a_changed_input_is_the_next_version_and_nothing_is_overwritten(change):
    second_block = loop_block()
    change(second_block)
    library, (first, second) = imported(request(loop_block()), request(second_block))
    assert second.created and second.version.number == 2
    assert second.version.asset_id == first.version.asset_id
    assert library.version(first.version.id) == first.version  # version 1 unchanged
    assert library.pin(first.version.id) != library.pin(second.version.id)
    # The same bytes keyed another way: both versions name one clip.
    assert first.version.content.sha256 == second.version.content.sha256


def test_the_same_identity_with_other_provenance_is_refused():
    with pytest.raises(ContractError) as caught:
        # Another engine job is not an identity input, but versions never change (D15).
        imported(request(loop_block()), request(_with_source(loop_block(), "job-999"),
                                                 job="job-999"))
    assert [v.rule for v in caught.value.violations] == ["idempotency.mismatch"]


def test_a_new_record_is_validated_on_write():
    bad = complete_block(timed_block(), sha("c"))
    bad["keys"]["identity"] = "sha256:" + "1" * 64
    item = request(timed_block())
    item = VersionRequest(**{**item.__dict__, "motion": bad})
    with pytest.raises(ContractError) as caught:
        imported(item)
    assert ("motion.identity_mismatch", "/motion/keys/identity") in {
        (v.rule, v.path) for v in caught.value.violations}


def test_the_block_is_immutable_content_and_round_trips():
    library, (outcome,) = imported(request(loop_block()))
    document = library.document(outcome.version.id)
    assert document["motion"] == complete_block(loop_block(), sha("c"))
    assert content_fields(outcome.version)["motion"] == document["motion"]
    again = Library.from_version_documents(library.documents())
    assert again.version(outcome.version.id) == outcome.version
    assert pin(again.version(outcome.version.id), again.asset(outcome.version.asset_id)) == \
        library.pin(outcome.version.id)
