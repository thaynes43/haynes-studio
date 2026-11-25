"""Fenced result registration and draft selection for media jobs."""

from haynes_studio.assets.candidate import PreparedCandidate, candidate_result, record_candidate
from haynes_studio.canonical.model import Story, to_document
from haynes_studio.db import catalog, drafts
from haynes_studio.errors import blocking
from haynes_studio.library import Library, validate_asset_version
from haynes_studio.library.library import require_media
from haynes_studio.library.model import BOARD, AssetVersion, Licence, version_document
from haynes_studio.photo.build import PreparedPhoto
from haynes_studio.photo.plan import can_select_photo
from haynes_studio.photo.record import record_photo
from haynes_studio.photo.validation import PNG, PhotoImage, decode, verify_bytes
from haynes_studio.queue.media_inputs import checked_candidate, checked_photo
from haynes_studio.store import LIBRARY, PRESENT, blob_locator
from haynes_studio.voice import is_current
from haynes_studio.voice.plan import has_track, same_input

from .errors import APIError

MAX_STAGED_IMAGE_BYTES = 64 * 1024 * 1024


def publisher(store, production):
    def publish(data, media_type):
        blob = store.publish(data, scope=production, media_type=media_type)
        return blob.sha256, blob.locator
    return publish


def invalid_result():
    return APIError(422, "work.result_invalid", "The result does not match the frozen media job")


def _image_metadata(result, signature):
    params = result.generator.get("params")
    if not isinstance(params, dict) or params.get("input_signature") != signature:
        raise invalid_result()
    try:
        licence = Licence.from_document(result.licence)
    except (KeyError, TypeError, ValueError) as error:
        raise invalid_result() from error
    return result.generator, licence


def _read_image(store, production, digest):
    with store.open(blob_locator(production or LIBRARY, digest, PNG)) as handle:
        data = handle.read(MAX_STAGED_IMAGE_BYTES + 1)
    if len(data) > MAX_STAGED_IMAGE_BYTES:
        raise invalid_result()
    verify_bytes(data, digest, "/result/sha256")
    image = decode(data, PNG, "/result")
    return PhotoImage(data, image.width, image.height)


def record_board_photo(conn, store, draft, prepared, by, now):
    plan = prepared.plan
    board_id = plan.scope.board_id
    board = draft.boards.get(board_id)
    story, model, library = None, None, Library()
    if board is not None:
        story, library = drafts.board_snapshot(conn, draft, board_id)
        model = Story.from_document(story)
    library = catalog.board_library(conn, library, board_id, "photo")
    outcome = record_photo(prepared, library, publish=publisher(store, plan.scope.production_id),
                           by=by, now=now)
    version = outcome.version
    document = version_document(version, outcome.library.asset_of(version.id))
    generator = document["provenance"]["generator"]
    received = generator["params"]["upload_sha256"] if prepared.origin == "uploaded" else None
    catalog.record_asset_version(conn, document, asset=outcome.library.asset_of(version.id),
                                 received_sha256=received)
    selected = can_select_photo(version, plan, model, None if model is None else model.boards[0],
                                outcome.library)
    revision = (drafts.select_board_media(conn, draft, board_id, "photo", version.id, to_document(by))
                if selected else None)
    return document, revision


def complete_voice(conn, store, row, job, result):
    document = result.version
    if blocking(validate_asset_version(document)):
        raise invalid_result()
    if document["scope"] != {
        "production_id": row["production_id"], "story_id": row["story_id"], "board_id": row["board_id"],
    }:
        raise invalid_result()
    version = AssetVersion.from_document(document)
    if version.kind != "board_voice" or version.state != BOARD or not has_track(version) \
            or not same_input(version, job.voice):
        raise invalid_result()
    draft = drafts.get_draft(conn, row["story_id"], lock=True)
    held = catalog.version_library(conn, version_id=version.id)
    if held.get(version.id) is None:
        if version.origin != "generated" or document["provenance"]["created_by"] != to_document(job.created_by):
            raise invalid_result()
    elif version_document(held.get(version.id), held.asset_of(version.id)) != document:
        raise invalid_result()
    require_media(version, "/result/version")
    track = version.voice.track
    if store.verify(track.locator, track.sha256) != PRESENT:
        raise invalid_result()
    for digest in {take.sha256 for take in version.voice.takes}:
        if store.verify(blob_locator(row["production_id"], digest, "audio/wav"), digest) != PRESENT:
            raise invalid_result()
    catalog.record_asset_version(conn, document)
    board = draft.boards.get(row["board_id"])
    selected = False
    if board is not None and board["voice"] is not None:
        story, library = drafts.board_snapshot(conn, draft, board["id"])
        current_id = board["voice"]["current_version_id"]
        selected = (current_id in (version.id, row["inputs"]["selected_version_id"])
                    and is_current(job, story, library))
        if selected:
            selected = drafts.select_board_media(conn, draft, board["id"], "voice", version.id,
                                                 to_document(job.created_by)) is not None
    return version.id, selected


def complete_photo(conn, store, row, job, result, now):
    plan = checked_photo(job, row["inputs"])
    generator, licence = _image_metadata(result, plan.input_signature)
    image = _read_image(store, row["production_id"], result.sha256)
    origin = "derived" if plan.layers is not None else "generated"
    prepared = PreparedPhoto(plan, image, origin, generator, licence)
    draft = drafts.get_draft(conn, row["story_id"], lock=True)
    doc, revision = record_board_photo(conn, store, draft, prepared, job.created_by, now)
    return doc["id"], revision is not None


def complete_candidate(conn, store, row, job, result, now):
    plan = checked_candidate(job, row["inputs"])
    library = catalog.version_library(conn, asset_id=plan.asset_id, source_key=plan.source_key)
    existing = candidate_result(library, plan)
    if result is None:
        if existing is None:
            raise invalid_result()
        return existing.id, False
    generator, licence = _image_metadata(result, plan.input_signature)
    image = _read_image(store, row["production_id"], result.sha256)
    outcome = record_candidate(PreparedCandidate(plan, image, generator, licence),
                               library, store=store, now=now)
    version = outcome.version
    if outcome.created:
        asset = outcome.library.asset_of(version.id)
        catalog.record_asset_version(conn, version_document(version, asset), asset=asset)
    return version.id, False
