"""The live clip sources of the service phase (story 851), through story 842's Wan
client and its fake pod only (``FakeWan`` behind ``FakeRunner``); nothing here reaches a
service. Each test copies one prepared store, so each has its own journal
(``<store root>/wan-journal.jsonl``) and starts as a new process would
(``forget_wan_process_state``). No test sleeps: the client's clock and sleep are fakes.

The fixture is the build fixture's story (B1 layered speech-to-video, B2 layered
image-to-video, B3 whole-frame image-to-video) with the doll loops recorded at 288x512,
a size the Wan client accepts (sides multiples of 32), and that size for both profiles.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
from dataclasses import replace

import pytest

from haynes_studio.adapters import wan
from haynes_studio.adapters.errors import (
    BUSY,
    COMMAND_FAILED,
    COMPETING_WORK,
    JOB_FAILED,
    JOURNAL_FAILED,
    NOT_FOUND,
    REQUEST_INVALID,
    RESPONSE_INVALID,
    TIMEOUT,
)
from haynes_studio.adapters.fakes import FailingRunner, FakeRunner, FakeWan
from haynes_studio.build import RunHeld, RunRecords, live_clip_sources
from haynes_studio.build.live import (
    E0_FILES,
    PlannedClip,
    WanClips,
    dry_run_report,
    dry_run_text,
    e0_clips,
    estimate,
    journal_path,
)
from haynes_studio.cache.plan import Toolchain
from haynes_studio.layered.s2v import read_provenance, record_stage
from haynes_studio.motion.winter_menu import complete_block
from haynes_studio.store import HASH_MISMATCH, LocalStore, blob_locator
from haynes_studio.wholeframe.clips import read_clip_set
from haynes_studio.wholeframe.source import last_frame_png
from tests.adapters.conftest import forget_wan_process_state
from tests.build_story import fixtures as f
from tests.layered import media
from tests.motion import fixtures as mf
from tests.support.policy import REPO_ROOT

W, H = 288, 512  # 9:16, sides multiples of 32
URL = "https://work.haynesnetwork.com/work_packages/851"
HOT = ((70.0, 0.0), (66.0, 0.0))
E0 = REPO_ROOT / "titles" / "the-winter-menu" / "video-e0"


@pytest.fixture(autouse=True)
def new_process():
    """``WanClipClient`` keeps the blocking job and the halt per process: each test
    starts, and ends, as a new process."""
    forget_wan_process_state()
    yield
    forget_wan_process_state()


class Clock:
    """The client's monotonic clock, wall clock and sleep, all fake."""

    def __init__(self):
        self.t = 100.0
        self.slept: list[float] = []

    def __call__(self):
        return self.t

    def wall(self):
        return 1_800_000_000.0 + self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


class Ids:
    def __init__(self, start: int = 0):
        self.n = start

    def __call__(self):
        self.n += 1
        return f"{self.n:032x}"


def toolchain(**changes) -> Toolchain:
    tools = Toolchain()
    out = replace(tools, s2v_profile={**f.S2V_PROFILE, "size": [W, H]}, s2v_negative_prompt=wan.NEGATIVE,
                  i2v_profile={**tools.i2v_profile, "size": [W, H]})
    return replace(out, **changes)


def _loop(world: f.World, version_id: str, asset: int, *, still_sha: str, tint: int) -> None:
    frames = [media.doll_frame(n, garble=n > 0, tint=tint, width=W, height=H) for n in range(f.LOOP_N)]
    clip, start = media.encode(frames, 24), media.png(media.doll_frame(0, tint=tint, width=W, height=H))
    clip_sha, start_sha = world.publish(clip, "video/mp4"), world.publish(start, "image/png")
    block = mf.loop_block(still_sha256=still_sha, frames=f.LOOP_N, width=W, height=H,
                          trim={"start": 0, "frames": f.LOOP_N})
    block["source"] = {**block["source"], "image_sha256": start_sha}
    block["keying"] = {**f.KEYING, "protect_boxes": [[2 * v for v in media.PROTECT]],
                       "decal_box": [2 * v for v in media.DECAL_BOX]}
    doc = mf.version(None, n=1, clip=clip_sha)
    doc["motion"] = complete_block(block, clip_sha)
    doc["capabilities"] = ["motion_clip"]
    doc["content"]["bytes"] = len(clip)
    world.docs.append(f._scoped(doc, version_id, asset))


def make_world(path) -> f.World:
    """The build fixture's world, its doll loops at 288x512."""
    path.mkdir(parents=True)
    world = f.World(path, LocalStore(path))
    for i, slot in enumerate("ab"):
        colour = ((200, 60, 60), (60, 200, 60))[i]
        still_sha = world.still(f.STILL[slot], 10 + i, media.cutout(colour))
        _loop(world, f.LOOP[slot], 20 + i, still_sha=still_sha, tint=f.TINT[slot])
        world.voice(f.VOICE[slot], 30 + i, f.STOCK[slot])
    plate_sha = world.still(f.PLATE, 40, media.set_plate(), kind="set")
    world.loop(f.SET_LOOP, 41, still_sha=plate_sha, clip=media.set_clip(f.SET_N),
               start=media.set_plate(), subject="set", frames=f.SET_N)
    world.photo(f.PHOTO, 50, f.photo_png())
    return world


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    """The world, voiced, after one dry run (so its drive tracks and mix are cached)."""
    world = make_world(tmp_path_factory.mktemp("live") / "store")
    document, library = f.voiced(world)
    sources = live_clip_sources(world.root, story=URL, dry_run=True)
    dry = f.build(world, document, library, phase="service", source=sources, tools=toolchain(),
                  dry_run=True)
    assert dry.run["status"] == "cancelled", dry.run["error"]
    return world, document, library


