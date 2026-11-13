"""The Wan clip client's guards (story 842), each proven through the fake Wan pod.

``FakeWan`` runs the pinned in-pod snippets themselves (wan_probe.py, wan_upload.py,
wan_run.py, wan_clip_fetch.py, wan_ledger_read.py) against a port of the installed
``api.generate()``, so the snippet guards (admission readback, read-only retries, the
foreign-work observer) are exercised here, not only the client's. Every test names the
guard it proves; docs/reference/legacy-adapters.md has the table (PoC line, code, test).
No test sleeps: the client's clock and sleep are fakes, and so is the pod's.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os

import pytest

from haynes_studio.adapters import pinned, wan
from haynes_studio.adapters.errors import (
    BUSY,
    COMMAND_FAILED,
    COMPETING_WORK,
    JOB_FAILED,
    JOURNAL_FAILED,
    NOT_FOUND,
    PIN_MISMATCH,
    REQUEST_INVALID,
    RESPONSE_INVALID,
    TIMEOUT,
    AdapterError,
    PinMismatch,
    RequestInvalid,
    WanError,
)
from haynes_studio.adapters.fakes import FakeRunner, FakeWan, synthetic_png, synthetic_wav
from haynes_studio.adapters.runner import Completed
from haynes_studio.adapters.wan import (
    IN_FLIGHT,
    UNCOLLECTED,
    FileJournal,
    ImageToVideo,
    InFlightJob,
    MemoryJournal,
    SpeechToVideo,
    WanClipClient,
    s2v_frames_needed,
    s2v_length,
)
from tests.adapters.conftest import forget_wan_process_state

STORY = "https://work.haynesnetwork.com/work_packages/428"
COOL = ((45.0, 0.0), (44.0, 0.0))
HOT = ((70.0, 0.0), (66.0, 0.0))
# The steps of a good render: probe, upload(s), probe again right before the run, run, fetch.
I2V_STEPS = ["wan_probe.py", "wan_upload.py", "wan_probe.py", "wan_run.py", "wan_clip_fetch.py"]


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
    def __init__(self, start=0):
        self.n = start

    def __call__(self):
        self.n += 1
        return f"{self.n:032x}"


def client_for(runner, clock=None, journal=None, ids=None):
    clock = clock or Clock()
    return WanClipClient(runner, journal=journal if journal is not None else MemoryJournal(wall=clock.wall),
                         clock=clock, wall=clock.wall, sleep=clock.sleep, new_job_id=ids or Ids())


def i2v(seed=7, **changes):
    fields = dict(image_png=synthetic_png(seed=1), prompt="a doll waves", seed=seed, story=STORY,
                  width=64, height=128, length=9)
    fields.update(changes)
    return ImageToVideo(**fields)


def s2v(board_frames=12, rate=24000, **changes):
    drive_frames = min(max(board_frames, 1), 240)  # a valid board's own drive; a stand-in otherwise
    fields = dict(image_png=synthetic_png(seed=2), drive_wav=synthetic_wav(drive_frames * rate // 24, rate=rate),
                  board_frames=board_frames, prompt="a doll talks", seed=501, story=STORY,
                  width=64, height=128)
    fields.update(changes)
    return SpeechToVideo(**fields)


class ProbeEdit:
    """A runner whose probe answers are edited by ``edit(answer)`` (the pod is untouched)."""

    def __init__(self, runner, edit):
        self.runner, self.edit = runner, edit

    def run(self, command):
        result = self.runner.run(command)
        if snippets_of(command) == "wan_probe.py":
            answer = json.loads(result.stdout)
            self.edit(answer)
            return Completed(0, json.dumps(answer).encode(), result.stderr)
        return result


def restart():
    """A new process: nothing in memory, only what the journal holds."""
    forget_wan_process_state()


def reopen(journal):
    """The journal as a new process opens it: the same file, or (in memory) the same lines."""
    return FileJournal(journal.path) if isinstance(journal, FileJournal) else journal


def journal_bytes(journal):
    return journal.path.read_bytes() if isinstance(journal, FileJournal) else journal.data


def events(journal):
    """Each journal line as "<event> <state, outcome or job>"."""
    lines = [json.loads(line) for line in journal_bytes(journal).decode().splitlines()]
    return [" ".join([e["event"], e.get("state") or e.get("outcome") or e["job_id"]]) for e in lines]


@pytest.fixture(params=["memory", "file"])
def journal(request, tmp_path):
    return MemoryJournal() if request.param == "memory" else FileJournal(tmp_path / "wan-journal.jsonl")


def snippets_of(command):
    """The pinned snippet a command runs."""
    names = {pin.sha256: name for name, pin in pinned.PINS.items()}
    return names[hashlib.sha256(command.argv[command.argv.index("--") + 3].encode()).hexdigest()]


def snippets(runner):
    """The pinned snippet each command ran, in order."""
    return [snippets_of(c) for c in runner.calls]


def runs(runner):
    return snippets(runner).count("wan_run.py")


def refused(pod, client, request, code):
    with pytest.raises(WanError) as caught:
        client.render(request)
    assert caught.value.code == code, caught.value
    return caught.value


def nothing_submitted(pod):
    assert pod.submitted == []
    assert not any(path == "/prompt" for path, _ in pod.engine_calls)


# A good render ------------------------------------------------------------------------------

def test_i2v_runs_the_poc_steps_in_order_and_returns_a_checked_clip():
    pod = FakeWan()
    runner = FakeRunner(pod)
    clip = client_for(runner).render(i2v())
    assert snippets(runner) == I2V_STEPS
    assert clip.frames == 9 and clip.record["frames_requested"] == 9
    assert clip.record["fps"] == 24 and clip.record["measured"]["fps"] == "24"
    assert clip.record["clip_sha256"] == clip.sha256
    assert clip.record["unexpected_work_seen"] is None
    assert WanClipClient.in_flight() is None and WanClipClient.halted() is None
    assert [p for p, _ in pod.engine_calls if p in ("/interrupt",)] == []


def test_s2v_uploads_image_then_audio_and_asks_for_the_time9_length():
    pod = FakeWan()
    runner = FakeRunner(pod)
    request = s2v(board_frames=94)
    clip = client_for(runner).render(request)
    assert snippets(runner) == ["wan_probe.py", "wan_upload.py", "wan_upload.py", "wan_probe.py",
                                "wan_run.py", "wan_clip_fetch.py"]
    assert clip.record["fps"] == 16 and clip.record["measured"]["fps"] == "16"
    assert request.length == 65 and clip.record["frames_requested"] == 65
    assert clip.record["frames_delivered"] == 66  # as E0's clip for this board
    assert clip.record["chunks"] == 1 and clip.record["method"] == "s2v-lightning"
    assert clip.record["inputs"]["audio"]["ref"].endswith(".wav")


def test_the_provenance_record_has_the_fields_the_story_asks_for():
    pod = FakeWan(gpu_trace=[HOT, COOL], slow_reads=2)
    clip = client_for(FakeRunner(pod)).render(i2v())
    r = clip.record
    for key in ("job_id", "graph_sha256", "template_sha256", "model_files_sha256", "seed",
                "frames_requested", "frames_delivered", "inputs", "clip_sha256", "cooldown_s",
                "render_s", "wall_s", "start_temps", "engine_read_retries", "unexpected_work_seen",
                "admission_readback_at", "prompt_id", "cool_before_upload"):
        assert key in r, key
    assert r["start_temps"] == [[45.0, 0.0], [44.0, 0.0]]
    assert r["cooldown_s"] == 0.0  # the probe right before the run
    assert r["cool_before_upload"] == {"cooldown_s": 10.0, "start_temps": [[45.0, 0.0], [44.0, 0.0]]}
    assert r["engine_read_retries"] == 2
    assert r["template_sha256"] == pinned.PINS["wan_ti2v_workflow.json"].sha256
    assert set(r["model_files_sha256"]) == {"wan2.2_ti2v_5B_fp16.safetensors",
                                            "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "wan2.2_vae.safetensors"}
    assert r["inputs"]["image"]["sha256"] == clip.start_image_sha256
    json.dumps(r)  # plain JSON


# G1 One job per process ---------------------------------------------------------------------

def test_g1_one_job_per_process():
    pod = FakeWan()
    inner = FakeRunner(pod)
    seen = []

    class Reentrant:
        def run(self, command):
            if snippets_of(command) == "wan_run.py":
                try:
                    client_for(FakeRunner(FakeWan())).render(i2v())
                except WanError as error:
                    seen.append(error.code)
            return inner.run(command)

    client_for(Reentrant()).render(i2v())
    assert seen == [BUSY]


# G2 Cool idle (poc/wan.py wait_cool) ----------------------------------------------------------

@pytest.mark.parametrize("pod", [FakeWan(accepting=False), FakeWan(active_job="f" * 32)],
                         ids=["holding", "active-job"])
def test_g2_a_busy_or_holding_api_is_refused_at_once(pod):
    runner = FakeRunner(pod)
    error = refused(pod, client_for(runner), i2v(), BUSY)
    assert "busy or holding" in str(error)
    assert snippets(runner) == ["wan_probe.py"]
    nothing_submitted(pod)


@pytest.mark.parametrize("pod", [FakeWan(queue_running=["foreign-1"]), FakeWan(queue_pending=["foreign-2"])],
                         ids=["running", "pending"])
def test_g2_queued_unknown_work_is_refused_and_preserved(pod):
    runner = FakeRunner(pod)
    error = refused(pod, client_for(runner), i2v(), BUSY)
    assert "unknown engine work" in str(error)
    assert snippets(runner) == ["wan_probe.py"]
    nothing_submitted(pod)
    assert not any(body for _, body in pod.engine_calls)  # nothing deleted or interrupted


def test_g2_hot_gpus_are_waited_for_reading_only():
    pod = FakeWan(gpu_trace=[HOT, ((62.0, 0.0), (40.0, 0.0)), ((61.9, 5.0), (40.0, 5.0))])
    runner = FakeRunner(pod)
    clock = Clock()
    clip = client_for(runner, clock).render(i2v())
    assert snippets(runner)[:5] == ["wan_probe.py"] * 3 + ["wan_upload.py", "wan_probe.py"]
    assert clock.slept == [10, 10]
    assert clip.record["cool_before_upload"]["cooldown_s"] == 20.0
    assert clip.record["cooldown_s"] == 0.0  # still cool right before the run
    assert clip.record["start_temps"] == [[61.9, 5.0], [40.0, 5.0]]


@pytest.mark.parametrize("state", [HOT, ((50.0, 6.0), (40.0, 0.0))], ids=["hot", "busy"])
def test_g2_gpus_that_never_cool_stop_before_submission(state):
    pod = FakeWan(gpu_trace=[state])
    runner = FakeRunner(pod)
    clock = Clock()
    error = refused(pod, client_for(runner, clock), i2v(), BUSY)
    assert "cool idle" in str(error)
    assert set(snippets(runner)) == {"wan_probe.py"}
    assert sum(clock.slept) == 1810 and len(runner.calls) == 182  # reads at 0, 10, ... 1810 s
    nothing_submitted(pod)


def test_g2_an_unreadable_probe_is_an_error_not_a_pass():
    """No GPU in the sample is not "every GPU cool" (``all([])`` would pass in the PoC)."""
    pod = FakeWan()
    runner = FakeRunner(pod)

    class NoGpus:
        def run(self, command):
            result = runner.run(command)
            if snippets_of(command) == "wan_probe.py":
                answer = json.loads(result.stdout)
                answer["sample"]["gpus"] = []
                return Completed(0, json.dumps(answer).encode())
            return result
    with pytest.raises(WanError) as caught:
        client_for(NoGpus()).render(i2v())
    assert (caught.value.code, caught.value.label) == (RESPONSE_INVALID, "wan.probe")
    assert snippets(runner) == ["wan_probe.py"]


def probe_refused(runner, edit, text):
    """A render whose probe answer ``edit`` changed is refused at the probe, with ``text``."""
    with pytest.raises(WanError) as caught:
        client_for(ProbeEdit(runner, edit)).render(i2v())
    assert (caught.value.code, caught.value.label) == (RESPONSE_INVALID, "wan.probe"), caught.value
    assert text in str(caught.value)
    assert snippets(runner) == ["wan_probe.py"]


@pytest.mark.parametrize("count", [1, 3])
def test_g2_a_sample_with_other_than_two_gpus_is_an_error(count):
    """Review finding 7: one cool GPU is not "both GPUs cool"."""
    pod = FakeWan()
    runner = FakeRunner(pod)

    def edit(answer):
        answer["sample"]["gpus"] = (answer["sample"]["gpus"] * 2)[:count]
    probe_refused(runner, edit, f"shows {count} GPUs; expected exactly 2")
    nothing_submitted(pod)


def test_g2_expected_gpus_is_a_positive_integer():
    for bad in (0, -1, True, 2.0):
        with pytest.raises(ValueError):
            WanClipClient(FakeRunner(FakeWan()), journal=MemoryJournal(), expected_gpus=bad)


@pytest.mark.parametrize("queue", [
    {"queue_running": None, "queue_pending": None}, {"queue_running": [], "queue_pending": None},
    {"queue_running": None, "queue_pending": []}, {"queue_pending": []}, {"queue_running": []}, {},
    {"error": "offline"}, {"queue_running": [], "queue_pending": 0},
], ids=["both-null", "pending-null", "running-null", "running-missing", "pending-missing", "empty",
        "error-body", "pending-a-number"])
def test_g2_a_queue_answer_without_both_lists_is_an_error_never_idle(queue):
    """Review finding 4: missing evidence of an empty queue is not an empty queue."""
    pod = FakeWan()
    runner = FakeRunner(pod)
    probe_refused(runner, lambda answer: answer.update(queue=queue), "is not a list")
    nothing_submitted(pod)


@pytest.mark.parametrize("key", ["accepting_jobs", "active_job"])
def test_g2_a_health_answer_without_accepting_jobs_or_active_job_is_an_error(key):
    """Review finding 4: health must say it accepts jobs and name its active job (or null)."""
    pod = FakeWan()
    runner = FakeRunner(pod)
    probe_refused(runner, lambda answer: answer["health"].pop(key), f"health lacks {key}")
    nothing_submitted(pod)


def test_g2_cool_idle_is_checked_again_right_before_the_run():
    """Review finding 3: the uploads take time; GPUs that heated meanwhile are waited for
    again (reading only), and the record keeps both passing probes."""
    pod = FakeWan(gpu_trace=[COOL, HOT, ((50.0, 1.0), (48.0, 0.0))])
    runner = FakeRunner(pod)
    clock = Clock()
    clip = client_for(runner, clock).render(i2v())
    assert snippets(runner) == ["wan_probe.py", "wan_upload.py", "wan_probe.py", "wan_probe.py",
                                "wan_run.py", "wan_clip_fetch.py"]
    assert clock.slept == [10]
    assert clip.record["start_temps"] == [[50.0, 1.0], [48.0, 0.0]] and clip.record["cooldown_s"] == 10.0
    assert clip.record["cool_before_upload"] == {"cooldown_s": 0.0, "start_temps": [[45.0, 0.0], [44.0, 0.0]]}


@pytest.mark.parametrize("change,text", [
    (lambda pod: pod.queue_pending.append("late-foreign"), "unknown engine work"),
    (lambda pod: pod.health.update(accepting_jobs=False), "Wan API busy or holding"),
    (lambda pod: pod.health.update(active_job="f" * 32), "Wan API busy or holding"),
    (lambda pod: pod.gpu_trace.append(HOT), "cool idle"),
], ids=["queued", "holding", "active-job", "hot"])
def test_g2_work_a_hold_or_heat_that_starts_during_the_uploads_stops_before_the_run(change, text):
    """Review finding 3: the probe right before the run refuses what the first one would."""
    pod = FakeWan()
    runner = FakeRunner(pod)

    class DuringUpload:
        def run(self, command):
            result = runner.run(command)
            if snippets_of(command) == "wan_upload.py":
                change(pod)
            return result
    error = refused(pod, client_for(DuringUpload()), i2v(), BUSY)
    assert text in str(error)
    assert snippets(runner)[:3] == ["wan_probe.py", "wan_upload.py", "wan_probe.py"]
    assert runs(runner) == 0 and WanClipClient.in_flight() is None
    nothing_submitted(pod)


# G3 Admission readback (poc/wan.py RUN, lines 43-46) -----------------------------------------

def test_g3_a_hold_at_the_admission_readback_submits_nothing():
    pod = FakeWan(hold_at_admission=True)
    runner = FakeRunner(pod)
    error = refused(pod, client_for(runner), i2v(), BUSY)
    assert "admission readback" in str(error)
    assert error.in_flight is False and WanClipClient.in_flight() is None
    assert pod.jobs == {}  # refused before api.save(job)
    nothing_submitted(pod)
    assert runs(runner) == 1


def test_g3_the_readback_also_refuses_a_health_answer_without_active_job():
    pod = FakeWan()
    pod.health.pop("active_job")
    code = pinned.load("wan_run.py").text
    payload = {"job": {"id": "a" * 32, "telemetry": []}, "graph": {}, "prompt": "p"}
    result = pod.run_snippet("wan_run.py", code, (), json.dumps(payload).encode())
    assert result.returncode == 1
    assert wan.NO_SUBMISSION in result.stderr.decode()
    assert pod.jobs == {} and pod.submitted == []


# G4 The API's compute lease (api.generate) ---------------------------------------------------

def test_g4_a_busy_lease_is_a_refusal_never_a_wait():
    pod = FakeWan(lease_held=True)
    runner = FakeRunner(pod)
    clock = Clock()
    error = refused(pod, client_for(runner, clock), i2v(), BUSY)
    assert "Compute is reserved" in str(error)
    assert runs(runner) == 1 and clock.slept == []
    assert error.in_flight is False and WanClipClient.in_flight() is None
    nothing_submitted(pod)
    assert next(iter(pod.jobs.values()))["state"] == "failed"


def test_g4_gpus_busy_at_generate_fail_the_job_without_submitting():
    pod = FakeWan(busy_at_generate=True)
    runner = FakeRunner(pod)
    error = refused(pod, client_for(runner), i2v(), JOB_FAILED)
    assert "Rack GPUs are busy" in str(error)
    nothing_submitted(pod)


def test_g4_work_queued_after_the_probe_fails_the_job_without_submitting():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class Late:
        def run(self, command):
            if snippets_of(command) == "wan_run.py":
                pod.queue_pending.append("late-foreign")
            return runner.run(command)
    error = refused(pod, client_for(Late()), i2v(), JOB_FAILED)
    assert "already has a job" in str(error)
    nothing_submitted(pod)


# G5 Foreign work during the job (poc/wan.py RUN observed_engine; render() lines 146-147) ------

def test_g5_foreign_work_keeps_the_output_and_stops_further_submissions():
    pod = FakeWan(foreign_during_job=["foreign-9", "foreign-3"])
    runner = FakeRunner(pod)
    client = client_for(runner)
    error = refused(pod, client, i2v(), COMPETING_WORK)
    assert error.clip is not None and error.clip.frames == 9
    assert error.clip.record["unexpected_work_seen"] == ["foreign-3", "foreign-9"]
    assert WanClipClient.halted().unexpected_work_seen == ("foreign-3", "foreign-9")
    before = len(runner.calls)
    refused(pod, client, i2v(seed=8), COMPETING_WORK)
    assert len(runner.calls) == before  # refused before any command
    assert WanClipClient.clear_halt() is not None
    pod.foreign_during_job = []
    assert client.render(i2v(seed=8)).frames == 9


def test_g5_our_own_running_prompt_is_not_foreign_work():
    pod = FakeWan(history_polls=4)
    clip = client_for(FakeRunner(pod)).render(i2v())
    assert clip.record["unexpected_work_seen"] is None
    assert sum(1 for path, _ in pod.engine_calls if path == "/queue") >= 4


def test_g5_foreign_work_in_a_failed_job_still_halts():
    pod = FakeWan(foreign_during_job=["foreign-1"], outcome="error")
    refused(pod, client_for(FakeRunner(pod)), i2v(), JOB_FAILED)
    assert WanClipClient.halted() is not None


# G6 Read-only retries of slow engine reads (poc/wan.py RUN lines 47-55) -----------------------

def test_g6_a_slow_history_read_is_retried_and_recorded():
    pod = FakeWan(slow_reads=3)
    clip = client_for(FakeRunner(pod)).render(i2v())
    assert clip.record["engine_read_retries"] == 3
    assert pod.slept.count(5) >= 3


def test_g6_after_six_tries_the_read_fails_to_the_apis_own_miss_count():
    pod = FakeWan(slow_reads=7)
    clip = client_for(FakeRunner(pod)).render(i2v())
    assert clip.record["engine_read_retries"] == 6
    assert clip.record["poll_misses"] == 1


def test_g6_a_slow_write_is_never_retried():
    pod = FakeWan(slow_prompt=True)
    runner = FakeRunner(pod)
    error = refused(pod, client_for(runner), i2v(), JOB_FAILED)
    assert "timed out" in str(error)
    assert [p for p, body in pod.engine_calls if body] == ["/prompt"]
    assert runs(runner) == 1


# G7 A job in flight after a lost answer (scope c) --------------------------------------------

@pytest.mark.parametrize("lose,code", [("timeout", TIMEOUT), ("empty", RESPONSE_INVALID),
                                       ("exit", COMMAND_FAILED)])
def test_g7_a_lost_answer_is_never_followed_by_a_resubmission(lose, code):
    pod = FakeWan(lose=lose, lost_state="running")
    runner = FakeRunner(pod)
    client = client_for(runner)
    error = refused(pod, client, i2v(), code)
    assert error.in_flight is True and error.job_id == "0" * 31 + "1"
    assert WanClipClient.in_flight() == InFlightJob(error.job_id, code, IN_FLIGHT,
                                                    pod.payloads[0]["job"]["graph_sha256"])
    before = len(runner.calls)
    again = refused(pod, client, i2v(), BUSY)
    assert "running" in str(again) and again.in_flight is True
    assert snippets(runner)[before:] == ["wan_ledger_read.py"]  # one read, then nothing
    assert runs(runner) == 1


def test_g7_once_the_job_reads_failed_the_next_render_goes_ahead():
    pod = FakeWan(lose="timeout", lost_state="running")
    runner = FakeRunner(pod)
    client = client_for(runner)
    first = refused(pod, client, i2v(), TIMEOUT)
    pod.lose = None
    pod.jobs[first.job_id]["state"] = "failed"
    clip = client.render(i2v(seed=9))
    assert WanClipClient.in_flight() is None
    assert clip.job_id != first.job_id and runs(runner) == 2


def test_g7_a_job_with_no_ledger_stays_in_flight_until_cleared():
    pod = FakeWan(lose="no_start")
    runner = FakeRunner(pod)
    client = client_for(runner)
    refused(pod, client, i2v(), COMMAND_FAILED)
    error = refused(pod, client, i2v(), BUSY)
    assert "no ledger" in str(error)
    assert runs(runner) == 1
    pod.lose = None
    assert WanClipClient.clear_in_flight() is not None
    assert client.render(i2v()).frames == 9


def test_g7_an_unreadable_ledger_keeps_the_job_in_flight():
    pod = FakeWan(lose="timeout")
    runner = FakeRunner(pod)
    client = client_for(runner)
    refused(pod, client, i2v(), TIMEOUT)

    class ReadFails:
        def run(self, command):
            if snippets_of(command) == "wan_ledger_read.py":
                return Completed(1, b"", b"error: lost connection to pod\n")
            return runner.run(command)
    error = refused(pod, client_for(ReadFails()), i2v(), BUSY)
    assert "could not be read" in str(error)
    assert WanClipClient.in_flight() is not None


@pytest.mark.parametrize("state", ["succeeded", "failed"])
def test_g7_a_settled_job_that_saw_foreign_work_halts(state):
    pod = FakeWan(lose="empty", lost_state=None, foreign_during_job=["foreign-1"])
    runner = FakeRunner(pod)
    client = client_for(runner)
    first = refused(pod, client, i2v(), RESPONSE_INVALID)
    pod.jobs[first.job_id] = {"id": first.job_id, "state": state, "unexpected_work_seen": ["foreign-1"]}
    refused(pod, client, i2v(), COMPETING_WORK)
    assert WanClipClient.halted() is not None
    if state == "succeeded":  # its clip is still to collect
        assert WanClipClient.in_flight().state == UNCOLLECTED
    else:
        assert WanClipClient.in_flight() is None
    assert runs(runner) == 1


def test_g7_a_runner_that_never_started_the_run_leaves_nothing_in_flight():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class NoStart:
        def run(self, command):
            if snippets_of(command) == "wan_run.py":
                raise AdapterError(COMMAND_FAILED, command.label, "could not start kubectl")
            return runner.run(command)
    error = refused(pod, client_for(NoStart()), i2v(), COMMAND_FAILED)
    assert error.in_flight is False and WanClipClient.in_flight() is None
    assert snippets(runner) == ["wan_probe.py", "wan_upload.py", "wan_probe.py"]  # it reached the run
    nothing_submitted(pod)


def test_g7_an_unfinished_answer_is_in_flight():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class Running:
        def run(self, command):
            result = runner.run(command)
            if snippets_of(command) == "wan_run.py":
                answer = json.loads(result.stdout)
                answer["state"] = "running"
                return Completed(0, json.dumps(answer).encode(), result.stderr)
            return result
    error = refused(pod, client_for(Running()), i2v(), RESPONSE_INVALID)
    assert error.in_flight is True and WanClipClient.in_flight().job_id == error.job_id


def test_g7_a_runner_that_returns_no_result_leaves_the_job_in_flight():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class Nothing:
        def run(self, command):
            result = runner.run(command)
            return None if snippets_of(command) == "wan_run.py" else result
    with pytest.raises(TypeError):
        client_for(Nothing()).render(i2v())
    assert WanClipClient.in_flight().code == "unknown"


def test_g7_an_interruption_while_reading_a_failed_run_keeps_it_in_flight():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class Stderr(bytes):
        def decode(self, *args):
            raise KeyboardInterrupt

    class Interrupted:
        def run(self, command):
            result = runner.run(command)
            if snippets_of(command) == "wan_run.py":
                return Completed(1, b"", Stderr(b"error: lost connection to pod\n"))
            return result
    with pytest.raises(KeyboardInterrupt):
        client_for(Interrupted()).render(i2v())
    assert WanClipClient.in_flight().code == "unknown"


def test_g7_an_unexpected_runner_error_during_the_run_is_in_flight():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class Boom:
        def run(self, command):
            if snippets_of(command) == "wan_run.py":
                raise KeyboardInterrupt
            return runner.run(command)
    with pytest.raises(KeyboardInterrupt):
        client_for(Boom()).render(i2v())
    assert WanClipClient.in_flight().code == "unknown"


def test_g7_an_answer_for_another_job_is_lost_and_in_flight():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class Other:
        def run(self, command):
            result = runner.run(command)
            if snippets_of(command) == "wan_run.py":
                answer = json.loads(result.stdout)
                answer["id"] = "e" * 32
                return Completed(0, json.dumps(answer).encode(), result.stderr)
            return result
    error = refused(pod, client_for(Other()), i2v(), RESPONSE_INVALID)
    assert error.in_flight is True


class FetchFailsOnce:
    """A runner whose first clip fetch times out."""

    def __init__(self, runner):
        self.runner, self.failed = runner, False

    def run(self, command):
        if snippets_of(command) == "wan_clip_fetch.py" and not self.failed:
            self.failed = True
            raise AdapterError(TIMEOUT, command.label, "no answer within 90 s")
        return self.runner.run(command)


def test_g7_a_lost_fetch_keeps_the_job_uncollected_and_blocks_the_next_render():
    """Review finding 2: a succeeded job whose clip was not collected blocks every render
    until recover collects it."""
    pod = FakeWan()
    runner = FakeRunner(pod)
    client = client_for(FetchFailsOnce(runner))
    request = i2v()
    lost = refused(pod, client, request, TIMEOUT)
    assert WanClipClient.in_flight().state == UNCOLLECTED
    before = len(runner.calls)
    again = refused(pod, client, i2v(seed=8), BUSY)
    assert f"recover(request, '{lost.job_id}')" in str(again)
    assert len(runner.calls) == before  # refused before any command
    assert runs(runner) == 1 and len(pod.submitted) == 1
    clip = client.recover(request, lost.job_id)
    assert WanClipClient.in_flight() is None
    assert client.render(i2v(seed=8)).job_id != clip.job_id and runs(runner) == 2


def test_g7_a_lost_answer_whose_ledger_reads_succeeded_waits_for_recover():
    """Review finding 2: reading succeeded is not collecting the clip."""
    pod = FakeWan(lose="timeout", lost_state="running")
    runner = FakeRunner(pod)
    client = client_for(runner)
    request = i2v()
    first = refused(pod, client, request, TIMEOUT)
    pod.lose = None
    pod.jobs[first.job_id]["state"] = "succeeded"
    assert "recover" in str(refused(pod, client, i2v(seed=9), BUSY))
    assert WanClipClient.in_flight().state == UNCOLLECTED
    refused(pod, client, i2v(seed=9), BUSY)  # without reading the ledger again
    assert snippets(runner).count("wan_ledger_read.py") == 1 and runs(runner) == 1
    client.recover(request, first.job_id)
    assert client.render(i2v(seed=9)).frames == 9 and runs(runner) == 2


def test_g7_a_clip_that_fails_its_checks_stays_uncollected_until_a_person_clears_it():
    pod = FakeWan(deliver_frames=40)
    runner = FakeRunner(pod)
    client = client_for(runner)
    error = refused(pod, client, i2v(), RESPONSE_INVALID)
    assert WanClipClient.in_flight().state == UNCOLLECTED
    refused(pod, client, i2v(seed=8), BUSY)
    with pytest.raises(WanError):
        client.recover(i2v(), error.job_id)  # the same check fails again
    assert WanClipClient.in_flight().job_id == error.job_id and runs(runner) == 1
    assert WanClipClient.clear_in_flight().job_id == error.job_id
    pod.deliver_frames = None
    assert client.render(i2v(seed=8)).frames == 9


# G8 Create-only, verified uploads (poc/wan.py UPLOAD) ----------------------------------------

def test_g8_uploads_are_created_once_and_never_overwritten():
    pod = FakeWan()
    client = client_for(FakeRunner(pod))
    client.render(i2v())
    client.render(i2v(seed=8))  # the same image again
    creates = [path for op, path in pod.writes if op == "create"]
    assert len(creates) == 1 and creates[0].startswith("/workspace/input/studio-e0/")
    name = creates[0].rsplit("/", 1)[1]
    assert name == wan.upload_name(synthetic_png(seed=1), ".png") and len(name) == 20


def test_g8_an_upload_that_differs_from_an_existing_file_is_refused():
    request = i2v()
    path = "/workspace/input/studio-e0/" + wan.upload_name(request.image_png, ".png")
    pod = FakeWan(files={path: b"other bytes"})
    runner = FakeRunner(pod)
    with pytest.raises(WanError) as caught:
        client_for(runner).render(request)
    assert caught.value.code == COMMAND_FAILED and "nothing was overwritten" in str(caught.value)
    assert pod.files[path] == b"other bytes"
    assert runs(runner) == 0
    nothing_submitted(pod)


def test_g8_an_upload_whose_read_back_differs_is_refused():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class WrongEcho:
        def run(self, command):
            if snippets_of(command) == "wan_upload.py":
                runner.run(command)
                return Completed(0, b"0" * 64 + b"\n")
            return runner.run(command)
    with pytest.raises(WanError) as caught:
        client_for(WrongEcho()).render(i2v())
    assert caught.value.code == RESPONSE_INVALID
    nothing_submitted(pod)


def test_g8_the_upload_snippet_checks_the_hash_of_what_it_was_given():
    pod = FakeWan()
    code = pinned.load("wan_upload.py").text
    result = pod.run_snippet("wan_upload.py", code, ("x.png", "0" * 64), b"\x89PNG")
    assert result.returncode == 1 and pod.files == {}


# G9 A failed, short or corrupt result is an error, never a clip ------------------------------

@pytest.mark.parametrize("outcome,text", [("error", "generation failed"), ("no_mp4", "without an MP4")])
def test_g9_a_failed_job_is_an_error(outcome, text):
    pod = FakeWan(outcome=outcome)
    runner = FakeRunner(pod)
    error = refused(pod, client_for(runner), i2v(), JOB_FAILED)
    assert text in str(error) and error.clip is None
    assert "wan_clip_fetch.py" not in snippets(runner)
    assert WanClipClient.in_flight() is None


def test_g9_a_short_clip_is_an_error():
    pod = FakeWan(deliver_frames=8)
    error = refused(pod, client_for(FakeRunner(pod)), i2v(), RESPONSE_INVALID)
    assert "short" in str(error)


def test_g9_a_short_s2v_clip_is_an_error():
    pod = FakeWan(deliver_frames=64)
    error = refused(pod, client_for(FakeRunner(pod)), s2v(board_frames=94), RESPONSE_INVALID)
    assert "asked for 65" in str(error)


def test_g9_a_clip_of_another_size_is_an_error():
    pod = FakeWan(deliver_size=(64, 96))
    error = refused(pod, client_for(FakeRunner(pod)), i2v(), RESPONSE_INVALID)
    assert "64x96" in str(error)


def test_g9_a_corrupt_clip_is_an_error():
    pod = FakeWan(corrupt_clip=True)
    error = refused(pod, client_for(FakeRunner(pod)), i2v(), RESPONSE_INVALID)
    assert "does not decode" in str(error)


def test_g9_a_clip_cut_in_transfer_is_an_error():
    pod = FakeWan(mangle_fetch=True)
    error = refused(pod, client_for(FakeRunner(pod)), i2v(), RESPONSE_INVALID)
    assert "differs from what the pod read" in str(error)


def test_g9_a_fetch_that_times_out_names_the_job_and_leaves_it_uncollected():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class SlowFetch:
        def run(self, command):
            if snippets_of(command) == "wan_clip_fetch.py":
                raise AdapterError(TIMEOUT, command.label, "no answer within 90 s")
            return runner.run(command)
    error = refused(pod, client_for(SlowFetch()), i2v(), TIMEOUT)
    assert error.job_id and f"/videos/{error.job_id}/file" in str(error)
    assert WanClipClient.in_flight().state == UNCOLLECTED and runs(runner) == 1


def test_g9_a_clip_of_another_size_than_the_ledger_is_an_error():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class Ledger:
        def run(self, command):
            result = runner.run(command)
            if snippets_of(command) == "wan_run.py":
                answer = json.loads(result.stdout)
                answer["bytes"] += 1
                return Completed(0, json.dumps(answer).encode(), result.stderr)
            return result
    error = refused(pod, client_for(Ledger()), i2v(), RESPONSE_INVALID)
    assert "its ledger says" in str(error)


@pytest.mark.parametrize("make,frames,expected", [(lambda: i2v(), 13, 9), (lambda: i2v(), 40, 9),
                                                  (lambda: s2v(board_frames=94), 67, 66)],
                         ids=["i2v-13", "i2v-40", "s2v-67"])
def test_g9_a_clip_with_other_frames_than_its_graph_makes_is_an_error(make, frames, expected):
    """Review finding 5: image-to-video makes exactly ``length`` frames, speech-to-video
    exactly what every E0 clip had; more is an error too, and the job stays uncollected."""
    pod = FakeWan(deliver_frames=frames)
    error = refused(pod, client_for(FakeRunner(pod)), make(), RESPONSE_INVALID)
    assert f"has {frames} frames; its graph makes exactly {expected}" in str(error)
    assert error.clip is None and WanClipClient.in_flight().state == UNCOLLECTED


@pytest.mark.parametrize("make,fps", [(lambda: i2v(), 1), (lambda: i2v(), 16), (lambda: s2v(board_frames=94), 24)],
                         ids=["i2v-1", "i2v-16", "s2v-24"])
def test_g9_a_clip_at_another_rate_is_an_error(make, fps):
    """Review finding 5: the measured rate must be the graph's (24 fps, or 16 for S2V)."""
    pod = FakeWan(deliver_fps=fps)
    error = refused(pod, client_for(FakeRunner(pod)), make(), RESPONSE_INVALID)
    assert f"plays at {fps} fps" in str(error)
    assert error.clip is None and WanClipClient.in_flight().state == UNCOLLECTED


