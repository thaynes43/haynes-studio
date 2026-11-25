"""Observe one authorized library still and publish its fenced segmentation receipt."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from weakref import WeakKeyDictionary

import numpy as np
from PIL import Image

from haynes_studio.adapters.segmentation import SegmentationClient, verify_result
from haynes_studio.jsonio import parse_strict, thaw
from haynes_studio.library import Content, Library
from haynes_studio.segmentation.inference import validate_request
from haynes_studio.segmentation.profile import (
    MAX_PIXELS, MAX_SHORT_SIDE, MAX_SIDE, MAX_SOURCE_BYTES, PROFILE_ID, SegmentationError, digest,
)
from haynes_studio.segmentation.service import MAX_REPLY
from haynes_studio.store import Blob, Store, StoreError, canonical_json
from haynes_studio.store.errors import BLOB_MISSING
from haynes_studio.store.layout import LIBRARY, parse_locator, scope_prefix

PNG, JSON = "image/png", "application/json"
IMAGE_FORMATS = {PNG: "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


@dataclass(frozen=True, slots=True)
class SegmentationIdentity:
    production_id: str | None
    source_version_id: str
    request_sha256: str
    profile_sha256: str

    @property
    def scope(self) -> str:
        return LIBRARY if self.production_id is None else self.production_id


@dataclass(frozen=True, slots=True)
class SegmentationCompletion:
    """Stored claim output. Only ready records occupy the completion key."""

    identity: SegmentationIdentity
    result: Blob
    status: str
    reason: str | None
    mask: Blob | None


@dataclass(frozen=True, slots=True)
class SegmentationOutcome:
    """A diagnostic receipt and its bytes."""

    completion: SegmentationCompletion
    png: bytes | None
    receipt: bytes

    @property
    def action(self) -> str:
        return {"needs_hint": "review", "failed": "stop"}[self.completion.status]


def decode_still(content: Content, data: bytes, *, plate: bool) -> Image.Image:
    """Read the pinned, normalized RGBA pixels used for observation."""
    expected_format = IMAGE_FORMATS.get(content.media_type)
    if (expected_format is None or not 0 < len(data) <= MAX_SOURCE_BYTES
            or digest(data) != content.sha256
            or content.bytes is not None and len(data) != content.bytes):
        raise SegmentationError("invalid_input")
    try:
        with Image.open(BytesIO(data), formats=[expected_format]) as image:
            width, height = image.size
            if (not 32 <= min(width, height) <= MAX_SHORT_SIDE or max(width, height) > MAX_SIDE
                    or width * height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1
                    or image.getexif().get(274, 1) != 1
                    or content.width is not None and content.width != width
                    or content.height is not None and content.height != height):
                raise SegmentationError("invalid_input")
            rgba = image.convert("RGBA")
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Warning):
        raise SegmentationError("invalid_input") from None
    low, high = rgba.getchannel("A").getextrema()
    if (plate and low != 255) or (not plate and (low != 0 or high == 0)):
        raise SegmentationError("invalid_input")
    return rgba


def _source(library, source_version_id, production_id, kind, store):
    version = library.get(source_version_id)
    if version is None or version.recorded_without_media or version.content is None:
        raise SegmentationError("input_unavailable")
    owner = library.asset_of(source_version_id).scope
    content = version.content
    locator = parse_locator(content.locator)
    if (owner.production_id not in (None, production_id)
            or owner.story_id is not None or owner.board_id is not None
            or locator.production_id not in (None, owner.production_id)
            or locator.sha256 != content.sha256 or locator.media_type != content.media_type):
        raise SegmentationError("input_unavailable")
    plate = version.kind == "set" and version.has("opaque_plate") and kind in ("foreground", "prop")
    cutout = version.has("rgba_cutout") and (version.kind, kind) in (("cast", "face"), ("prop", "prop"))
    if not (plate or cutout):
        raise SegmentationError("invalid_input")
    if content.bytes is not None and not 0 < content.bytes <= MAX_SOURCE_BYTES:
        raise SegmentationError("invalid_input")
    try:
        with store.open(content.locator) as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
    except StoreError as error:
        if error.code == BLOB_MISSING:
            raise SegmentationError("input_unavailable") from None
        raise
    image = decode_still(content, data, plate=plate)
    alpha = None if plate else np.asarray(image.getchannel("A")) != 0
    return {"sha256": content.sha256, "width": image.width, "height": image.height}, data, alpha


def _text(value):
    return unicodedata.normalize("NFC", value.strip()) if isinstance(value, str) else value


def make_request(source: dict, *, kind: str, key: str, label: str | None,
                 hint: Mapping | None) -> dict:
    """Canonicalize text and freeze the closed service request."""
    hint = thaw(hint)
    if isinstance(hint, dict) and hint.get("kind") == "text" and "text" in hint:
        hint["text"] = _text(hint["text"])
    request = {
        "schema": "studio.segmentation-request/v1", "profile": PROFILE_ID, "input": source,
        "target": {"kind": kind, "key": key, "label": _text(label)}, "hint": hint,
    }
    validate_request(request)
    return request


def _read_blob(store, blob, scope, media_type, limit):
    locator = parse_locator(blob.locator)
    if (locator.scope != scope or locator.sha256 != blob.sha256
            or locator.media_type != blob.media_type or blob.media_type != media_type
            or not 0 < blob.bytes <= limit):
        raise SegmentationError("invalid_output")
    with store.open(blob.locator) as stream:
        data = stream.read(blob.bytes + 1)
    if len(data) != blob.bytes or digest(data) != blob.sha256:
        raise SegmentationError("invalid_output")
    return data


def _verify_support(pixels, alpha, request):
    if pixels is not None and (
        alpha is not None and (pixels & ~alpha).any()
        or request["hint"] is not None and request["hint"]["kind"] == "point"
        and not pixels[request["hint"]["xy"][1], request["hint"]["xy"][0]]
    ):
        raise SegmentationError("invalid_output")


def _observation_boundary():
    # Only verification can attach data to an observation. An empty object made
    # with object.__new__ has no writable fields and cannot supply an observation.
    state = WeakKeyDictionary()

    def verified_data(observation) -> tuple[SegmentationCompletion, bytes, bytes]:
        try:
            return state[observation]
        except KeyError:
            raise TypeError("Only the segmentation adapter can verify a ready observation") from None

    class VerifiedObservation:
        """A ready observation bound to its frozen request, verified by the adapter."""

        __slots__ = ("__weakref__",)

        def __new__(cls):
            raise TypeError("Only the segmentation adapter can verify a ready observation")

        def __init_subclass__(cls):
            raise TypeError("Verified observations cannot be subclassed")

        @property
        def completion(self) -> SegmentationCompletion:
            # Keep the verified record private. Dataclass initializers can
            # rewrite even frozen objects when called on an existing instance.
            return deepcopy(verified_data(self)[0])

        @property
        def png(self) -> bytes:
            return verified_data(self)[1]

        @property
        def receipt(self) -> bytes:
            return verified_data(self)[2]

        @property
        def action(self) -> str:
            verified_data(self)
            return "use_mask"

    def verified_ready(store, completion, identity, request, profile, alpha) -> VerifiedObservation:
        completion = deepcopy(completion)
        if (completion.identity != identity or completion.status != "ready"
                or completion.reason is not None or completion.mask is None
                or identity.request_sha256 != digest(canonical_json(request))
                or identity.profile_sha256 != digest(profile.manifest())):
            raise SegmentationError("invalid_output")
        receipt = _read_blob(store, completion.result, identity.scope, JSON, MAX_REPLY)
        png = _read_blob(store, completion.mask, identity.scope, PNG, MAX_SOURCE_BYTES)
        try:
            result = parse_strict(receipt.decode("utf-8"))
            if canonical_json(result) != receipt:
                raise ValueError("noncanonical receipt")
        except (ValueError, RecursionError):
            raise SegmentationError("invalid_output") from None
        # Check the PNG descriptor in the receipt against the exact bytes that
        # matched the completion's locator, hash, length and media type above.
        pixels = verify_result(request, result, png, profile)
        _verify_support(pixels, alpha, request)
        observation = object.__new__(VerifiedObservation)
        state[observation] = (completion, png, receipt)
        return observation

    return VerifiedObservation, verified_ready


VerifiedObservation, _verified_ready = _observation_boundary()


def _publish(store, identity, data, media_type, check_fence):
    check_fence()
    expected = digest(data)
    blob = store.publish(data, scope=identity.scope, media_type=media_type, expected_sha256=expected)
    if blob.sha256 != expected:
        raise SegmentationError("store_failed")
    return blob


def run_segmentation_job(
    library: Library, *, source_version_id: str, production_id: str | None,
    kind: str, key: str, label: str | None = None, hint: Mapping | None = None,
    store: Store, client: SegmentationClient, check_fence: Callable[[], None],
    lookup_ready: Callable[[SegmentationIdentity], SegmentationCompletion | None],
    commit_completion: Callable[[SegmentationCompletion], None],
    record_failure: Callable[..., None],
) -> VerifiedObservation | SegmentationOutcome | None:
    """Run beside the sidecar from an admitted, frozen asset operation.

    The caller supplies an authorized library slice, the target kind, key, label
    and hint, and a current-only ready lookup. Prop targets require a label.
    Both writers must enforce the claim fence atomically. The completion writer
    creates only ready records. The failure writer appends diagnostics, optionally
    with a verified non-ready receipt, outside the ready identity namespace.
    Source and library are read-only.
    """
    try:
        scope_prefix(LIBRARY if production_id is None else production_id)
        with client.serial(check_fence):
            source, data, alpha = _source(library, source_version_id, production_id, kind, store)
            request = make_request(source, kind=kind, key=key, label=label, hint=hint)
            identity = SegmentationIdentity(
                production_id, source_version_id, digest(canonical_json(request)), client.profile_sha256,
            )
            check_fence()
            existing = lookup_ready(deepcopy(identity))
            if existing is not None:
                outcome = _verified_ready(store, existing, identity, request, client.profile, alpha)
                check_fence()
                return outcome

            result, png, pixels = client.run_locked(request, data, check_fence)
            _verify_support(pixels, alpha, request)
            mask = None if png is None else _publish(store, identity, png, PNG, check_fence)
            receipt_bytes = canonical_json(result)
            receipt = _publish(store, identity, receipt_bytes, JSON, check_fence)
            completion = SegmentationCompletion(identity, receipt, result["status"], result["reason"], mask)
            if completion.status == "ready":
                outcome = _verified_ready(store, completion, identity, request, client.profile, alpha)
                check_fence()
                commit_completion(completion)
                return outcome
            _read_blob(store, receipt, identity.scope, JSON, MAX_REPLY)
            check_fence()
            record_failure(code=completion.reason, diagnostic=completion)
            return SegmentationOutcome(completion, png, receipt_bytes)
    except SegmentationError as error:
        code = error.reason
    except (StoreError, OSError):
        code = "store_failed"
    check_fence()
    record_failure(code=code)
    return None
