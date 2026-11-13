"""``studio.job/v1``: the schema and validator, the read-only model, and the state
machine of VOICE-4, one test per transition."""

from __future__ import annotations

import copy
import itertools

import pytest

from haynes_studio.canonical.ids import Minter
from haynes_studio.errors import ContractError
from haynes_studio.library.model import input_signature
from haynes_studio.voice import Job, cancel, fail, generating, new_job, start, succeed, validate_job
from haynes_studio.voice.jobs import ALLOWED, TRANSITION
from haynes_studio.voice.model import STATUSES
from tests.canonical.fixtures import NOW
from tests.library.fixtures import BY
from tests.voice.fixtures import LATER, fresh_r4

RESULT = "asv_01M7AK8S89SE0FB8NM89KS1RMZ"
OTHER_BOARD = "brd_01M79V9FC00000000000000008"


@pytest.fixture(scope="module")
def voice_job() -> Job:
    studio = fresh_r4()
    return studio.request(studio.board(8)["id"]).job


def rules(document, context="write"):
    return {(v.rule, v.path) for v in validate_job(document, context=context)}


def photo_job() -> Job:
    signature = "sha256:" + "a" * 64
    return new_job("photo", OTHER_BOARD, signature, by=BY, now=NOW,
                   minter=Minter(clock=lambda: 1_800_000_000_000, random_bits=lambda: 9))


# Validator --------------------------------------------------------------------------------


def test_a_requested_voice_job_is_valid_and_round_trips(voice_job):
    document = voice_job.to_document()
    assert document["schema"] == "studio.job/v1"
    assert (document["kind"], document["status"]) == ("voice", "queued")
    assert document["result_version_id"] is None and document["result_is_current"] is None
    for context in ("read", "write", "queue_run"):
        assert validate_job(document, context=context) == []
    assert Job.from_document(document) == voice_job
    assert Job.from_document(document).to_document() == document


def test_a_photo_job_has_no_voice_block():
    document = photo_job().to_document()
    assert validate_job(document) == []
    document["voice"] = {"lines": []}
    assert ("schema.invalid", "/voice") in rules(document)


def test_terminal_documents_validate():
    job = start(photo_job(), now=NOW)
    for done in (succeed(job, RESULT, is_current=False, now=LATER),
                 fail(job, "adapter.timeout", "kokoro.synthesize: timed out", now=LATER),
                 cancel(job, now=LATER)):
        assert validate_job(done.to_document()) == []


@pytest.mark.parametrize("change, expected", [
    (lambda d: d.update(schema="studio.job/v2"), ("schema.unsupported", "/schema")),
    (lambda d: d.update(colour="red"), ("schema.unknown_field", "/colour")),
    (lambda d: d.update(derived={}), ("schema.unknown_field", "/derived")),
    (lambda d: d.update(id="job_123"), ("id.malformed", "/id")),
    (lambda d: d.update(id=RESULT), ("id.type_mismatch", "/id")),
    (lambda d: d.update(target_id=RESULT), ("id.type_mismatch", "/target_id")),
    (lambda d: d.update(kind="render"), ("schema.invalid", "/kind")),
    (lambda d: d.update(status="done"), ("schema.invalid", "/status")),
    (lambda d: d.update(input_signature="a" * 64), ("schema.invalid", "/input_signature")),
    (lambda d: d.update(result_version_id=RESULT), ("schema.invalid", "/result_version_id")),
    (lambda d: d.update(result_is_current=True), ("schema.invalid", "/result_is_current")),
    (lambda d: d.update(error={"code": "voice.x", "message": "no"}), ("schema.invalid", "/error")),
    (lambda d: d.update(status="succeeded"), ("schema.invalid", "/result_version_id")),
    (lambda d: d.update(status="failed"), ("schema.invalid", "/error")),
    (lambda d: d.pop("voice"), ("schema.invalid", "/voice")),
    (lambda d: d.pop("created_by"), ("schema.invalid", "")),
])
def test_schema_rules(voice_job, change, expected):
    document = copy.deepcopy(voice_job.to_document())
    change(document)
    assert expected in rules(document)


def test_the_voice_block_must_sign_to_the_jobs_signature(voice_job):
    document = copy.deepcopy(voice_job.to_document())
    document["voice"]["lead_ms"] += 100
    assert rules(document) == {("schema.invalid", "/input_signature")}
    document = copy.deepcopy(voice_job.to_document())
    document["voice"]["lines"][1]["text"] = "Nay."
    assert rules(document) == {("schema.invalid", "/voice/lines/1/signature")}


def test_the_voice_block_names_stock_voices_one_gap_per_later_line_and_each_line_once(voice_job):
    document = copy.deepcopy(voice_job.to_document())
    document["voice"]["lines"][0]["voice_id"] = "xx_cloned"
    assert ("voice.not_stock", "/voice/lines/0/voice_id") in rules(document)
    document = copy.deepcopy(voice_job.to_document())
    document["voice"]["model"] = "Another-TTS 2"
    assert ("voice.not_stock", "/voice/lines/0/voice_id") in rules(document)
    document = copy.deepcopy(voice_job.to_document())
    document["voice"]["gaps_ms"].append(300)
    assert ("schema.invalid", "/voice/gaps_ms") in rules(document)
    document = copy.deepcopy(voice_job.to_document())
    document["voice"]["lines"][1]["line_id"] = document["voice"]["lines"][0]["line_id"]
    assert ("ref.duplicate", "/voice/lines/1/line_id") in rules(document)