def copy_world(prepared, tmp_path) -> f.World:
    world = prepared[0]
    root = tmp_path / "store"
    shutil.copytree(world.root, root)
    return f.World(root, LocalStore(root), docs=list(world.docs))


class Phase:
    """One store's service phases on one fake pod, each a new process."""

    def __init__(self, world: f.World, document, library, pod: FakeWan, *, runner=None):
        self.world, self.document, self.library, self.pod = world, document, library, pod
        self.runner = runner or FakeRunner(pod)
        self.clock, self.ids = Clock(), Ids()

    def run(self, *, document=None, phase="service", dry_run=False, tools=None, new_process=True,
            before=None):
        if new_process:
            forget_wan_process_state()
        self.sources = live_clip_sources(
            self.world.root, story=URL, runner=self.runner, dry_run=dry_run,
            client_options={"clock": self.clock, "wall": self.clock.wall, "sleep": self.clock.sleep,
                            "new_job_id": self.ids})
        self.clips: WanClips | None = self.sources.s2v.clips if not dry_run else None
        if before is not None:
            before(self.sources)
        return f.build(self.world, document or self.document, self.library, phase=phase,
                       source=self.sources, tools=tools or toolchain(), dry_run=dry_run)


def payload_shapes(payloads) -> list[tuple[str, int, int]]:
    """Each Wan run the pod received: kind, seed and requested length (from the preset)."""
    out = []
    for payload in payloads:
        job = payload["job"]
        kind = "s2v" if "-s2v-" in job["preset"] else "i2v"
        out.append((kind, job["seed"], int(job["preset"].rsplit("-", 1)[1].rstrip("f"))))
    return out


def held_problem(run) -> dict:
    assert run["status"] == "held", run["error"]
    assert run["finished_at"] is None  # held is not terminal: a person reconciles it
    (problem,) = run["error"]["problems"]
    assert problem["status"] == "held" and problem["check"]
    assert problem["journal"].endswith("wan-journal.jsonl")
    return problem


# The service phase, the dry run and the second run ---------------------------------------------


@pytest.fixture(scope="module")
def served(prepared, tmp_path_factory):
    """A dry run, a service phase and a second service phase on one store and pod."""
    world = copy_world(prepared, tmp_path_factory.mktemp("served"))
    phase = Phase(world, prepared[1], prepared[2], FakeWan())
    dry = phase.run(dry_run=True)
    after_dry = (list(phase.pod.payloads), phase.pod.probes, journal_path(world.root).exists())
    first = phase.run()
    first_sources, first_clips = phase.sources, phase.clips
    payloads = list(phase.pod.payloads)
    second = phase.run()
    forget_wan_process_state()
    state = wan.FileJournal(journal_path(world.root)).read_state()
    return {"world": world, "dry": dry, "after_dry": after_dry, "first": first,
            "first_sources": first_sources, "first_clips": first_clips, "payloads": payloads,
            "second": second, "second_clips": phase.clips, "pod": phase.pod, "state": state}


def test_the_dry_run_lists_the_missing_clips_and_contacts_nothing(served):
    dry = served["dry"]
    assert dry.run["status"] == "cancelled" and dry.run["progress"]["stage"] == "dry_run"
    assert "nothing was asked of a service" in dry.run["transitions"][-1]["reason"]
    payloads, probes, journal_made = served["after_dry"]
    assert payloads == [] and probes == 0 and not journal_made  # no command, no journal
    shapes = [(c.kind, c.board_id, c.slot, c.index, c.frames, c.seed) for c in dry.planned]
    assert shapes == [("s2v", f.B1, "a", None, 13, 11), ("i2v", f.B3, None, 0, 121, 31)]
    assert all((c.width, c.height) == (W, H) for c in dry.planned)
    assert dry.planned[0].chunks == 1 and dry.planned[1].chunks is None


def test_the_service_phase_requests_exactly_the_missing_clips_once_each_in_order(served):
    first = served["first"]
    run = first.run
    assert run["status"] == "cancelled", run["error"]
    assert "service phase complete" in run["transitions"][-1]["reason"]
    # One Wan job per planned clip, in the dry run's order, each rendered once.
    planned = [(c.kind, c.seed, c.frames) for c in served["dry"].planned]
    assert payload_shapes(served["payloads"]) == planned
    assert served["first_clips"].calls == [("render", None), ("render", None)]
    assert len(served["first_sources"].s2v.calls) == 1 and len(served["first_sources"].i2v.calls) == 1
    assert [(c.kind, c.seed, c.frames) for c in first.planned] == planned
    # The journal is the store's, and every job in it is settled.
    state = served["state"]
    assert state.job is None and state.halt is None and len(state.named) == 2