def test_g9_a_clip_with_no_measured_rate_is_an_error(monkeypatch):
    monkeypatch.setattr(wan, "measure_clip", lambda body: wan.Measured(9, 64, 128, ""))
    pod = FakeWan()
    error = refused(pod, client_for(FakeRunner(pod)), i2v(), RESPONSE_INVALID)
    assert "no measured rate" in str(error)


# G10 Nothing runs for a bad request or a changed pin ------------------------------------------

@pytest.mark.parametrize("change", [
    {"prompt": ""}, {"prompt": "x" * 4097}, {"seed": -1}, {"seed": 2 ** 53}, {"seed": True},
    {"story": "#428"}, {"story": "https://work.haynesnetwork.com/work_packages/428/x"},
    {"width": 100}, {"height": 32}, {"length": 10}, {"length": 125}, {"image_png": b"GIF89a"},
    {"negative": ""},
])
def test_g10_a_bad_i2v_request_is_refused_before_anything_runs(change):
    with pytest.raises(RequestInvalid):
        i2v(**change)


@pytest.mark.parametrize("change", [
    {"board_frames": 0}, {"board_frames": 343},
    {"drive_wav": synthetic_wav(11000)}, {"drive_wav": b"RIFF"}, {"seed": 2 ** 53 - 2},
])
def test_g10_a_bad_s2v_request_is_refused_before_anything_runs(change):
    with pytest.raises(RequestInvalid):
        s2v(**change)


