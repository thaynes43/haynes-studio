"""Run one Studio worker with HTTP access to Studio API, Wan and the ASR service."""

import argparse
import logging
import os
import re
from contextlib import ExitStack
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep

import httpx

from haynes_studio.build.errors import BuildError, failure_of
from haynes_studio.build.live import WanChainSource, WanS2VSource, check_request
from haynes_studio.build.pipeline import ALL, BuildInputs, QueuedBuild, build_story
from haynes_studio.build.prebuild import snapshot_bytes
from haynes_studio.build.sources import ClipSources
from haynes_studio.library import Library
from haynes_studio.model_register import load_model_register
from haynes_studio.store import LocalStore, PRESENT

from .asr import WyomingTranscriber
from .inputs import freeze, prepare_queue
from .protocol import STORY_PATTERN
from .progress import ProgressFile
from .staging import BuildStageStore
from .wan import AttemptFailed, BuildCancelled, LanePaused, ProductClips, ProductWan
from .worker_api import WorkerAPI, WorkerAPIError, service_url
from .worker_tokens import worker_bearer

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15
IDLE_SECONDS = 5
PERCENT = {"preflight": 5, "wan_preparing": 15, "wan_submitting": 25, "wan_poll": 35,
           "rendering": 55, "delivery": 95}


class ActiveClaim:
    """Keep the lease alive during blocking HTTP, encode and decode.

    The synchronous calls also check the fence at side-effect boundaries.
    """

    def __init__(self, claim, *, progress=None):
        self.claim = claim
        self.touch_progress = progress or ProgressFile()
        self.done, self.cancelled, self.lost = Event(), Event(), Event()
        self.thread = Thread(target=self._maintain, name="studio-worker-heartbeat")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.done.set()
        self.thread.join()

    def _maintain(self):
        while not self.done.wait(HEARTBEAT_SECONDS):
            try:
                self._beat()
            except WorkerAPIError as error:
                if error.status in (401, 403, 404, 409):
                    self.lost.set()
                    return
                # A transient HTTP failure does not extend the DB lease; the
                # next synchronous check or the DB clock will enforce expiry.

    def _beat(self, progress=None):
        answer = self.claim.heartbeat(progress)
        if answer["cancel_requested"]:
            self.cancelled.set()

    def progress(self, stage, *, drain=False):
        self.touch_progress()
        if self.lost.is_set():
            raise WorkerAPIError("work.fence_lost", 409)
        self._beat({"percent": PERCENT[stage], "stage": stage})
        if self.cancelled.is_set() and not drain:
            raise BuildCancelled()
        return self.cancelled.is_set()

    def before_delivery(self):
        self.progress("delivery")
        self.claim.publish()