def test_a_second_service_phase_requests_none_and_reads_no_journal(served):
    second = served["second"]
    assert second.run["status"] == "cancelled", second.run["error"]
    assert second.planned == () and second.source_calls == 0
    assert served["pod"].payloads == served["payloads"]  # nothing more ran
    assert served["second_clips"].client is None  # the client was never made


def test_the_clip_record_maps_onto_each_adapters_provenance_without_loss(served):
    world, pod, run = served["world"], served["pod"], served["first"].run
    stages = {s["board_id"]: s for s in run["stages"]}
    s2v = next(c for c in stages[f.B1]["clips"] if c["role"] == "s2v_clip")
    with world.store.open(world.store.stage_record(f.PRODUCTION, run["id"], record_stage(s2v["sha256"]))
                          .blobs["record"].locator) as handle:
        record = read_provenance(handle.read())
    clip, wan_record = record["clip"], record["clip"]["extra"]["wan"]
    ledger = pod.jobs[wan_record["job_id"]]
    assert record["source"] == "studio.build.wan-s2v/1"
    assert clip["engine"] == wan_record["engine"] == "wan-api/s2v-14b-lightning"
    assert clip["engine_job_id"] == wan_record["job_id"] == s2v["engine_job_id"]
    assert clip["files_sha256"] == wan_record["model_files_sha256"] == s2v["files_sha256"]
    assert clip["sha256"] == wan_record["clip_sha256"] and clip["bytes"] == wan_record["clip_bytes"]
    assert clip["frames_requested"] == wan_record["frames_requested"] == 13
    assert clip["frames_delivered"] == wan_record["frames_delivered"]
    assert record["seed"] == wan_record["seed"] == 11
    assert record["start_image"]["sha256"] == wan_record["inputs"]["image"]["sha256"]
    assert record["drive_track"]["sha256"] == wan_record["inputs"]["audio"]["sha256"]
    assert wan_record["graph_sha256"] == ledger["graph_sha256"] and wan_record["story"] == URL
    assert wan_record["negative"] == wan.NEGATIVE and wan_record["recovered"] is False
    # The whole-frame chain: each clip's Wan record is kept on its clip-set entry.
    b3 = next(c for c in stages[f.B3]["clips"] if c["role"] == "whole_frame_clip")
    with world.store.open(blob_locator(f.PRODUCTION, b3["sha256"], "application/json")) as handle:
        clip_set = read_clip_set(handle.read(), b3["sha256"])
    assert clip_set["source"] == "studio.build.wan-i2v/1"
    (entry,) = clip_set["clips"]
    i2v_record = entry["extra"]["wan"]
    assert entry["engine"] == i2v_record["engine"] == "wan-api/ti2v-5b"
    assert entry["engine_job_id"] == i2v_record["job_id"] == b3["clips"][0]["engine_job_id"]
    assert entry["sha256"] == i2v_record["clip_sha256"] and entry["seed"] == i2v_record["seed"] == 31
    assert entry["files_sha256"] == i2v_record["model_files_sha256"]
    assert entry["start_image"]["sha256"] == i2v_record["inputs"]["image"]["sha256"]
    assert entry["frames_requested"] == i2v_record["frames_requested"] == 121


# Refusals: each stops the phase held, and nothing further is submitted ---------------------------


REFUSALS = {
    # name: (pod behaviour, code, runs the pod received)
    "api_holding": (dict(accepting=False), BUSY, 0),
    "api_busy": (dict(active_job="f" * 32), BUSY, 0),
    "unknown_work_queued": (dict(queue_running=["p-foreign"]), BUSY, 0),
    "gpus_never_cool": (dict(gpu_trace=[HOT]), BUSY, 0),
    "admission_readback_holds": (dict(hold_at_admission=True), BUSY, 1),
    "compute_lease_busy": (dict(lease_held=True), BUSY, 1),
    "gpus_busy_at_generate": (dict(busy_at_generate=True), JOB_FAILED, 1),
    "job_failed": (dict(outcome="error"), JOB_FAILED, 1),
    "answer_lost": (dict(lose="timeout"), TIMEOUT, 1),
    "clip_cut_in_transfer": (dict(mangle_fetch=True), RESPONSE_INVALID, 1),
}


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_every_refusal_stops_the_phase_held_and_submits_nothing_further(prepared, tmp_path, name):
    behaviour, code, runs = REFUSALS[name]
    phase = Phase(copy_world(prepared, tmp_path), prepared[1], prepared[2], FakeWan(**behaviour))
    built = phase.run()
    run = built.run
    problem = held_problem(run)
    assert run["error"]["code"] == problem["rule"] == code, run["error"]
    assert run["error"]["board_id"] == f.B1 and run["error"]["stage"] == "s2v_clip"
    assert run["error"]["message"].startswith("held") and "Nothing further was submitted" in run["error"]["message"]
    assert len(phase.pod.payloads) == runs
    assert phase.clips.calls == [("render", None)]  # one render; no retry, no second clip
    assert phase.sources.i2v.calls == []  # the next clip was never asked for
    if runs:
        assert problem["job_id"] == f"{1:032x}"
    if name == "gpus_never_cool":  # the client's own wait (reading only), not the build's
        assert sum(phase.clock.slept) > wan.COOL_MAX_S
    # The stop holds: a later request asks nothing of the client.
    with pytest.raises(RunHeld) as caught:
        phase.sources.s2v.generate(phase.sources.s2v.calls[0])
    assert caught.value is phase.clips.stopped
    assert phase.clips.calls == [("render", None)] and len(phase.pod.payloads) == runs
    assert RunRecords(phase.world.store, f.PRODUCTION).latest(run["id"])["status"] == "held"