def test_g10_s2v_takes_the_longest_board_e0_ran_and_a_drive_rounded_to_one_sample():
    assert s2v_length(342) == 231 and s2v_length(343) == 308  # 3 chunks, then 4 (refused above)
    assert s2v(board_frames=13, rate=16000).board_frames == 13  # 8666.67 samples: floor or ceil
    s2v(board_frames=13, rate=16000, drive_wav=synthetic_wav(8667, rate=16000))
    with pytest.raises(RequestInvalid):
        s2v(board_frames=13, rate=16000, drive_wav=synthetic_wav(8668, rate=16000))


def test_g10_a_changed_template_or_snippet_is_refused_before_anything_runs():
    pod = FakeWan()
    runner = FakeRunner(pod)
    with pytest.raises(PinMismatch):
        WanClipClient(runner, journal=MemoryJournal(), i2v_template=pinned.PinnedInput(
            "wan_ti2v_workflow.json", pinned.load("wan_ti2v_workflow.json").data + b" "))
    for attribute, name in (("probe_snippet", "wan_probe.py"), ("run_snippet", "wan_run.py"),
                            ("fetch_snippet", "wan_clip_fetch.py"), ("i2v_template", "wan_ti2v_workflow.json")):
        client = client_for(runner)
        setattr(client, attribute, pinned.PinnedInput(name, getattr(client, attribute).data + b"\n"))
        with pytest.raises(AdapterError) as caught:
            client.render(i2v())
        assert caught.value.code == PIN_MISMATCH
    assert runner.calls == []
    nothing_submitted(pod)


