"""Admit one person-selected target and commit a verified result under its claim."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from haynes_studio.assets.occlusion import (
    JSON, PNG, VerifiedObservation, make_request, read_source, verify_stored_observation,
)
from haynes_studio.db import catalog, jobs
from haynes_studio.db.problems import NotFound
from haynes_studio.db.runs import database_time, timestamp
from haynes_studio.jsonio import parse_strict
from haynes_studio.library import Content, Licence, Scope, VersionRequest, import_version
from haynes_studio.library.model import PROMOTED, signature
from haynes_studio.queue.occlusion_inputs import checked_occlusion, occlusion_signature
from haynes_studio.segmentation.profile import PROFILE_ID, SegmentationError
from haynes_studio.store import BLOB_MISSING, LIBRARY, Blob, StoreError
from haynes_studio.store.layout import blob_locator
from haynes_studio.voice.jobs import fail, new_job, succeed

from .errors import APIError
from .media_completion import invalid_result
from .models import Body
from .routes import _id

Coordinate = Annotated[int, Field(ge=0, le=1920)]
TargetText = Annotated[str, StringConstraints(min_length=1, max_length=80)]


class PointHint(Body):
    kind: Literal["point"]
    xy: Annotated[list[Coordinate], Field(min_length=2, max_length=2)]


class BoxHint(Body):
    kind: Literal["box"]
    xyxy: Annotated[list[Coordinate], Field(min_length=4, max_length=4)]


class TextHint(Body):
    kind: Literal["text"]
    text: TargetText


class OcclusionRequest(Body):
    source_version_id: str
    kind: Literal["foreground", "prop", "face"]
    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    label: TargetText | None = None
    hint: Annotated[PointHint | BoxHint | TextHint, Field(discriminator="kind")] | None = None


def _target(conn, source_id, body):
    library = catalog.version_library(conn, version_id=source_id)
    anchor = library.get(source_id)
    if anchor is None:
        raise NotFound
    scope = library.asset_of(source_id).scope
    if scope.story_id is not None or scope.board_id is not None:
        raise NotFound
    label = body.label
    hint = body.hint.model_dump() if body.hint is not None else None
    focal = (anchor.occlusion or {}).get("focal_props", ())
    if body.kind == "prop":
        declaration = next((target for target in focal if target["key"] == body.key), None)
        if declaration is not None:
            if label is not None or hint is not None:
                raise APIError(422, "occlusion.declared_target", "Use the focal prop's stored label and hint")
            label, hint = declaration["label"], declaration.get("hint")
            if declaration["depth"] == "separate":
                source_id = declaration["source_asset_version_id"]
                library = catalog.version_library(conn, version_id=source_id)
                if library.get(source_id) is None:
                    raise NotFound
    return library, source_id, scope.production_id, label, hint, anchor.id if anchor.kind == "set" else None


def enqueue_occlusion(state, actor, body, key):
    actor.human()
    anchor_id = _id(body.source_version_id, "asv", "/source_version_id")
    fingerprint = signature(body.model_dump())
    with state.engine.begin() as conn:
        position = jobs.lock_lane(conn, "occlusion")
        existing = jobs.lookup(conn, "occlusion", "asset-jobs", actor.principal, key, fingerprint)
        if existing is not None:
            return existing, False
        if state.segmentation is None or position is None:
            raise APIError(503, "occlusion.unavailable", "Occlusion admission is disabled")
        library, source_id, production, label, hint, set_id = _target(conn, anchor_id, body)
        separate_prop = set_id is not None and source_id != set_id
        try:
            source, _, _ = read_source(library, source_id, production, body.kind, state.store,
                                       separate_prop=separate_prop)
            request = make_request(source, kind=body.kind, key=body.key, label=label, hint=hint)
        except SegmentationError as error:
            if error.reason == "input_unavailable":
                raise NotFound from error
            raise APIError(422, "occlusion.invalid_input",
                           "Choose a supported still and a target within its bounds") from error
        except (OSError, StoreError) as error:
            raise APIError(503, "occlusion.store_unavailable", "The pinned still could not be read") from error
        frozen = {"source": library.document(source_id), "set_version_id": set_id,
                  "production_id": production, "request": request,
                  "profile": parse_strict(state.segmentation.manifest().decode("utf-8"))}
        job = new_job("occlusion", anchor_id, occlusion_signature(frozen), by=actor.principal,
                      now=timestamp(database_time(conn)))
        return jobs.enqueue(conn, job, position=position, production=production, inputs=frozen,
                            key=key, signature=fingerprint), True


def _blob(descriptor, scope, media_type):
    return Blob(descriptor.sha256, descriptor.bytes, media_type, blob_locator(scope, descriptor.sha256, media_type))


def complete_occlusion(conn, store, row, job, evidence, now):
    production = row["production_id"]
    frozen = row["inputs"]
    library, request, profile = checked_occlusion(job, frozen, production)
    scope = production or LIBRARY
    receipt = _blob(evidence.receipt, scope, JSON)
    mask = _blob(evidence.mask, scope, PNG) if evidence.mask is not None else None
    try:
        observation = verify_stored_observation(
            store, library=library, source_version_id=frozen["source"]["id"], production_id=production,
            request=request, profile=profile, receipt=receipt, mask=mask,
        )
    except SegmentationError as error:
        raise invalid_result() from error
    except StoreError as error:
        if error.code == BLOB_MISSING:
            raise invalid_result() from error
        raise
    completion = observation.completion
    if not isinstance(observation, VerifiedObservation):
        message = ("The target needs a clearer hint" if completion.status == "needs_hint"
                   else "Segmentation refused the target")
        return fail(job, f"occlusion.{completion.reason}", message, now=now, diagnostic={
            "status": completion.status, "receipt_sha256": receipt.sha256,
        })
    source = library.version(completion.identity.source_version_id)
    width, height = (request["input"][axis] for axis in ("width", "height"))
    outcome = import_version(
        library, VersionRequest(
            kind=source.kind, name=f"Mask: {request['target']['key']}", scope=Scope(production),
            capabilities=("mask",), content=Content(mask.sha256, mask.bytes, PNG, mask.locator, width, height),
            provenance={"origin": "derived", "external": None, "source_key": f"occlusion:{job.id}",
                        "generator": {"role": "image", "engine": "segmentation", "model": PROFILE_ID,
                                      "source_asset_version_ids": [source.id]}},
            licence=Licence.unknown("Derived from a stored still using the pinned segmentation profile"),
            state=PROMOTED, segmentation={
                "source_version_id": source.id, "still_sha256": request["input"]["sha256"],
                "request_sha256": completion.identity.request_sha256,
                "profile_sha256": completion.identity.profile_sha256,
                "receipt_sha256": receipt.sha256,
            },
        ), by=job.created_by, now=now,
    )
    catalog.record_asset_version(conn, outcome.library.document(outcome.version.id))
    return succeed(job, outcome.version.id, is_current=False, now=now)