def test_a_runner_that_cannot_reach_the_pod_stops_the_phase_held(prepared, tmp_path):
    phase = Phase(copy_world(prepared, tmp_path), prepared[1], prepared[2], FakeWan(),
                  runner=FailingRunner(returncode=1, stderr=b"error: connection refused\n"))
    problem = held_problem(phase.run().run)
    assert problem["rule"] == COMMAND_FAILED and phase.clips.calls == [("render", None)]


def test_an_unreadable_journal_stops_the_phase_held_before_any_command(prepared, tmp_path):
    world = copy_world(prepared, tmp_path)
    path = journal_path(world.root)
    path.write_bytes(b"not a journal\n")
    path.with_name(path.name + ".lock").write_bytes(b"")
    phase = Phase(world, prepared[1], prepared[2], FakeWan())
    problem = held_problem(phase.run().run)
    assert problem["rule"] == JOURNAL_FAILED and phase.pod.probes == 0 and phase.pod.payloads == []
    assert path.read_bytes() == b"not a journal\n"  # never rewritten


def test_a_journal_another_holder_has_stops_the_phase_held_before_any_command(prepared, tmp_path):
    world = copy_world(prepared, tmp_path)
    other = wan.FileJournal(journal_path(world.root))
    other.hold()
    try:
        phase = Phase(world, prepared[1], prepared[2], FakeWan())
        problem = held_problem(phase.run().run)
    finally:
        other.release()
    assert problem["rule"] == BUSY and phase.pod.probes == 0 and phase.pod.payloads == []


def test_competing_work_keeps_the_checked_clip_then_holds_and_the_halt_holds_the_next_run(prepared, tmp_path):
    phase = Phase(copy_world(prepared, tmp_path), prepared[1], prepared[2],
                  FakeWan(foreign_during_job=["p-foreign"]))
    first = phase.run()
    problem = held_problem(first.run)
    assert problem["rule"] == COMPETING_WORK and problem["halt"]["unexpected_work_seen"] == ["p-foreign"]
    kept = problem["clip_kept"]
    assert len(phase.pod.payloads) == 1 and phase.sources.i2v.calls == []
    with phase.world.store.open(blob_locator(f.PRODUCTION, kept["sha256"], "video/mp4")) as handle:
        assert hashlib.sha256(handle.read()).hexdigest() == kept["sha256"]  # cached
    # A new process on the same journal: the halt stops it at once; nothing is submitted.
    phase.pod.foreign_during_job = []
    again = phase.run()
    problem = held_problem(again.run)
    assert problem["rule"] == COMPETING_WORK and again.run["error"]["board_id"] == f.B3
    assert len(phase.pod.payloads) == 1  # the kept clip was not rendered again
    assert phase.clips.calls == [("render", None)]


# A lost answer: recover, never a second render ------------------------------------------------------


def test_a_lost_answer_is_recovered_by_the_next_phase_never_rendered_again(prepared, tmp_path):
    phase = Phase(copy_world(prepared, tmp_path), prepared[1], prepared[2],
                  FakeWan(lose="timeout", lost_state="succeeded"))
    lost = phase.run()
    problem = held_problem(lost.run)
    job = problem["job_id"]
    assert problem["rule"] == TIMEOUT and problem["in_flight"] == {"job_id": job, "state": "in_flight"}
    phase.pod.lose = None
    recovered = phase.run()
    assert recovered.run["status"] == "cancelled", recovered.run["error"]
    assert phase.clips.calls == [("recover", job), ("render", None)]  # then the next clip
    assert [shape[0] for shape in payload_shapes(phase.pod.payloads)] == ["s2v", "i2v"]  # one s2v job ever
    b1 = next(s for s in recovered.run["stages"] if s["board_id"] == f.B1)
    s2v = next(c for c in b1["clips"] if c["role"] == "s2v_clip")
    assert s2v["engine_job_id"] == job and s2v["made"]
    forget_wan_process_state()
    assert wan.FileJournal(journal_path(phase.world.root)).read_state().job is None


def test_a_lost_fetch_is_recovered_by_the_next_phase_never_rendered_again(prepared, tmp_path):
    phase = Phase(copy_world(prepared, tmp_path), prepared[1], prepared[2], FakeWan(mangle_fetch=True))
    problem = held_problem(phase.run().run)
    assert problem["in_flight"]["state"] == "uncollected"
    phase.pod.mangle_fetch = False
    recovered = phase.run()
    assert recovered.run["status"] == "cancelled", recovered.run["error"]
    assert phase.clips.calls == [("recover", problem["job_id"]), ("render", None)]
    assert len(phase.pod.payloads) == 2