def test_g10_a_job_id_that_is_not_the_apis_form_is_refused():
    client = WanClipClient(FakeRunner(FakeWan()), journal=MemoryJournal(), new_job_id=lambda: "../etc")
    with pytest.raises(RequestInvalid) as caught:
        client.render(i2v())
    assert caught.value.code == REQUEST_INVALID


# G11 Collecting a finished job instead of rendering it again ---------------------------------

def test_g11_recover_collects_a_lost_answers_clip_without_a_second_job():
    pod = FakeWan(lose="empty", lost_state="succeeded")
    runner = FakeRunner(pod)
    client = client_for(runner)
    request = i2v()
    lost = refused(pod, client, request, RESPONSE_INVALID)
    clip = client.recover(request, lost.job_id)
    assert clip.job_id == lost.job_id and clip.frames == 9 and clip.record["recovered"] is True
    assert clip.record["cooldown_s"] is None and clip.record["inputs"]["image"]["sha256"] == request.image_sha256
    assert WanClipClient.in_flight() is None
    assert runs(runner) == 1 and snippets(runner)[-2:] == ["wan_ledger_read.py", "wan_clip_fetch.py"]


def test_g11_recover_after_a_failed_fetch():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class SlowOnce:
        failed = False

        def run(self, command):
            if snippets_of(command) == "wan_clip_fetch.py" and not self.failed:
                self.failed = True
                raise AdapterError(TIMEOUT, command.label, "no answer within 90 s")
            return runner.run(command)
    client = client_for(SlowOnce())
    request = s2v()
    error = refused(pod, client, request, TIMEOUT)
    assert "recover" in str(error)
    clip = client.recover(request, error.job_id)
    assert clip.record["frames_requested"] == 9 and runs(runner) == 1