def _resigned(document):
    """The document with its ``input_signature`` recomputed from its voice block."""
    voice = document["voice"]
    document["input_signature"] = input_signature([line["signature"] for line in voice["lines"]],
                                                  voice["lead_ms"], voice["gaps_ms"])
    return document


@pytest.mark.parametrize("lead, gaps, expected", [
    (1_000_000_000, None, ("schema.invalid", "/voice/lead_ms")),  # input B
    (120_001, None, ("schema.invalid", "/voice/lead_ms")),
    (1900, [300, 120_001, 250, 700, 900], ("schema.invalid", "/voice/gaps_ms/1")),
    (120_000, [120_000] * 5, ("schema.invalid", "/voice")),  # 720000 ms before any take
], ids=["input-b", "lead", "gap", "lead-and-gaps"])
def test_the_voice_block_bounds_its_lead_and_gaps(voice_job, lead, gaps, expected):
    """Second review, finding 2: a lead and each gap are at most 120000 ms, and together
    at most a track's 600000 ms. The signatures are recomputed, so only the bound breaks."""
    document = copy.deepcopy(voice_job.to_document())
    document["voice"]["lead_ms"] = lead
    if gaps is not None:
        document["voice"]["gaps_ms"] = gaps
    assert rules(_resigned(document)) == {expected}


def test_the_largest_lead_and_gaps_are_valid(voice_job):
    document = copy.deepcopy(voice_job.to_document())
    document["voice"]["lead_ms"] = 120_000
    document["voice"]["gaps_ms"] = [120_000, 120_000, 120_000, 120_000, 0]
    assert rules(_resigned(document)) == set()


def test_a_malformed_document_never_raises():
    assert rules([]) == {("schema.invalid", "")}
    assert rules({"schema": None}) == {("schema.invalid", "/schema")}
    deep = {"schema": "studio.job/v1"}
    node = deep
    for _ in range(70):
        node["x"] = {}
        node = node["x"]
    assert rules(deep) == {("schema.invalid", "")}
    with pytest.raises(ValueError):
        validate_job({}, context="draft")


# State machine ---------------------------------------------------------------------------

MOVES = {
    "running": lambda job: start(job, now=LATER),
    "succeeded": lambda job: succeed(job, RESULT, is_current=True, now=LATER),
    "failed": lambda job: fail(job, "adapter.timeout", "timed out", now=LATER),
    "cancelled": lambda job: cancel(job, now=LATER),
}


def at(status: str) -> Job:
    job = photo_job()
    path = {"queued": [], "running": ["running"], "succeeded": ["running", "succeeded"],
            "failed": ["running", "failed"], "cancelled": ["cancelled"]}[status]
    for step in path:
        job = MOVES[step](job)
    assert job.status == status
    return job


def test_queued_to_running():
    job = start(at("queued"), now=LATER)
    assert (job.status, job.updated_at, job.created_at) == ("running", LATER, NOW)


def test_queued_to_cancelled():
    job = cancel(at("queued"), now=LATER)
    assert (job.status, job.result_version_id, job.error) == ("cancelled", None, None)


def test_running_to_succeeded_current():
    job = succeed(at("running"), RESULT, is_current=True, now=LATER)
    assert (job.status, job.result_version_id, job.result_is_current) == ("succeeded", RESULT, True)


def test_running_to_succeeded_stale():
    """VOICE-4: a job that finishes after its inputs changed is succeeded, its result
    kept, and not current."""
    job = succeed(at("running"), RESULT, is_current=False, now=LATER)
    assert (job.status, job.result_version_id, job.result_is_current) == ("succeeded", RESULT, False)


def test_running_to_failed():
    job = fail(at("running"), "adapter.command_failed", "kokoro.synthesize:\x00 exit 1\n", now=LATER)
    assert job.status == "failed"
    assert (job.error.code, job.error.message) == ("adapter.command_failed",
                                                   "kokoro.synthesize: exit 1")
    assert job.result_version_id is None


def test_running_to_cancelled():
    assert cancel(at("running"), now=LATER).status == "cancelled"


REFUSED = [(src, to) for src, to in itertools.product(STATUSES, MOVES)
           if to not in ALLOWED[src]]


@pytest.mark.parametrize("src, to", REFUSED, ids=[f"{s}-to-{t}" for s, t in REFUSED])
def test_every_other_move_is_refused(src, to):
    job = at(src)
    with pytest.raises(ContractError) as caught:
        MOVES[to](job)
    (violation,) = caught.value.violations
    assert (violation.rule, violation.status) == (TRANSITION, "conflict")
    assert job.status == src  # values never change in place


def test_terminal_states_have_no_moves():
    assert all(not ALLOWED[status] for status in ("succeeded", "failed", "cancelled"))
    assert set(ALLOWED) == set(STATUSES)


def test_a_result_must_be_a_version_id():
    with pytest.raises(ContractError):
        succeed(at("running"), "brd_01M79V9FC00000000000000008", is_current=True, now=LATER)


def test_in_flight_jobs_are_generating_facts():
    queued, running, done = at("queued"), at("running"), at("succeeded")
    facts = generating([queued, running, done])
    assert facts.generating == {(OTHER_BOARD, "photo")}
    assert generating([done]).generating == frozenset()