@pytest.mark.parametrize("lost_state, code", [("running", BUSY), (None, NOT_FOUND), ("failed", JOB_FAILED)])
def test_a_lost_job_that_has_not_succeeded_stops_the_next_phase_held_without_a_render(
        prepared, tmp_path, lost_state, code):
    phase = Phase(copy_world(prepared, tmp_path), prepared[1], prepared[2],
                  FakeWan(lose="timeout", lost_state=lost_state))
    job = held_problem(phase.run().run)["job_id"]
    phase.pod.lose = None
    problem = held_problem(phase.run().run)
    assert problem["rule"] == code and problem["job_id"] == job
    assert phase.clips.calls == [("recover", job)] and len(phase.pod.payloads) == 1


def test_a_journal_job_made_for_another_request_stops_the_phase_held(prepared, tmp_path):
    phase = Phase(copy_world(prepared, tmp_path), prepared[1], prepared[2],
                  FakeWan(lose="timeout", lost_state="succeeded"))
    job = held_problem(phase.run().run)["job_id"]
    phase.pod.lose = None
    reseeded = copy.deepcopy(phase.document)
    f.board_of(reseeded, f.B1)["seeds"]["s2v:a"] = 12  # another request than the lost job's
    problem = held_problem(phase.run(document=reseeded).run)
    assert problem["rule"] == "build.wan_unsettled" and problem["job_id"] == job
    assert phase.clips.calls == [] and len(phase.pod.payloads) == 1  # neither recover nor render


# Checked before any clip ----------------------------------------------------------------------------


def test_a_request_the_client_would_refuse_fails_the_run_before_any_clip(prepared, tmp_path):
    phase = Phase(copy_world(prepared, tmp_path), prepared[1], prepared[2], FakeWan())
    run = phase.run(tools=toolchain(s2v_negative_prompt="")).run  # the Wan graph needs one
    assert run["status"] == "failed" and run["error"]["code"] == REQUEST_INVALID
    assert run["error"]["board_id"] == f.B1
    assert run["error"]["message"].endswith("(found before any clip was requested)")
    assert phase.pod.probes == 0 and phase.clips.client is None
    assert not journal_path(phase.world.root).exists()


def test_a_profile_the_client_does_not_make_fails_the_run_before_any_clip(prepared, tmp_path):
    phase = Phase(copy_world(prepared, tmp_path), prepared[1], prepared[2], FakeWan())
    tools = toolchain()
    run = phase.run(tools=replace(tools, i2v_profile={**tools.i2v_profile, "model": "another"})).run
    assert run["status"] == "failed" and run["error"]["code"] == "build.live_unsupported"
    assert run["error"]["board_id"] == f.B3 and "model='another'" in run["error"]["message"]
    assert phase.pod.probes == 0 and phase.clips.client is None


# The journal ------------------------------------------------------------------------------------------


def test_every_run_of_a_store_uses_its_one_journal(tmp_path):
    first = live_clip_sources(tmp_path, story=URL, runner=FakeRunner(FakeWan()))
    second = live_clip_sources(str(tmp_path), story=URL, runner=FakeRunner(FakeWan()))
    assert first.s2v.clips.journal_path == second.i2v.clips.journal_path == tmp_path / "wan-journal.jsonl"
    assert first.s2v.clips is first.i2v.clips  # one client per phase for both kinds
    with pytest.raises(TypeError):
        live_clip_sources(tmp_path, story=URL, runner=FakeRunner(FakeWan()),
                          client_options={"journal": wan.MemoryJournal()})
    assert not (tmp_path / "wan-journal.jsonl").exists()  # making the sources reads nothing


# The E0 estimate -----------------------------------------------------------------------------------


def test_the_estimate_comes_from_the_e0_records_of_the_same_shape():
    records = e0_clips(E0)
    assert {r.source.split(":")[0] for r in records} == set(E0_FILES)
    assert not any(r.kind == "s2v" and r.chunks is None for r in records)  # the 20-step job is out

    def clip(kind, frames, chunks=None):
        return PlannedClip(kind, f.B1, 1, "a" if kind == "s2v" else None, None if kind == "s2v" else 0,
                           frames, 5, 576, 1024, chunks, "sha256:x")
    one, three = estimate(clip("s2v", 65, 1), records), estimate(clip("s2v", 231, 3), records)
    assert one.records == 4 and one.render_s == (142.5, 203.1)
    assert three.records == 4 and three.render_s == (269.5, 716.3) and three.wall_s_max == 842.3
    full, short = estimate(clip("i2v", 121), records), estimate(clip("i2v", 65), records)
    assert full.render_s == short.render_s == (116.5, 152.1) and "upper bound" in short.basis
    none = estimate(PlannedClip("i2v", f.B3, 3, None, 0, 13, 31, W, H, None, "k"), records)
    assert none.render_s is None and "no E0 job" in none.basis
    report = dry_run_report([clip("s2v", 65, 1), clip("i2v", 121)], records)
    assert report["total"]["render_s"] == [259.0, 355.2] and report["total"]["jobs"] == 2
    assert "GPU 142.5-203.1 s" in dry_run_text(report)


# The command line ---------------------------------------------------------------------------------


def cli(*argv, wan_runner=None):
    from haynes_studio.cli import Clients, main
    out, err = io.StringIO(), io.StringIO()
    clients = Clients(speech=lambda: pytest.fail("no speech"), transcriber=lambda: f.transcriber()[0],
                      wan_runner=wan_runner or (lambda: pytest.fail("no Wan runner")))
    code = main(list(argv), stdout=out, stderr=err, clients=clients)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture(scope="module")
