"""Commit a worker-verified matte only under its claim and frozen source pin."""

from hashlib import sha256

from haynes_studio.assets.matte import JSON, matte_identity, matte_kind, matte_outputs
from haynes_studio.canonical.model import to_document
from haynes_studio.db import catalog
from haynes_studio.errors import blocking
from haynes_studio.layered.matte_size import ENGINE
from haynes_studio.library import AssetVersion, Content, validate_asset_version
from haynes_studio.library.model import CANDIDATE, PROMOTED, locator_for
from haynes_studio.matting.backend import RESULT_SCHEMA, input_signature
from haynes_studio.queue.media_inputs import checked_matte
from haynes_studio.schemas import validator_for
from haynes_studio.store import PRESENT, canonical_json

from .media_completion import invalid_result


def _descriptors(receipt, production):
    for name in ("cutout", "mask"):
        descriptor = receipt["artifacts"][name]
        yield Content(**descriptor, locator=locator_for(descriptor["sha256"], descriptor["media_type"], production))
    data = canonical_json(receipt)
    digest = sha256(data).hexdigest()
    yield Content(digest, len(data), JSON, locator_for(digest, JSON, production))


def _receipt(document, source, target):
    generator = document["provenance"]["generator"]
    if generator["engine"] != ENGINE or generator["source_asset_version_ids"] != [source["id"]]:
        raise invalid_result()
    params = generator["params"]
    receipt = params["receipt"]
    if not validator_for(RESULT_SCHEMA).is_valid(receipt):
        raise invalid_result()
    pinned = source["content"]
    observed = receipt["source"]
    request = {key: receipt[key] for key in ("job_id", "source", "profile_id", "profile_sha256", "parameters")}
    if (observed["asset_version_id"] != source["id"]
            or observed["production_id"] != source["scope"]["production_id"]
            or any(pinned.get(key) not in (None, observed[key])
                   for key in ("sha256", "media_type", "bytes", "width", "height"))
            or receipt["parameters"] != {"chroma_rgb": None, "target_height_px": target.height}
            or params["normalization"] != target.document()
            or params["profile_sha256"] != receipt["profile_sha256"]
            or params["image_digest"] != receipt["provenance"]["image_digest"]
            or params["input_signature"] != receipt["input_signature"]
            or generator["model"] != receipt["profile_id"]
            or generator["files_sha256"] != receipt["provenance"]["files_sha256"]
            or input_signature({"schema": "studio.matte-request/v1", **request}) != receipt["input_signature"]):
        raise invalid_result()
    return receipt


def complete_matte(conn, store, row, job, document):
    source = row["inputs"]["source"]
    target = checked_matte(job, row["inputs"])
    if (blocking(validate_asset_version(document)) or document["scope"] != source["scope"]
            or document["scope"]["production_id"] != row["production_id"]
            or document["kind"] != matte_kind(source["kind"])
            or document["number"] != 1 or set(document["capabilities"]) != {"rgba_cutout", "mask"}):
        raise invalid_result()
    version = AssetVersion.from_document(document)
    try:
        receipt = _receipt(document, source, target)
        descriptors = tuple(_descriptors(receipt, row["production_id"]))
        if ((version.source_key, version.asset_id, version.id) != matte_identity(receipt, target)
                or version.origin != "derived" or matte_outputs(version) != descriptors):
            raise invalid_result()
    except (KeyError, TypeError, ValueError) as error:
        raise invalid_result() from error

    library = catalog.version_library(conn, version_id=version.id)
    existing = library.get(version.id)
    if existing is None:
        if (version.state != CANDIDATE or receipt["job_id"] != job.id
                or document["provenance"]["created_by"] != to_document(job.created_by)
                or any(document[field] != source[field] for field in ("name", "labels", "attributes"))):
            raise invalid_result()
    elif existing.state not in (CANDIDATE, PROMOTED) or version.with_state(existing.state) != existing:
        raise invalid_result()
    if any(store.verify(item.locator, item.sha256) != PRESENT for item in descriptors):
        raise invalid_result()
    if existing is None:
        catalog.record_asset_version(conn, document)
    return version.id
