"""Drive media claims using the Studio API and caller-configured service clients."""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from haynes_studio.adapters.errors import COMMAND_FAILED, TIMEOUT, AdapterError
from haynes_studio.adapters.matting import MattingUnavailable
from haynes_studio.assets.candidate import generate_candidate
from haynes_studio.assets.matte import matte_outputs, run_matte_job
from haynes_studio.canonical.model import to_document
from haynes_studio.errors import ContractError, blocking
from haynes_studio.layered.errors import LayeredError
from haynes_studio.library import Library
from haynes_studio.library.model import version_document
from haynes_studio.photo.build import compose_layered_photo, generate_photo
from haynes_studio.photo.validation import PNG
from haynes_studio.store import BLOB_MISSING, LIBRARY, LocalStore, StoreError
from haynes_studio.voice import Job, make_voice, validate_job

from .media_inputs import checked_candidate, checked_matte, checked_photo
from .progress import ProgressFile
from .protocol import MEDIA_LANES
from .worker_api import WorkerAPIError

IMAGE_WAIT_SECONDS = 30 * 60
logger = logging.getLogger(__name__)


class ImageQueueBusy(Exception):
    """The last queue read found work before the prompt was submitted."""


class Dispatch:
    """Mark the first non-idempotent call and recheck the lease at each call."""

    def __init__(self, active):
        self.active = active
        self.started = False

    def _check(self):
        self.active.touch_progress()
        if self.active.lost.is_set():
            raise WorkerAPIError("work.fence_lost", 409)

    def check(self):
        self._check()
        self.active.claim.heartbeat()

    def __call__(self):
        self._check()
        if self.started:
            self.active.claim.heartbeat()
        else:
            self.active.claim.publish()
            self.started = True


class ImageLane:
    def __init__(self, client, dispatch, *, clock, pause):
        self.client, self.dispatch = client, dispatch
        self.clock, self.pause = clock, pause

    def render(self, request):
        started = self.clock()
        while self.clock() - started < IMAGE_WAIT_SECONDS:
            self.dispatch.active.touch_progress()
            if self.dispatch.active.lost.is_set():
                raise WorkerAPIError("work.fence_lost", 409)
            if self.client.queue().idle:
                try:
                    waited = self.clock() - started
                    result = self.client.render(request, before_submit=self.dispatch)
                    return replace(result, waited_s=round(result.waited_s + waited, 1))
                except ImageQueueBusy:
                    pass
            self.pause(10)
        raise AdapterError("adapter.busy", "comfyui", "The shared image queue stayed busy")


class SpeechLane:
    def __init__(self, client, dispatch):
        self.client, self.dispatch = client, dispatch

    def synthesize(self, request):
        self.dispatch()
        return self.client.synthesize(request)


