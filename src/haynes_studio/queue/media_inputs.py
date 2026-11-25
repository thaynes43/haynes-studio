"""Frozen operation inputs shared by the API and the media worker."""

from haynes_studio.adapters.comfyui import TextToImage
from haynes_studio.assets.candidate import plan_candidate
from haynes_studio.canonical.model import Story
from haynes_studio.errors import ContractError, Violation
from haynes_studio.library import Library
from haynes_studio.library.model import signature, version_document
from haynes_studio.photo.build import MODEL
from haynes_studio.photo.plan import WHOLE_FRAME, plan_photo


def documents(library):
    return [version_document(version, library.asset_of(version.id))
            for version in library.versions.values()]


def photo_plan(story, board_id, library):
    model = Story.from_document(story)
    board = next(board for board in model.boards if board.id == board_id)
    return plan_photo(model, board, library)


def photo_request(plan, seed):
    if plan.layer == WHOLE_FRAME:
        # Validate against the same pinned client request as generation.
        TextToImage(job="validate", name="board-photo", prompt=plan.prompt or "", seed=seed,
                    width=plan.size[0] * 2 // 3, height=plan.size[1] * 2 // 3)
    return signature({
        "schema": "studio.photo-job-inputs/v1", "photo_signature": plan.input_signature,
        "seed": seed if plan.layer == WHOLE_FRAME else None,
        "model": MODEL if plan.layer == WHOLE_FRAME else None,
        "selected_version_id": plan.selected_version_id,
    })


def checked_photo(job, frozen):
    plan = photo_plan(frozen["story"], job.target_id, Library.from_version_documents(frozen["library"]))
    if photo_request(plan, frozen["seed"]) != job.input_signature:
        raise ContractError(job.id, [Violation("job.input_changed", "", "The frozen photo inputs changed")])
    return plan


def checked_candidate(job, frozen):
    plan = plan_candidate(job_id=job.id, asset_id=job.target_id, by=job.created_by, **frozen)
    if plan.input_signature != job.input_signature:
        raise ContractError(job.id, [Violation("job.input_changed", "", "The frozen candidate inputs changed")])
    return plan


def provenance(document, frozen):
    """Expose the job inputs people and agents need to diagnose stale or failed work."""
    from haynes_studio.voice.model import Job

    if document["kind"] == "voice":
        return {}
    job = Job.from_document(document)
    if job.kind == "photo":
        plan = checked_photo(job, frozen)
        return {"photo": {
            "production_id": plan.scope.production_id, "story_id": plan.scope.story_id,
            "layer": plan.layer, "prompt": plan.prompt, "source_assets": [source.pin() for source in plan.sources],
            "selected_version_id": plan.selected_version_id, "photo_input_signature": plan.input_signature,
            "seed": frozen["seed"] if plan.layer == WHOLE_FRAME else None,
            "model": MODEL if plan.layer == WHOLE_FRAME else None,
        }}
    plan = checked_candidate(job, frozen)
    return {"asset_candidate": {
        **frozen, "model": MODEL, "request_size": [plan.request.width, plan.request.height],
    }}
