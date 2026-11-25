"""Prepare and publish one derived still through an authorized Studio job claim."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from PIL import Image

from haynes_studio.adapters.errors import COMMAND_FAILED, REQUEST_INVALID, AdapterError
from haynes_studio.adapters.matting import MattingClient, failure
from haynes_studio.canonical.ids import is_id, ulid
from haynes_studio.canonical.model import Principal, to_document
from haynes_studio.errors import ContractError
from haynes_studio.formats.recipe import recipe_hash
from haynes_studio.layered.matte_size import ENGINE, SIZE_POLICY, MatteSize
from haynes_studio.library import AssetVersion, Content, Library, Outcome, VersionRequest, import_version
from haynes_studio.library.library import IDEMPOTENCY_MISMATCH, require_media
from haynes_studio.library.model import CANDIDATE, KIND_CAPABILITIES, PROMOTED, locator_for
from haynes_studio.library.winter_menu import LicenceRegister
from haynes_studio.matting.pixels import MAX_SOURCE_BYTES, decode_source
from haynes_studio.matting.profile import PROFILE_ID, MatteError
from haynes_studio.model_register import load_model_register
from haynes_studio.store import (
    COLLISION, HASH_MISMATCH, LIBRARY, MISSING, PRESENT, Blob, Store, StoreError, canonical_json,
)

PNG = "image/png"
JSON = "application/json"


@dataclass(frozen=True)
class MatteTarget:
    format_version_id: str
    format_sha256: str
    slot: str
    height: int

    @classmethod
    def from_recipe(cls, version: Mapping, slot: str) -> "MatteTarget":
        """Select one slot from an immutable, authorized format version."""
        try:
            recipe = version["recipe"]
            height = recipe["cast"]["matte_slots"][slot]["target_height_px"]
            if (is_id(version["id"], "fmv") and recipe_hash(recipe) == version["sha256"]
                    and type(height) is int and 1 <= height <= 2048):
                return cls(version["id"], version["sha256"], slot, height)
        except (KeyError, TypeError, ValueError):
            pass
        raise failure(REQUEST_INVALID, "The pinned format has no valid height for this cast slot")

    def document(self) -> dict:
        return {"policy": SIZE_POLICY, "format_version_id": self.format_version_id,
                "format_sha256": self.format_sha256, "slot": self.slot, "target_height_px": self.height}


def _read_source(store: Store, version: AssetVersion, production_id: str | None) -> tuple[dict, bytes]:
    content = version.content
    formats = {"image/jpeg": "JPEG", PNG: "PNG"}
    if (content.media_type not in formats
            or content.locator != locator_for(content.sha256, content.media_type, production_id)):
        raise failure(REQUEST_INVALID, "The source must be a PNG or JPEG in its pinned library scope")

    with store.open(content.locator) as handle:
        data = handle.read(MAX_SOURCE_BYTES + 1)
    if (not 0 < len(data) <= MAX_SOURCE_BYTES
            or (content.bytes is not None and len(data) != content.bytes)
            or sha256(data).hexdigest() != content.sha256):
        raise failure(REQUEST_INVALID, "The encoded source length or hash differs from its asset pin")
    try:
        with Image.open(BytesIO(data), formats=[formats[content.media_type]]) as header:
            width, height = header.size
        if (not (64 <= width <= 2048 and 64 <= height <= 2048)
                or content.width not in (None, width) or content.height not in (None, height)):
            raise failure(REQUEST_INVALID, "The source dimensions are invalid or differ from its pin")
        source = {"asset_version_id": version.id, "production_id": production_id,
                  "sha256": content.sha256, "bytes": len(data), "media_type": content.media_type,
                  "width": width, "height": height}
        decode_source(data, source).close()
    except (OSError, ValueError, SyntaxError, MatteError, Image.DecompressionBombError, Warning):
        raise failure(REQUEST_INVALID, "The pinned source is not a supported opaque still") from None
    return source, data


def _stable_id(prefix: str, key: str) -> str:
    bits = int.from_bytes(sha256(f"{prefix}:{key}".encode()).digest()[:16])
    return f"{prefix}_{ulid(bits >> 80, bits % (1 << 80))}"


def _existing(library: Library, key: str, asset_id: str, version_id: str) -> AssetVersion | None:
    asset = library.by_source_key(key)
    if asset is None:
        return None
    version = library.get(version_id)
    if (asset.id != asset_id or version is None or version.asset_id != asset_id
            or version.source_key != key or version.state not in (CANDIDATE, PROMOTED)
            or version.origin != "derived" or set(version.capabilities) != {"rgba_cutout", "mask"}):
        raise failure(IDEMPOTENCY_MISMATCH, "This matting input already has a different candidate")
    return version


def _recorded_outputs(version: AssetVersion, store: Store) -> tuple[tuple[Content, ...], tuple[Content, ...]]:
    try:
        params = version.provenance["generator"]["params"]
        outputs = (version.content, Content.from_document(params.get("mask")),
                   Content.from_document(params.get("receipt_blob")))
    except (KeyError, TypeError):
        raise failure(IDEMPOTENCY_MISMATCH, "The recorded matte has an invalid descriptor") from None
    missing = []
    for descriptor in outputs:
        if descriptor is None:
            raise failure(IDEMPOTENCY_MISMATCH, "The recorded matte has an invalid descriptor")
        state = store.verify(descriptor.locator, descriptor.sha256)
        if state == MISSING:
            missing.append(descriptor)
        elif state != PRESENT:
            raise failure(HASH_MISMATCH, "A stored matte artifact differs from its pin")
    return outputs, tuple(missing)


def _publish(store: Store, data: bytes, content: Content, scope: str) -> None:
    blob = store.publish(data, scope=scope, media_type=content.media_type, expected_sha256=content.sha256)
    if blob != Blob(content.sha256, content.bytes, content.media_type, content.locator):
        raise failure(HASH_MISMATCH, "The published matte artifact differs from its verified descriptor")


def _content(data: bytes, media_type: str, production_id: str | None, **size) -> Content:
    digest = sha256(data).hexdigest()
    return Content(digest, len(data), media_type, locator_for(digest, media_type, production_id), **size)


def _make_candidate(
    library: Library, *, source_version_id: str, job_id: str, production_id: str | None,
    format_version: Mapping, slot: str, by: Principal, now: str, store: Store, client: MattingClient,
    check_fence: Callable[[], None], chroma_rgb: tuple[int, int, int] | None, output_store: Store,
) -> Outcome:
    version = library.get(source_version_id)
    require_media(version, "/source_version_id")
    if version is None or version.content is None:
        raise failure(REQUEST_INVALID, "The pinned source version has no media")
    asset = library.asset_of(source_version_id)
    # A promoted library photo is opaque-only. Its explicitly chosen cast
    # slot makes the derived candidate a cast asset with its own identity.
    kind = "cast" if asset.kind == "photo" else asset.kind
    if (not is_id(job_id, "job") or asset.scope.production_id != production_id
            or asset.scope.story_id is not None or asset.scope.board_id is not None
            or not version.has("opaque_photo")
            or not {"rgba_cutout", "mask"}.issubset(KIND_CAPABILITIES[kind])):
        raise failure(REQUEST_INVALID, "An authorized, library-scoped opaque still is required")
    target = MatteTarget.from_recipe(format_version, slot)
    source, data = _read_source(store, version, asset.scope.production_id)
    identity = {"source": source, "profile_id": PROFILE_ID, "profile_sha256": client.profile_sha256,
                "parameters": {"chroma_rgb": None if chroma_rgb is None else list(chroma_rgb),
                               "target_height_px": target.height}}
    key = "matting:" + sha256(canonical_json({"input": identity, "target": target.document()})).hexdigest()
    asset_id, version_id = _stable_id("ast", key), _stable_id("asv", key)
    check_fence()
    existing = _existing(library, key, asset_id, version_id)
    if existing is not None:
        recorded, missing = _recorded_outputs(existing, store)
        if not missing:
            return Outcome(library, existing, created=False)
        # The receipt is job-specific. Replay its original request so even a
        # missing receipt blob can be restored without changing provenance.
        try:
            job_id = existing.provenance["generator"]["params"]["receipt"]["job_id"]
        except (KeyError, TypeError):
            raise failure(IDEMPOTENCY_MISMATCH, "The recorded matte has an invalid receipt") from None

    request = {"schema": "studio.matte-request/v1", "job_id": job_id, **identity}
    receipt, artifacts = client.run(request, data, check_fence=check_fence)
    canvas = source["width"], source["height"]
    MatteSize.measured(receipt["shape"], canvas, target.height)

    production = asset.scope.production_id
    cutout = _content(artifacts["cutout"], PNG, production, width=canvas[0], height=canvas[1])
    mask = _content(artifacts["mask"], PNG, production, width=canvas[0], height=canvas[1])
    receipt_bytes = canonical_json(receipt)
    receipt_blob = _content(receipt_bytes, JSON, production)
    outputs = ((artifacts["cutout"], cutout), (artifacts["mask"], mask), (receipt_bytes, receipt_blob))
    if existing is not None:
        if (cutout, mask, receipt_blob) != recorded:
            raise failure(HASH_MISMATCH, "The rebuilt matte differs from its recorded hashes or descriptors")
        for payload, descriptor in outputs:
            verified_store = store
            if descriptor in missing:
                check_fence()
                try:
                    _publish(output_store, payload, descriptor, production or LIBRARY)
                except StoreError as error:
                    if error.code != COLLISION:
                        raise
                    raise failure(HASH_MISMATCH, "A stored matte artifact differs from its pin") from None
                verified_store = output_store
            if verified_store.verify(descriptor.locator, descriptor.sha256) != PRESENT:
                raise failure(HASH_MISMATCH, "A recorded matte artifact could not be verified")
        check_fence()
        return Outcome(library, existing, created=False)

    try:
        licences = LicenceRegister.from_document(load_model_register()["proposals"]["matting"])
    except (KeyError, TypeError, ValueError):
        raise failure(COMMAND_FAILED, "The matting model licence register is invalid") from None
    outcome = import_version(library, VersionRequest(
        kind=kind, name=asset.name, scope=asset.scope, labels=asset.labels,
        attributes=asset.attributes, asset_id=asset_id, version_id=version_id,
        state=CANDIDATE, capabilities=("rgba_cutout", "mask"), content=cutout,
        provenance={"origin": "derived", "source_key": key, "external": None, "generator": {
            "role": "composite", "engine": ENGINE, "model": PROFILE_ID,
            "files_sha256": receipt["provenance"]["files_sha256"],
            "source_asset_version_ids": [version.id],
            "params": {"profile_sha256": client.profile_sha256,
                       "image_digest": receipt["provenance"]["image_digest"],
                       "input_signature": receipt["input_signature"], "receipt": receipt,
                       "mask": to_document(mask), "receipt_blob": to_document(receipt_blob),
                       "normalization": target.document()},
        }},
        licence=licences.licence_for("composite", PROFILE_ID),
    ), by=by, now=now)
    for payload, artifact in outputs:
        check_fence()
        _publish(output_store, payload, artifact, production or LIBRARY)
    check_fence()
    return outcome


def run_matte_job(
    library: Library, *, source_version_id: str, job_id: str, production_id: str | None,
    format_version: Mapping, slot: str, by: Principal, now: str, store: Store, client: MattingClient,
    check_fence: Callable[[], None], record_failure: Callable[..., None],
    chroma_rgb: tuple[int, int, int] | None = None, output_store: Store | None = None,
) -> Outcome | None:
    """Run in the worker beside the sidecar, from an admitted, frozen asset job.

    Read from the authoritative store and write to the job's staging store
    when supplied. The caller owns the claim and commits the returned library
    outcome behind its fence, after making all three blobs authoritative.
    Blob writes alone do not publish a candidate. Fence loss propagates.
    """
    try:
        return _make_candidate(
            library, source_version_id=source_version_id, job_id=job_id, production_id=production_id,
            format_version=format_version, slot=slot, by=by, now=now, store=store, client=client,
            check_fence=check_fence, chroma_rgb=chroma_rgb,
            output_store=store if output_store is None else output_store,
        )
    except (AdapterError, StoreError) as error:
        record_failure(code=error.code, message=str(error)[:500] if isinstance(error, AdapterError)
                       else "The private store could not verify or publish the matte")
    except ContractError as error:
        issue = error.violations[0]
        record_failure(code=issue.rule, message=issue.message[:500])
    except OSError:
        record_failure(code=COMMAND_FAILED, message="The matting job could not read or write its files")
    return None