class MediaWorker:
    def __init__(self, api, *, lane, store, client, licences=None, clock=monotonic, pause=sleep,
                 progress=None):
        if lane not in MEDIA_LANES:
            raise ValueError("Expected an image, voice or matte lane")
        self.api, self.lane, self.store, self.client = api, lane, store, client
        self.licences, self.clock, self.pause = licences, clock, pause
        self.progress = progress or ProgressFile()

    def _fetch(self, locator, digest):
        self.progress()
        try:
            with self.store.open(locator) as handle:
                data = handle.read(64 * 1024 * 1024 + 1)
        except StoreError as error:
            if error.code == BLOB_MISSING:
                return None
            raise
        if len(data) > 64 * 1024 * 1024 or sha256(data).hexdigest() != digest:
            return None
        return data

    def _voice(self, job, claim, dispatch, production):
        library = Library.from_version_documents(claim.body["library"])

        def publish(data, media_type):
            self.progress()
            blob = self.store.publish(data, scope=production, media_type=media_type)
            return blob.sha256, blob.locator

        result = make_voice(
            job.voice, job.target_id, library, speech=SpeechLane(self.client, dispatch),
            fetch=self._fetch, publish=publish, by=job.created_by,
            now=datetime.now(UTC).isoformat().replace("+00:00", "Z"), licences=self.licences,
        )
        return {"version": version_document(result.version, result.library.asset_of(result.version.id))}

    def _matte(self, job, claim, dispatch, frozen, production):
        target = checked_matte(job, frozen)
        library = Library.from_version_documents(claim.body["library"])

        def record_failure(*, code, message):
            if code == TIMEOUT:
                message = "Matting timed out. Scratch may remain until the next sweep."
            claim.fail(code=code, message=message)

        try:
            with TemporaryDirectory(prefix=f"studio-{job.id}-", dir=self.client.scratch) as scratch:
                stage = LocalStore(scratch)
                result = run_matte_job(
                    library, source_version_id=job.target_id, job_id=job.id, production_id=production,
                    format_version=frozen["format_version"], slot=target.slot, by=job.created_by,
                    now=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    store=self.store, client=self.client, output_store=stage, check_fence=dispatch.check,
                    before_dispatch=dispatch,
                    record_failure=record_failure,
                )
                if result is None:
                    return None
                # A reused result can reach publication without a sidecar request.
                dispatch()
                # A replay can restore missing files even though it returns
                # the existing candidate. Copy every staged artifact.
                for item in matte_outputs(result.version):
                    try:
                        staged = stage.open(item.locator)
                    except StoreError as error:
                        if error.code != BLOB_MISSING:
                            raise
                        continue
                    with staged:
                        dispatch()
                        self.store.publish(staged, scope=production or LIBRARY, media_type=item.media_type,
                                           expected_sha256=item.sha256)
        except MattingUnavailable as error:
            if not dispatch.started:
                raise
            record_failure(code=error.code, message=error.message)
            return None
        except OSError as error:
            raise AdapterError(COMMAND_FAILED, "matting", "The matte staging store is unavailable") from error
        return {"matte_version": version_document(result.version, result.library.asset_of(result.version.id))}

    def _result(self, job, claim, dispatch):
        self.progress()
        frozen = claim.body["inputs"]
        production = claim.body["production_id"]
        if job.kind == "voice":
            return self._voice(job, claim, dispatch, production)
        if job.kind == "matte":
            return self._matte(job, claim, dispatch, frozen, production)
        image = ImageLane(self.client, dispatch, clock=self.clock, pause=self.pause)
        if job.kind == "photo":
            plan = checked_photo(job, frozen)
            if plan.layers is None:
                prepared = generate_photo(plan, client=image, fetch=self._fetch, seed=frozen["seed"],
                                          job=job.id.lower().replace("_", "-"), licences=self.licences)
            else:
                dispatch()
                prepared = compose_layered_photo(plan, fetch=self._fetch)
        else:
            plan = checked_candidate(job, frozen)
            if claim.body["has_result"]:
                return None
            prepared = generate_candidate(plan, client=image, licences=self.licences)
        self.progress()
        blob = self.store.publish(prepared.image.png, scope=production or LIBRARY, media_type=PNG)
        return {"sha256": blob.sha256, "generator": to_document(prepared.generator),
                "licence": to_document(prepared.licence)}

    def _matte_wait(self, error):
        message = f"Waiting for the matting sidecar ({error.code})"
        self.progress.write_status(message)
        logger.warning("%s", message)

    def tick(self):
        from .worker import ActiveClaim

        self.progress()
        if self.lane == "matte":
            try:
                self.client.ready_for_claim()
            except AdapterError as error:
                self._matte_wait(error)
                return False
            self.progress.write_status("Matting sidecar ready")
        claim = self.api.claim(self.lane)
        if claim is None:
            return False
        with ActiveClaim(claim, progress=self.progress) as active:
            try:
                doc = claim.body["job"]
                violations = blocking(validate_job(doc))
                if violations:
                    raise ContractError(doc["id"], violations)
                job = Job.from_document(doc)
                evidence = self._result(job, claim, Dispatch(active))
                self.progress()
            except MattingUnavailable as error:
                claim.release()
                self._matte_wait(error)
                return False
            except WorkerAPIError:
                raise
            except ContractError as error:
                failure = error.violations[0]
                claim.fail(code=failure.rule, message=failure.message[:500])
            except (AdapterError, LayeredError, StoreError) as error:
                # Keep machine provenance and avoid persisting service logs or raw inputs.
                claim.fail(code=error.code, message="A media dependency could not finish this job")
            except Exception:
                claim.fail(code="work.media_failed", message="The worker could not prepare the media result")
            else:
                if job.kind == "matte" and evidence is None:  # The adapter already recorded the failure.
                    return True
                try:
                    claim.complete({"result": evidence})
                except WorkerAPIError as error:
                    if error.status not in (413, 422) and error.code != "work.result_store_unavailable":
                        raise
                    claim.fail(code="work.result_rejected", message="The API could not verify the media result")
        return True