def files(prepared, tmp_path_factory):
    folder = tmp_path_factory.mktemp("live-cli")
    _, document, library = prepared
    tools = toolchain()
    (folder / "story.json").write_text(json.dumps(document))
    (folder / "library.json").write_text(json.dumps(library.documents()))
    (folder / "toolchain.json").write_text(json.dumps(
        {"s2v_profile": dict(tools.s2v_profile), "i2v_profile": dict(tools.i2v_profile),
         "s2v_negative_prompt": tools.s2v_negative_prompt}))
    return folder


def cli_args(world, files, *extra):
    return ["build", "--store", str(world.root), "--story", str(files / "story.json"),
            "--library", str(files / "library.json"), "--operator-iss",
            "https://authentik.example.invalid/application/o/haynes-studio/", "--operator-sub",
            "example-subject-build", "--toolchain", str(files / "toolchain.json"), "--register",
            str(f.REGISTER), *extra]


def test_the_cli_dry_run_prints_each_clip_and_asks_nothing(prepared, files, tmp_path):
    world = copy_world(prepared, tmp_path)
    code, out, err = cli(*cli_args(world, files, "--phase", "service", "--dry-run", "--wan-story", URL))
    assert code == 0, err
    assert "dry run: 2 clip job(s) would be requested" in out
    assert f"s2v board 1 {f.B1} slot a: 13 frames at 288x512, 1 chunk(s), seed 11" in out
    assert f"i2v board 3 {f.B3} clip 0: 121 frames at 288x512, seed 31" in out
    assert not journal_path(world.root).exists()
    code, out, err = cli(*cli_args(world, files, "--phase", "service", "--dry-run", "--wan-story", URL,
                                   "--json"))
    assert code == 0 and [c["kind"] for c in json.loads(out)["dry_run"]["clips"]] == ["s2v", "i2v"]


def test_the_cli_needs_a_wan_story_and_a_dry_run_only_of_the_service_phase(prepared, files, tmp_path):
    world = copy_world(prepared, tmp_path)
    for extra in (("--phase", "service"), (), ("--phase", "service", "--wan-story", "428")):
        code, _, err = cli(*cli_args(world, files, *extra))
        assert code == 2 and "--wan-story" in err
    code, _, err = cli(*cli_args(world, files, "--dry-run", "--wan-story", URL))
    assert code == 2 and "--dry-run" in err
    assert not journal_path(world.root).exists()


def test_the_cli_service_phase_on_the_fake_pod_and_a_held_run_exits_1(prepared, files, tmp_path):
    world = copy_world(prepared, tmp_path)
    pod = FakeWan(accepting=False)
    code, out, err = cli(*cli_args(world, files, "--phase", "service", "--wan-story", URL),
                         wan_runner=lambda: FakeRunner(pod))
    assert code == 1 and "(service phase): held" in out
    assert "rule adapter.busy" in err and f"at board {f.B1}" in err and "held" in err
    forget_wan_process_state()
    pod.health["accepting_jobs"] = True
    code, out, err = cli(*cli_args(world, files, "--phase", "service", "--wan-story", URL),
                         wan_runner=lambda: FakeRunner(pod))
    assert code == 0, err
    assert "(service phase): cancelled" in out and len(pod.payloads) == 2


def test_the_offline_phase_needs_no_client_and_reads_no_journal(prepared, files, tmp_path, monkeypatch):
    import haynes_studio.build as studio_build
    world = copy_world(prepared, tmp_path)
    monkeypatch.setattr(studio_build, "live_clip_sources",
                        lambda *a, **k: pytest.fail("the offline phase asks no hook"))
    monkeypatch.setattr(wan.WanClipClient, "__init__", lambda *a, **k: pytest.fail("no client offline"))
    code, out, err = cli(*cli_args(world, files, "--offline"))  # its Wan runner fails if asked
    assert code == 1 and "rule build.offline_missing" in err and f"at board {f.B1}" in err
    assert not journal_path(world.root).exists()


# Chains of more than one clip ------------------------------------------------------------------


class Staged:
    """The fake pod's runner, with ``hooks[n]`` applied to the pod once it has received
    ``n`` Wan runs (``0``: before the first command; ``1``: right after the first run)."""

    def __init__(self, pod: FakeWan, hooks):
        self.pod, self.hooks, self.runner = pod, dict(hooks), FakeRunner(pod)

    def run(self, command):
        hook = self.hooks.pop(len(self.pod.payloads), None)
        if hook is not None:
            hook(self.pod)
        return self.runner.run(command)


CHAIN = toolchain(i2v_clip_frames=9)  # B3's 12 source frames: two clips of 9


def chain_world(prepared, tmp_path, pod, hooks=()):
    world = copy_world(prepared, tmp_path)
    phase = Phase(world, prepared[1], prepared[2], pod, runner=Staged(pod, hooks))
    return phase


def b3_clips(world, run):
    b3 = next(s for s in run["stages"] if s["board_id"] == f.B3)
    entry = next(c for c in b3["clips"] if c["role"] == "whole_frame_clip")
    with world.store.open(blob_locator(f.PRODUCTION, entry["sha256"], "application/json")) as handle:
        return read_clip_set(handle.read(), entry["sha256"])["clips"]