def test_g11_recover_refuses_another_requests_job_and_an_unfinished_one():
    pod = FakeWan(lose="timeout", lost_state="running")
    client = client_for(FakeRunner(pod))
    lost = refused(pod, client, i2v(), TIMEOUT)
    with pytest.raises(WanError) as caught:
        client.recover(i2v(seed=99), lost.job_id)
    assert caught.value.code == RESPONSE_INVALID
    with pytest.raises(WanError) as caught:
        client.recover(i2v(), lost.job_id)
    assert caught.value.code == BUSY and WanClipClient.in_flight() is not None


def test_g11_recover_keeps_the_halt_rule():
    pod = FakeWan(lose="empty", lost_state="succeeded", foreign_during_job=["foreign-1"])
    runner = FakeRunner(pod)
    client = client_for(runner)
    lost = refused(pod, client, i2v(), RESPONSE_INVALID)
    with pytest.raises(WanError) as caught:
        client.recover(i2v(), lost.job_id)  # recover is the first to read the ledger
    assert caught.value.code == COMPETING_WORK and caught.value.clip.frames == 9
    assert WanClipClient.halted().unexpected_work_seen == ("foreign-1",)
    refused(pod, client, i2v(seed=8), COMPETING_WORK)
    assert runs(runner) == 1