class BuildWorker:
    """Drive the existing build from its frozen claim, with no DB connection."""

    def __init__(self, api, wan, *, store, stage_root, register, tracker_story, transcriber,
                 studio="git:unknown", image_digest=None, clock=monotonic, pause=sleep,
                 progress=None):
        self.api, self.wan, self.store, self.register = api, wan, store, register
        self.stage_root = stage_root
        self.tracker_story, self.transcriber = tracker_story, transcriber
        self.studio, self.image_digest = studio, image_digest
        self.clock, self.pause = clock, pause
        self.progress = progress or ProgressFile()

    def _inputs(self, claim):
        run = claim.body["run"]
        frozen = claim.body["snapshot"]
        _, digest = snapshot_bytes(frozen)
        if (digest != run["snapshot"]["sha256"] or self.store.verify(run["snapshot"]["locator"], digest) != PRESENT):
            raise BuildError("run.snapshot_changed", "The stored run snapshot does not match its pin",
                             stage="prebuild")
        if frozen["toolchain_request"]["studio"] != self.studio:
            raise BuildError("work.revision_mismatch",
                             "The Studio toolchain changed. Queue a new run to capture the current revision.",
                             stage="prebuild")
        library = Library.from_version_documents(claim.body["library"])
        story = frozen["story"]
        format_version = frozen.get("format_version")
        prepared = prepare_queue(story, library, format_version=format_version)
        prepared.ensure_buildable()
        verified, _ = freeze(prepared, studio=self.studio)
        if snapshot_bytes(verified)[1] != digest:
            raise BuildError("run.snapshot_changed", "The frozen assets no longer match the snapshot",
                             stage="prebuild")
        return BuildInputs(story, library, self.register, studio=self.studio,
                           image_digest=self.image_digest, format_version=format_version)

    def _render(self, claim, active, clips, inputs):
        s2v, i2v = WanS2VSource(clips), WanChainSource(clips)
        sources = ClipSources(s2v, i2v, check=lambda request: check_request(request, self.tracker_story),
                              stopped=lambda: clips.stopped, bind=i2v.bind)
        run = {key: value for key, value in claim.body["run"].items()
               if key not in ("revision", "cancel_requested", "estimate_methods")}
        earlier_runs = claim.body.get("earlier_runs", ())
        staging = BuildStageStore(self.stage_root, run["id"], self.store, create=True,
                                  earlier_runs=earlier_runs)
        return build_story(
            inputs, store=staging, phase=ALL, sources=sources,
            transcriber=self.transcriber, actor=claim.body["actor"],
            earlier_runs=earlier_runs, queued=QueuedBuild(run, active.before_delivery, self.progress),
        ).run

    def tick(self):
        self.progress()
        claim = self.api.claim()
        if claim is None:
            return False
        with ActiveClaim(claim, progress=self.progress) as active:
            clips = ProductClips(claim, self.wan, story=self.tracker_story,
                                 progress=active.progress, clock=self.clock, pause=self.pause)
            try:
                clips.reconcile()
                active.progress("preflight")
                inputs = self._inputs(claim)
                self.wan.ready()
                claim.resume()
                result = self._render(claim, active, clips, inputs)
            except LanePaused as error:
                self._pause(claim, error)
                return True
            except BuildCancelled as error:
                claim.fail(status="cancelled", reason="Cancelled after reconciling Wan work",
                           wan_job_id=error.job_id)
                return True
            except AttemptFailed as error:
                failure = failure_of(error.error)
                claim.fail(status="failed", reason=failure.message[:500], error=failure.to_document(),
                           wan_job_id=error.job_id)
                return True
            except (WorkerAPIError, OSError):
                # Ownership or the reply is ambiguous. Relinquish by expiry;
                # the next claimant reads any durable external ID first.
                raise
            except Exception as error:
                failure = failure_of(error, stage="prebuild")
                claim.fail(status="failed", reason=failure.message[:500], error=failure.to_document())
                return True

            if clips.stopped is not None:
                self._pause(claim, clips.stopped, evidence=result)
            elif active.cancelled.is_set():
                claim.fail(status="cancelled", reason="Cancelled after reconciling Wan work")
            elif result["status"] == "succeeded":
                self._complete(claim, result)
            else:
                error = result["error"]
                claim.fail(status="failed", reason=error["message"][:500], error=error,
                           stages=result["stages"], checks=result["checks"])
        return True

    @staticmethod
    def _complete(claim, result):
        evidence = {key: result[key] for key in ("stages", "outputs", "checks", "provenance", "delivery_id")}
        try:
            claim.complete(evidence)
        except WorkerAPIError as error:
            # These replies came from the API before committing success. A
            # lost reply or a database outage still leaves an ambiguous result.
            if error.status not in (413, 422) and error.code != "work.delivery_unverified":
                raise
            message = "Studio API refused the staged delivery"
            claim.fail(status="failed", reason=message, error={
                "code": "work.delivery_rejected", "message": message,
                "board_id": None, "stage": "delivery",
            })

    @staticmethod
    def _pause(claim, error, evidence=None):
        status = "queued" if error.wait_reason else "held"
        fields = {} if evidence is None else {key: evidence[key] for key in ("stages", "checks")}
        failure = (evidence or {}).get("error") or failure_of(error, stage="wan").to_document()
        claim.fail(status=status, reason=error.message[:500], wait_reason=error.wait_reason,
                   error=failure, admission_busy=error.admission_busy, **fields)


def _serve(worker, once):
    progress = worker.progress
    while True:
        progress()
        try:
            did_work = worker.tick()
        except WorkerAPIError as error:
            logger.warning("Studio worker request failed (%s)", error.code)
            if once or error.status in (401, 403):
                raise SystemExit(1) from None
            did_work = False
        except OSError as error:
            logger.warning("Studio worker store is unavailable (%s)", type(error).__name__)
            if once:
                raise SystemExit(1) from None
            did_work = False
        progress()
        if once:
            return
        if not did_work:
            sleep(IDLE_SECONDS)