def test_a_chain_renders_each_clip_once_in_order_each_on_the_last_frame_before(prepared, tmp_path):
    phase = chain_world(prepared, tmp_path, FakeWan())
    built = phase.run(tools=CHAIN)
    assert built.run["status"] == "cancelled", built.run["error"]
    assert [(c.kind, c.index, c.frames, c.seed) for c in built.planned] == [
        ("s2v", None, 13, 11), ("i2v", 0, 9, 31), ("i2v", 1, 9, 32)]
    assert payload_shapes(phase.pod.payloads) == [("s2v", 11, 13), ("i2v", 31, 9), ("i2v", 32, 9)]
    clips = b3_clips(phase.world, built.run)
    first, second = clips[0]["extra"]["wan"], clips[1]["extra"]["wan"]
    assert first["inputs"]["image"]["sha256"] == hashlib.sha256(f.photo_png()).hexdigest()
    with phase.world.store.open(blob_locator(f.PRODUCTION, clips[0]["sha256"], "video/mp4")) as handle:
        last = last_frame_png(handle.read())
    assert second["inputs"]["image"]["sha256"] == hashlib.sha256(last).hexdigest()
    assert clips[1]["start_image"]["role"] == "previous_last_frame"


def _refuse(pod):
    pod.health["accepting_jobs"] = False


def test_a_refusal_inside_a_chain_holds_naming_the_clips_collected_before_it(prepared, tmp_path):
    phase = chain_world(prepared, tmp_path, FakeWan(), {2: _refuse})  # after B1 and clip 0
    problem = held_problem(phase.run(tools=CHAIN).run)
    assert problem["rule"] == BUSY and phase.clips.stopped is not None
    (collected,) = problem["collected_before_stop"]
    assert collected["index"] == 0 and collected["job_id"] == f"{2:032x}"
    assert len(phase.pod.payloads) == 2 and phase.clips.calls == [("render", None)] * 3


def test_a_held_run_keeps_the_board_stages_it_completed_before_the_stop(prepared, tmp_path):
    """Story 860: refused at B3's clip 1, after B1's clip and B3's clip 0. B1 and B2 were
    completed (B2's segment, like B1's, is left to the offline phase); B3 was not."""
    phase = chain_world(prepared, tmp_path, FakeWan(), {2: _refuse})
    run = phase.run(tools=CHAIN).run
    assert run["status"] == "held" and run["finished_at"] is None
    assert [s["board_id"] for s in run["stages"]] == [f.B1, f.B2]
    b1 = next(s for s in run["stages"] if s["board_id"] == f.B1)
    s2v = next(c for c in b1["clips"] if c["role"] == "s2v_clip")
    assert s2v["made"] and s2v["render_s"] is not None and s2v["engine_job_id"] == f"{1:032x}"


def test_foreign_work_on_a_chains_earlier_clip_holds_and_submits_nothing_more(prepared, tmp_path):
    def foreign(pod):
        pod.foreign_during_job = ["p-foreign"]

    def quiet(pod):
        pod.foreign_during_job = []
    phase = chain_world(prepared, tmp_path, FakeWan(), {1: foreign, 2: quiet})
    problem = held_problem(phase.run(tools=CHAIN).run)
    assert problem["rule"] == COMPETING_WORK and problem["collected_before_stop"] == []
    assert problem["clip_kept"]["handed_to_adapter"] is False  # a chain is committed whole
    assert len(phase.pod.payloads) == 2  # B1, then clip 0; clip 1 never sent
    assert phase.clips.calls == [("render", None)] * 2


def test_a_lost_answer_on_a_chains_later_clip_is_recovered_on_the_kept_clips_before_it(prepared, tmp_path):
    def lose(pod):
        pod.lose, pod.lost_state = "timeout", "succeeded"
    phase = chain_world(prepared, tmp_path, FakeWan(), {2: lose})
    job = held_problem(phase.run(tools=CHAIN).run)["job_id"]
    phase.pod.lose = None
    again = phase.run(tools=CHAIN)  # clip 0 is kept, so the next request is clip 1's own
    assert again.run["status"] == "cancelled", again.run["error"]
    assert phase.clips.calls == [("recover", job)] and len(phase.pod.payloads) == 3
    assert [c["engine_job_id"] for c in b3_clips(phase.world, again.run)] == [f"{2:032x}", job]


# Kept chain clips: a clip collected is never asked for again -------------------------------------


class Crash(BaseException):
    """The process dies: nothing in the build or the client catches it."""


def kept_artifacts(run, board=f.B3):
    """The kept chain clips a run's board stage lists: (name, made)."""
    stage = next(s for s in run["stages"] if s["board_id"] == board)
    return [(a["name"], a["made"]) for a in stage["artifacts"] if a["kind"] == "wan_chain_clip"]