def test_g11_recover_reports_a_failed_job_as_failed():
    pod = FakeWan(lose="empty", lost_state="failed")
    runner = FakeRunner(pod)
    client = client_for(runner)
    lost = refused(pod, client, i2v(), RESPONSE_INVALID)
    with pytest.raises(WanError) as caught:
        client.recover(i2v(), lost.job_id)
    assert caught.value.code == JOB_FAILED and caught.value.clip is None
    assert "wan_clip_fetch.py" not in snippets(runner) and WanClipClient.in_flight() is None


def test_g11_a_recover_whose_fetch_fails_leaves_the_job_uncollected():
    pod = FakeWan(lose="empty", lost_state="succeeded")
    runner = FakeRunner(pod)
    client = client_for(FetchFailsOnce(runner))
    request = i2v()
    lost = refused(pod, client, request, RESPONSE_INVALID)
    assert WanClipClient.in_flight().state == IN_FLIGHT
    with pytest.raises(WanError) as caught:
        client.recover(request, lost.job_id)
    assert caught.value.code == TIMEOUT and WanClipClient.in_flight().state == UNCOLLECTED
    refused(pod, client, i2v(seed=8), BUSY)
    assert client.recover(request, lost.job_id).frames == 9 and WanClipClient.in_flight() is None
    assert runs(runner) == 1


def test_g11_the_job_carries_the_hash_of_the_graph_it_was_sent_with():
    """Review finding 1: the ledger keeps the graph's SHA-256, so recover can check it."""
    pod = FakeWan()
    clip = client_for(FakeRunner(pod)).render(s2v())
    payload = pod.payloads[0]
    assert payload["job"]["graph_sha256"] == wan.graph_sha256(payload["graph"]) == clip.record["graph_sha256"]
    assert pod.jobs[clip.job_id]["graph_sha256"] == clip.record["graph_sha256"]


@pytest.mark.parametrize("change", [{"prompt": "a completely different line"},
                                    {"negative": "not the original negative"},
                                    {"story": "https://work.haynesnetwork.com/work_packages/429"}],
                         ids=["prompt", "negative", "story"])
