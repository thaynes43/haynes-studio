"""Handle media claims through the existing worker routes."""

from haynes_studio.assets.candidate import candidate_result
from haynes_studio.db import catalog, jobs
from haynes_studio.db.runs import timestamp
from haynes_studio.library import Library
from haynes_studio.queue.media_inputs import checked_candidate, documents
from haynes_studio.queue.protocol import MEDIA_LANES, ImageEvidence, MatteEvidence, VoiceEvidence
from haynes_studio.store import StoreError
from haynes_studio.voice.jobs import fail, succeed
from haynes_studio.voice.model import Job

from .auth import require_worker_lane
from .errors import APIError
from .matte_completion import complete_matte
from .media_completion import complete_candidate, complete_photo, complete_voice, invalid_result
from .routes import _id


def claim(conn, worker_id, lane, *, settle_while_paused=False):
    row = jobs.claim(conn, worker_id, lane, settle_while_paused=settle_while_paused)
    if row is None:
        return None
    body = {"job": jobs.job_document(row), "inputs": row["inputs"], "fence": row["fence"],
            "claim_until": row["claim_until"], "production_id": row["production_id"]}
    if row["kind"] == "voice":
        library = catalog.board_library(conn, Library(), row["board_id"], "board_voice")
        body["library"] = documents(library)
    elif row["kind"] == "asset_candidate":
        plan = checked_candidate(Job.from_document(body["job"]), row["inputs"])
        library = catalog.version_library(conn, asset_id=plan.asset_id, source_key=plan.source_key)
        body["has_result"] = candidate_result(library, plan) is not None
    elif row["kind"] == "matte":
        prior = jobs.prior_matte_versions(conn, body["job"]["input_signature"])
        library = catalog.version_library(conn, version_ids=prior)
        body["library"] = [row["inputs"]["source"], *documents(library)]
    return body


def lock(conn, request, body):
    lane = require_worker_lane(request, *MEDIA_LANES)
    return jobs.lock_claim(conn, _id(body.job_id, "job", "/job_id"),
                           request.state.principal.worker_id, body.fence, lane=lane)


def complete(conn, request, body):
    row, now = lock(conn, request, body)
    job = Job.from_document(jobs.job_document(row))
    store = request.app.state.store
    now = timestamp(now)
    try:
        if job.kind == "voice" and isinstance(body.result, VoiceEvidence):
            version_id, selected = complete_voice(conn, store, row, job, body.result)
        elif job.kind == "photo" and isinstance(body.result, ImageEvidence):
            if not row["dispatched"]:
                raise invalid_result()
            version_id, selected = complete_photo(conn, store, row, job, body.result, now)
        elif job.kind == "asset_candidate" and (isinstance(body.result, ImageEvidence) or body.result is None):
            if body.result is not None and not row["dispatched"]:
                raise invalid_result()
            version_id, selected = complete_candidate(conn, store, row, job, body.result, now)
        elif job.kind == "matte" and isinstance(body.result, MatteEvidence) and row["dispatched"]:
            version_id = complete_matte(conn, store, row, job, body.result.matte_version)
            selected = False
        else:
            raise invalid_result()
    except (StoreError, OSError) as error:
        raise APIError(503, "work.result_store_unavailable", "The result could not be read from the store") from error
    return jobs.finish(conn, row, succeed(job, version_id, is_current=selected, now=now))


def finish_failure(conn, request, body):
    row, now = lock(conn, request, body)
    job = Job.from_document(jobs.job_document(row))
    return jobs.finish(conn, row, fail(job, body.code, body.message, now=timestamp(now)))