def test_a_chain_refused_at_clip_1_keeps_clip_0_and_the_next_phase_submits_only_clip_1(prepared, tmp_path):
    phase = chain_world(prepared, tmp_path, FakeWan(), {2: _refuse})  # after B1 and clip 0
    problem = held_problem(phase.run(tools=CHAIN).run)
    assert problem["rule"] == BUSY and problem["in_flight"] is None  # the journal settled it
    (collected,) = problem["collected_before_stop"]
    assert collected["index"] == 0 and collected["kept"].startswith("sha256:") and not collected["reused"]
    phase.pod.health["accepting_jobs"] = True
    again = phase.run(tools=CHAIN)  # a new run: no reconciliation, nothing blocks it
    assert again.run["status"] == "cancelled", again.run["error"]
    assert phase.clips.calls == [("render", None)]  # clip 1 only
    assert payload_shapes(phase.pod.payloads) == [("s2v", 11, 13), ("i2v", 31, 9), ("i2v", 32, 9)]
    clips = b3_clips(phase.world, again.run)
    assert clips[0]["engine_job_id"] == collected["job_id"] == f"{2:032x}"
    assert clips[0]["extra"]["kept"]["key"] == collected["kept"]
    assert kept_artifacts(again.run) == [("wan_chain_clip/0", False), ("wan_chain_clip/1", True)]
    b3 = next(s for s in again.run["stages"] if s["board_id"] == f.B3)
    entry = next(c for c in b3["clips"] if c["role"] == "whole_frame_clip")
    assert [c["kept"]["made"] for c in entry["clips"]] == [False, True]


def test_a_crash_after_a_chains_first_clip_keeps_it_for_the_next_process(prepared, tmp_path):
    phase = chain_world(prepared, tmp_path, FakeWan())

    def dies_before_clip_1(sources):
        clips, make = sources.i2v.clips, sources.i2v.clips.make

        def make_or_die(request, **options):
            if len(clips.calls) == 2:  # B1 and clip 0 collected; clip 1 never journalled
                raise Crash()
            return make(request, **options)
        clips.make = make_or_die
    with pytest.raises(Crash):
        phase.run(tools=CHAIN, before=dies_before_clip_1)
    assert payload_shapes(phase.pod.payloads) == [("s2v", 11, 13), ("i2v", 31, 9)]
    forget_wan_process_state()
    assert wan.FileJournal(journal_path(phase.world.root)).read_state().job is None
    again = phase.run(tools=CHAIN)  # a new process: a new client and sources, the same store
    assert again.run["status"] == "cancelled", again.run["error"]
    assert phase.clips.calls == [("render", None)]
    assert payload_shapes(phase.pod.payloads) == [("s2v", 11, 13), ("i2v", 31, 9), ("i2v", 32, 9)]
    assert kept_artifacts(again.run) == [("wan_chain_clip/0", False), ("wan_chain_clip/1", True)]


def test_a_kept_clip_that_is_not_its_bytes_is_refused_and_nothing_is_rendered_in_its_place(
        prepared, tmp_path):
    phase = chain_world(prepared, tmp_path, FakeWan(), {2: _refuse})
    (kept,) = held_problem(phase.run(tools=CHAIN).run)["collected_before_stop"]
    path = phase.world.root / blob_locator(f.PRODUCTION, kept["sha256"], "video/mp4")
    damaged = bytearray(path.read_bytes())
    damaged[len(damaged) // 2] ^= 0xFF  # the same size, other bytes
    path.chmod(0o644)
    path.write_bytes(bytes(damaged))
    phase.pod.health["accepting_jobs"] = True
    run = phase.run(tools=CHAIN).run
    assert run["status"] == "failed" and run["error"]["code"] == HASH_MISMATCH, run["error"]
    assert run["error"]["board_id"] == f.B3 and run["error"]["stage"] == "whole_frame_clip"
    assert len(phase.pod.payloads) == 2 and phase.clips.calls == [] and phase.clips.client is None


THREE = toolchain(i2v_clip_frames=5)  # B3's 12 source frames: three clips of 5


def test_a_chain_of_three_stopped_at_clip_2_reuses_clips_0_and_1(prepared, tmp_path):
    phase = chain_world(prepared, tmp_path, FakeWan(), {3: _refuse})  # after B1, clips 0 and 1
    problem = held_problem(phase.run(tools=THREE).run)
    assert [c["index"] for c in problem["collected_before_stop"]] == [0, 1]
    phase.pod.health["accepting_jobs"] = True
    again = phase.run(tools=THREE)
    assert again.run["status"] == "cancelled", again.run["error"]
    assert phase.clips.calls == [("render", None)]
    assert payload_shapes(phase.pod.payloads) == [
        ("s2v", 11, 13), ("i2v", 31, 5), ("i2v", 32, 5), ("i2v", 33, 5)]
    assert kept_artifacts(again.run) == [
        ("wan_chain_clip/0", False), ("wan_chain_clip/1", False), ("wan_chain_clip/2", True)]


def test_a_single_clip_chain_and_a_speech_clip_are_one_job_each_and_the_chain_clip_is_kept(served):
    assert payload_shapes(served["payloads"]) == [("s2v", 11, 13), ("i2v", 31, 121)]
    assert served["first_clips"].calls == [("render", None), ("render", None)]
    first, second = served["first"].run, served["second"].run
    assert kept_artifacts(first) == [("wan_chain_clip/0", True)]
    assert kept_artifacts(second) == [("wan_chain_clip/0", False)]  # the chain itself was a hit
    assert kept_artifacts(first, f.B1) == []  # speech-to-video keeps nothing more than before