def test_g11_recover_refuses_a_job_made_for_another_prompt_negative_or_story(change):
    """Review finding 1: same image, seed and size is not the same request."""
    pod = FakeWan(lose="empty", lost_state="succeeded")
    runner = FakeRunner(pod)
    client = client_for(runner)
    lost = refused(pod, client, i2v(prompt="the original line"), RESPONSE_INVALID)
    with pytest.raises(WanError) as caught:
        client.recover(i2v(**{"prompt": "the original line", **change}), lost.job_id)
    assert caught.value.code == RESPONSE_INVALID and "not made for this request" in str(caught.value)
    assert "wan_clip_fetch.py" not in snippets(runner) and runs(runner) == 1
    assert WanClipClient.in_flight().job_id == lost.job_id  # it still blocks
    assert client.recover(i2v(prompt="the original line"), lost.job_id).job_id == lost.job_id


def test_g11_recover_refuses_a_ledger_without_graph_sha256():
    """Review finding 1: every E0 job's ledger lacks it, so none can be proven the
    request's job; old jobs are imported another way."""
    pod = FakeWan(lose="empty", lost_state="succeeded")
    runner = FakeRunner(pod)
    client = client_for(runner)
    request = i2v()
    lost = refused(pod, client, request, RESPONSE_INVALID)
    del pod.jobs[lost.job_id]["graph_sha256"]
    with pytest.raises(WanError) as caught:
        client.recover(request, lost.job_id)
    assert caught.value.code == RESPONSE_INVALID and "has no graph_sha256" in str(caught.value)
    assert "wan_clip_fetch.py" not in snippets(runner)


# G12 The journal: what blocks renders outlives the process (review finding 6) ----------------

def test_g12_a_client_needs_a_journal():
    with pytest.raises(TypeError):
        WanClipClient(FakeRunner(FakeWan()))  # the missing journal is the point
    for bad in (None, {}, "wan-journal.jsonl"):
        with pytest.raises(TypeError):
            WanClipClient(FakeRunner(FakeWan()), journal=bad)


def test_g12_the_job_is_journalled_before_the_run_starts(journal):
    pod = FakeWan()
    runner = FakeRunner(pod)
    seen = []

    class Look:
        def run(self, command):
            if snippets_of(command) == "wan_run.py":
                seen.append(reopen(journal).load())
            return runner.run(command)
    clip = client_for(Look(), journal=journal).render(i2v())
    assert seen == [InFlightJob(clip.job_id, "journal", IN_FLIGHT, clip.record["graph_sha256"])]
    assert events(journal) == ["remember in_flight", "remember uncollected", "settle collected"]
    assert reopen(journal).load() is None


def test_g12_a_journal_that_cannot_be_written_runs_nothing(tmp_path):
    pod = FakeWan()
    runner = FakeRunner(pod)
    error = refused(pod, client_for(runner, journal=FileJournal(tmp_path / "no-such-dir" / "j.jsonl")),
                    i2v(), JOURNAL_FAILED)
    assert "could not be written" in str(error)
    assert runs(runner) == 0 and WanClipClient.in_flight() is None
    nothing_submitted(pod)


def test_g12_a_new_process_loads_the_unsettled_job_and_behaves_as_the_one_that_submitted(journal):
    pod = FakeWan(lose="timeout", lost_state="running")
    runner = FakeRunner(pod)
    request = i2v()
    first = refused(pod, client_for(runner, journal=journal), request, TIMEOUT)
    pod.lose = None
    restart()
    client = client_for(runner, journal=reopen(journal), ids=Ids(100))
    assert WanClipClient.in_flight() == InFlightJob(first.job_id, "journal", IN_FLIGHT,
                                                    pod.payloads[0]["job"]["graph_sha256"])
    refused(pod, client, i2v(seed=8), BUSY)  # its ledger reads running
    pod.jobs[first.job_id]["state"] = "succeeded"
    refused(pod, client, i2v(seed=8), BUSY)  # now uncollected, and journalled so
    restart()
    client = client_for(runner, journal=reopen(journal), ids=Ids(200))
    assert WanClipClient.in_flight().state == UNCOLLECTED
    assert "recover" in str(refused(pod, client, i2v(seed=8), BUSY))
    assert runs(runner) == 1
    client.recover(request, first.job_id)
    restart()
    client = client_for(runner, journal=reopen(journal), ids=Ids(300))
    assert WanClipClient.in_flight() is None
    assert client.render(i2v(seed=8)).frames == 9 and runs(runner) == 2


def test_g12_a_job_settled_by_its_failed_ledger_stays_settled_in_a_new_process(journal):
    pod = FakeWan(lose="timeout", lost_state="failed")
    runner = FakeRunner(pod)
    refused(pod, client_for(runner, journal=journal), i2v(), TIMEOUT)
    pod.lose = None
    assert client_for(runner, journal=journal, ids=Ids(100)).render(i2v(seed=8)).frames == 9
    restart()
    assert reopen(journal).load() is None
    assert events(journal)[:2] == ["remember in_flight", "settle failed"]


def test_g12_clear_in_flight_appends_a_cleared_line_a_new_process_reads(journal):
    pod = FakeWan(lose="no_start")
    runner = FakeRunner(pod)
    refused(pod, client_for(runner, journal=journal), i2v(), COMMAND_FAILED)  # no ledger: stays
    restart()
    client = client_for(runner, journal=reopen(journal), ids=Ids(100))
    assert "no ledger" in str(refused(pod, client, i2v(), BUSY))
    before = journal_bytes(journal)
    assert WanClipClient.clear_in_flight().code == "journal"
    after = journal_bytes(journal)
    assert after.startswith(before) and json.loads(after[len(before):])["outcome"] == "cleared"
    restart()
    pod.lose = None
    assert client_for(runner, journal=reopen(journal), ids=Ids(200)).render(i2v()).frames == 9


def test_g12_the_halt_outlives_the_process(journal):
    pod = FakeWan(foreign_during_job=["foreign-1"])
    runner = FakeRunner(pod)
    refused(pod, client_for(runner, journal=journal), i2v(), COMPETING_WORK)
    pod.foreign_during_job = []
    restart()
    client = client_for(runner, journal=reopen(journal), ids=Ids(100))
    assert WanClipClient.halted().unexpected_work_seen == ("foreign-1",)
    refused(pod, client, i2v(seed=8), COMPETING_WORK)
    assert runs(runner) == 1
    WanClipClient.clear_halt()
    restart()
    assert client_for(runner, journal=reopen(journal), ids=Ids(200)).render(i2v(seed=8)).frames == 9
    assert "clear_halt " + "0" * 31 + "1" in events(journal)


def test_g12_a_journal_job_other_than_the_one_the_process_holds_is_refused():
    pod = FakeWan(lose="timeout")
    runner = FakeRunner(pod)
    held = refused(pod, client_for(runner), i2v(), TIMEOUT)
    other = MemoryJournal()
    other.remember("b" * 32, IN_FLIGHT, "0" * 64)
    with pytest.raises(WanError) as caught:
        client_for(runner, journal=other)
    assert caught.value.code == BUSY and held.job_id in str(caught.value) and "b" * 32 in str(caught.value)


def _line(**event):
    journal = MemoryJournal(wall=lambda: 0.0)
    journal._write(event)
    return journal.data


A, B, G = "a" * 32, "b" * 32, "0" * 64
REMEMBER_A = _line(event="remember", job_id=A, state=IN_FLIGHT, graph_sha256=G)


