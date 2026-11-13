"""The Wan clip client's guards (story 842), each proven through the fake Wan pod.

``FakeWan`` runs the pinned in-pod snippets themselves (wan_probe.py, wan_upload.py,
wan_run.py, wan_clip_fetch.py, wan_ledger_read.py) against a port of the installed
``api.generate()``, so the snippet guards (admission readback, read-only retries, the
foreign-work observer) are exercised here, not only the client's. Every test names the
guard it proves; docs/reference/legacy-adapters.md has the table (PoC line, code, test).
No test sleeps: the client's clock and sleep are fakes, and so is the pod's.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from haynes_studio.adapters import pinned, wan
from haynes_studio.adapters.errors import (
    BUSY,
    COMMAND_FAILED,
    COMPETING_WORK,
    JOB_FAILED,
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
    ImageToVideo,
    InFlightJob,
    SpeechToVideo,
    WanClipClient,
    s2v_frames_needed,
    s2v_length,
)

STORY = "https://work.haynesnetwork.com/work_packages/428"
COOL = ((45.0, 0.0), (44.0, 0.0))
HOT = ((70.0, 0.0), (66.0, 0.0))


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
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"{self.n:032x}"


def client_for(runner, clock=None):
    clock = clock or Clock()
    return WanClipClient(runner, clock=clock, wall=clock.wall, sleep=clock.sleep, new_job_id=Ids())


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
    assert snippets(runner) == ["wan_probe.py", "wan_upload.py", "wan_run.py", "wan_clip_fetch.py"]
    assert clip.frames == 9 and clip.record["frames_requested"] == 9
    assert clip.record["clip_sha256"] == clip.sha256
    assert clip.record["unexpected_work_seen"] is None
    assert WanClipClient.in_flight() is None and WanClipClient.halted() is None
    assert [p for p, _ in pod.engine_calls if p in ("/interrupt",)] == []


def test_s2v_uploads_image_then_audio_and_asks_for_the_time9_length():
    pod = FakeWan()
    runner = FakeRunner(pod)
    request = s2v(board_frames=94)
    clip = client_for(runner).render(request)
    assert snippets(runner) == ["wan_probe.py", "wan_upload.py", "wan_upload.py", "wan_run.py",
                                "wan_clip_fetch.py"]
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
                "admission_readback_at", "prompt_id"):
        assert key in r, key
    assert r["start_temps"] == [[45.0, 0.0], [44.0, 0.0]]
    assert r["cooldown_s"] == 10.0
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
    assert snippets(runner)[:4] == ["wan_probe.py"] * 3 + ["wan_upload.py"]
    assert clock.slept == [10, 10]
    assert clip.record["cooldown_s"] == 20.0
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
    assert WanClipClient.in_flight() == InFlightJob(error.job_id, code)
    before = len(runner.calls)
    again = refused(pod, client, i2v(), BUSY)
    assert "running" in str(again) and again.in_flight is True
    assert snippets(runner)[before:] == ["wan_ledger_read.py"]  # one read, then nothing
    assert runs(runner) == 1


def test_g7_once_the_job_reads_finished_the_next_render_goes_ahead():
    pod = FakeWan(lose="timeout", lost_state="running")
    runner = FakeRunner(pod)
    client = client_for(runner)
    first = refused(pod, client, i2v(), TIMEOUT)
    pod.lose = None
    pod.jobs[first.job_id]["state"] = "succeeded"
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


def test_g7_a_settled_job_that_saw_foreign_work_halts():
    pod = FakeWan(lose="empty", lost_state=None, foreign_during_job=["foreign-1"])
    runner = FakeRunner(pod)
    client = client_for(runner)
    first = refused(pod, client, i2v(), RESPONSE_INVALID)
    pod.jobs[first.job_id] = {"id": first.job_id, "state": "succeeded", "unexpected_work_seen": ["foreign-1"]}
    refused(pod, client, i2v(), COMPETING_WORK)
    assert WanClipClient.in_flight() is None and WanClipClient.halted() is not None
    assert runs(runner) == 1


def test_g7_a_runner_that_never_started_leaves_nothing_in_flight():
    class NoStart:
        def run(self, command):
            raise AdapterError(COMMAND_FAILED, command.label, "could not start kubectl")
    with pytest.raises(AdapterError):
        client_for(NoStart()).render(i2v())
    assert WanClipClient.in_flight() is None


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


def test_g9_a_fetch_that_times_out_names_the_job_and_leaves_nothing_in_flight():
    pod = FakeWan()
    runner = FakeRunner(pod)

    class SlowFetch:
        def run(self, command):
            if snippets_of(command) == "wan_clip_fetch.py":
                raise AdapterError(TIMEOUT, command.label, "no answer within 90 s")
            return runner.run(command)
    error = refused(pod, client_for(SlowFetch()), i2v(), TIMEOUT)
    assert error.job_id and f"/videos/{error.job_id}/file" in str(error)
    assert WanClipClient.in_flight() is None and runs(runner) == 1


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
        WanClipClient(runner, i2v_template=pinned.PinnedInput(
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
    client = WanClipClient(FakeRunner(FakeWan()), new_job_id=lambda: "../etc")
    with pytest.raises(RequestInvalid) as caught:
        client.render(i2v())
    assert caught.value.code == REQUEST_INVALID


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