def _media_main(options, parser, progress):
    from haynes_studio.adapters.errors import AdapterError
    from haynes_studio.adapters.matting import MattingClient
    from haynes_studio.library.winter_menu import load_licence_register
    from haynes_studio.matting.profile import MatteError, Profile

    from .media_services import ComfyHTTP, WyomingKokoro
    from .media_worker import MediaWorker

    with ExitStack() as resources:
        try:
            origin = service_url(os.environ["STUDIO_API_URL"])
            token = worker_bearer(os.environ["STUDIO_WORKER_TOKEN"])
            store = LocalStore(os.environ["STUDIO_STORE_ROOT"])
            register = None if options.lane == "matte" else load_licence_register()
            if options.lane == "matte":
                client = MattingClient(Profile.installed(), os.environ["STUDIO_MATTING_PROFILE_SHA256"])
            elif options.lane == "image":
                url = service_url(os.environ["STUDIO_COMFYUI_URL"])
                image_http = resources.enter_context(httpx.Client(base_url=url, trust_env=False, timeout=60))
                client = ComfyHTTP(image_http, progress=progress)
            else:
                port = int(os.getenv("STUDIO_TTS_PORT", "10210"))
                if not 1 <= port <= 65535:
                    raise ValueError("Invalid port")
                client = WyomingKokoro(os.environ["STUDIO_TTS_HOST"], port)
        except KeyError as error:
            parser.error(f"{error.args[0]} is required")
        except (AdapterError, MatteError) as error:
            parser.error(f"Worker matting configuration is invalid ({error.code})")
        except (OSError, ValueError) as error:
            parser.error(f"Worker configuration is invalid ({type(error).__name__})")
        api = resources.enter_context(httpx.Client(base_url=origin, trust_env=False, timeout=15,
                                                   headers={"Authorization": f"Bearer {token}"}))
        _serve(MediaWorker(WorkerAPI(api), lane=options.lane, store=store, client=client,
                           licences=register, progress=progress), options.once)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("run", "image", "voice", "matte"), default="run")
    parser.add_argument("--once", action="store_true", help="Process at most one claim and exit")
    parser.add_argument("--progress-file", default=os.getenv("STUDIO_WORKER_PROGRESS_FILE"),
                        help="Main-thread progress marker (or STUDIO_WORKER_PROGRESS_FILE)")
    parser.add_argument("--check-progress", type=float, metavar="SECONDS",
                        help="Exit zero if the progress file is at most SECONDS old, otherwise nonzero")
    options = parser.parse_args()
    progress = ProgressFile(options.progress_file)
    if options.check_progress is not None:
        raise SystemExit(0 if progress.fresh(options.check_progress) else 1)
    logging.basicConfig(level=logging.INFO)
    if options.lane != "run":
        _media_main(options, parser, progress)
        return

    try:
        studio_url = service_url(os.environ["STUDIO_API_URL"])
        wan_url = service_url(os.environ["STUDIO_WAN_URL"])
        tracker_story = os.environ["STUDIO_WAN_STORY_URL"]
        if not re.fullmatch(STORY_PATTERN, tracker_story):
            raise ValueError("STUDIO_WAN_STORY_URL must be a full work package URL")
        register = load_model_register()
        store = LocalStore(os.environ["STUDIO_STORE_ROOT"])
        stage_root = Path(os.environ["STUDIO_BUILD_STAGE_ROOT"])
        if not stage_root.is_dir() or stage_root.resolve() == Path(store.root).resolve():
            raise ValueError("STUDIO_BUILD_STAGE_ROOT must be a separate existing directory")
        token = worker_bearer(os.environ["STUDIO_WORKER_TOKEN"])
        transcriber = WyomingTranscriber(os.environ["STUDIO_ASR_HOST"], int(os.getenv("STUDIO_ASR_PORT", "10300")))
    except KeyError as error:
        parser.error(f"{error.args[0]} is required")
    except (OSError, ValueError) as error:
        parser.error(f"Worker configuration is invalid ({type(error).__name__})")

    with ExitStack() as resources:
        api = resources.enter_context(httpx.Client(base_url=studio_url, trust_env=False,
                                                   headers={"Authorization": f"Bearer {token}"}, timeout=15))
        wan = resources.enter_context(httpx.Client(base_url=wan_url, trust_env=False, timeout=20))
        worker = BuildWorker(WorkerAPI(api), ProductWan(wan), store=store, stage_root=stage_root,
                             register=register,
                             tracker_story=tracker_story, transcriber=transcriber,
                             studio=os.getenv("STUDIO_BUILD_REVISION", "git:unknown"),
                             image_digest=os.getenv("STUDIO_BUILD_IMAGE_DIGEST"), progress=progress)
        _serve(worker, options.once)

if __name__ == "__main__":
    main()