@pytest.mark.parametrize("data", [
    b"not json\n", b"\n", b"\xff\n", REMEMBER_A[:-1], REMEMBER_A + b'{"v": 1, "event": "settle"',
    REMEMBER_A + _line(event="remember", job_id=B, state=IN_FLIGHT, graph_sha256=G),
    REMEMBER_A + _line(event="remember", job_id=A, state=UNCOLLECTED, graph_sha256="1" * 64),
    _line(event="settle", job_id=A, outcome="cleared"),
    REMEMBER_A + _line(event="settle", job_id=B, outcome="cleared"),
    _line(event="clear_halt", job_id=A),
    _line(event="halt", job_id=A, unexpected_work_seen=["x"]) + _line(event="clear_halt", job_id=B),
    REMEMBER_A.replace(b'"v": 1', b'"v": 2'), REMEMBER_A.replace(b'"in_flight"', b'"running"'),
    REMEMBER_A.replace(A.encode(), b"../etc"), REMEMBER_A.replace(b'"remember"', b'"forget"'),
    REMEMBER_A.replace(b'"at"', b'"extra": 1, "at"'), REMEMBER_A.replace(b', "graph_sha256": "' + G.encode() + b'"', b""),
    REMEMBER_A + _line(event="settle", job_id=A, outcome="cleared").replace(b"cleared", b"gone"),
    _line(event="halt", job_id=A, unexpected_work_seen=["x"]).replace(b'["x"]', b"[]"),
], ids=["not-json", "empty-line", "not-utf8", "incomplete-line", "incomplete-last-line", "two-unsettled",
        "graph-changed", "settle-unknown", "settle-other", "clear-no-halt", "clear-other-halt", "version",
        "state", "job-id", "event", "extra-key", "missing-key", "outcome", "empty-halt"])
def test_g12_a_journal_that_does_not_read_exactly_submits_nothing(data, tmp_path):
    pod = FakeWan()
    runner = FakeRunner(pod)
    path = tmp_path / "wan-journal.jsonl"
    path.write_bytes(data)
    for journal in (MemoryJournal(data), FileJournal(path)):
        with pytest.raises(WanError) as caught:
            client_for(runner, journal=journal)
        assert caught.value.code == JOURNAL_FAILED and caught.value.label == "wan.journal"
    good = MemoryJournal()
    client = client_for(runner, journal=good)
    good.data += data  # damaged after the client was made: the next render reads it again
    error = refused(pod, client, i2v(), JOURNAL_FAILED)
    assert "inspected" in str(error)
    assert runner.calls == [] and WanClipClient.in_flight() is None
    nothing_submitted(pod)


def test_g12_an_unreadable_journal_submits_nothing(tmp_path):
    with pytest.raises(WanError) as caught:
        client_for(FakeRunner(FakeWan()), journal=FileJournal(tmp_path))  # a directory
    assert caught.value.code == JOURNAL_FAILED and "could not be read" in str(caught.value)


def test_g12_a_missing_journal_file_is_an_empty_journal(tmp_path):
    path = tmp_path / "wan-journal.jsonl"
    journal = FileJournal(path)
    assert journal.load() is None and journal.load_halt() is None and not path.exists()


def test_g12_the_file_journal_appends_one_fsynced_line_per_event(tmp_path, monkeypatch):
    path = tmp_path / "wan-journal.jsonl"
    journal = FileJournal(path)
    opened, synced, real_open, real_fsync = [], [], os.open, os.fsync

    def spy_open(target, flags, *args):
        fd = real_open(target, flags, *args)
        opened.append((os.fspath(target), flags))  # the opens that succeeded
        return fd

    def spy_fsync(fd):
        synced.append(os.fstat(fd).st_ino)  # which file or directory was synced
        return real_fsync(fd)
    contents = []
    with monkeypatch.context() as patch:
        patch.setattr(wan.os, "open", spy_open)
        patch.setattr(wan.os, "fsync", spy_fsync)
        for write in (lambda: journal.remember(A, IN_FLIGHT, G), lambda: journal.remember(A, UNCOLLECTED, G),
                      lambda: journal.halt(A, ["x"]), lambda: journal.settle(A, "collected"),
                      lambda: journal.clear_halt(A)):
            write()
            contents.append(path.read_bytes())
    flags = [f for target, f in opened if target == os.fspath(path)]
    assert len(flags) == 5 and all(f & os.O_APPEND and not f & os.O_TRUNC for f in flags)
    assert flags[0] & os.O_EXCL and flags[0] & os.O_CREAT  # created once, then opened to append
    assert synced.count(path.stat().st_ino) == 5  # every line synced
    assert synced.count(tmp_path.stat().st_ino) == 1  # and the directory that got the new file
    assert all(b.startswith(a) and b.count(b"\n") == a.count(b"\n") + 1 for a, b in zip(contents, contents[1:]))
    assert FileJournal(path).load() is None and FileJournal(path).load_halt() is None


def _code(cls):
    """A class's code without its docstrings or comments."""
    tree = ast.parse(inspect.getsource(cls))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef | ast.FunctionDef) and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_g12_the_journal_code_never_rewrites_truncates_or_deletes():
    text = "".join(_code(cls) for cls in (wan.Journal, wan.FileJournal, wan.MemoryJournal))
    assert "os.O_APPEND" in text and "os.fsync" in text
    for word in ("truncate", "O_TRUNC", "unlink", "remove", "rename", ".replace(", "rmtree", "write_bytes",
                 "write_text", "'w'", '"w"', "'wb'", '"wb"', "seek"):
        assert word not in text, word


# The fake pod behaves like the real one ---------------------------------------------------------

def test_each_run_gets_a_fresh_api_module_so_records_belong_to_their_job():
    pod = FakeWan()
    client = client_for(FakeRunner(pod))
    first = client.render(i2v())
    pod.slow_reads = 2
    second = client.render(i2v(seed=8))
    assert first.record["engine_read_retries"] == 0
    assert second.record["engine_read_retries"] == 2
    assert pod.jobs[second.job_id]["engine_read_retries"] == 2


def test_the_apis_90_second_miss_rule_fails_a_job_whose_engine_stalls():
    pod = FakeWan(slow_reads=12)
    error = refused(pod, client_for(FakeRunner(pod)), i2v(), JOB_FAILED)
    assert "timed out" in str(error)
    assert pod.jobs[error.job_id]["poll_misses"] == 2  # 145 s of stalled reads, then 90 s since the first miss
    assert ("/interrupt", True) in pod.engine_calls  # the API interrupted its own prompt


# Reads -------------------------------------------------------------------------------------

def test_read_job_reads_a_ledger_and_reports_a_missing_one():
    pod = FakeWan()
    client = client_for(FakeRunner(pod))
    clip = client.render(i2v())
    assert client.read_job(clip.job_id)["state"] == "succeeded"
    with pytest.raises(WanError) as caught:
        client.read_job("d" * 32)
    assert caught.value.code == NOT_FOUND


def test_time9_lengths_and_needs():
    assert [s2v_length(f) for f in (153, 94, 146, 84, 83, 122, 251, 108)] == \
        [154, 65, 154, 57, 57, 154, 231, 73]
    assert all(s2v_length(f) >= s2v_frames_needed(f) for f in range(1, 343))


# The snippets only read, except the create-only upload and the job's own ledger --------------

FORBIDDEN = ("unlink", "rmtree", "remove", "rename", "replace", "/interrupt", "'delete'", '"delete"',
             "shutil", "os.", "'w'", "'wb'", "'a'", "write_bytes", "write_text", "chmod", "kill")


@pytest.mark.parametrize("name", ["wan_probe.py", "wan_upload.py", "wan_run.py", "wan_clip_fetch.py",
                                  "wan_ledger_read.py"])
def test_no_snippet_deletes_moves_interrupts_or_overwrites(name):
    text = pinned.load(name).text
    assert [word for word in FORBIDDEN if word in text] == []
    opens = [part for part in text.split(".open(")[1:]]
    assert all(part.startswith("'xb'") for part in opens)  # wan_upload.py: create-only
