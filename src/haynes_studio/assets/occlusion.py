"""Observe one authorized library still and publish its fenced segmentation receipt."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO

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


@dataclass(frozen=True)
class SegmentationIdentity:
    production_id: str | None
    source_version_id: str
    request_sha256: str
    profile_sha256: str

    @property
    def scope(self) -> str:
        return LIBRARY if self.production_id is None else self.production_id


@dataclass(frozen=True)
class SegmentationCompletion:
    """Verified claim output. Only ready results occupy the completion key."""

    identity: SegmentationIdentity
    result: Blob
    status: str
    reason: str | None
    mask: Blob | None


@dataclass(frozen=True)
class SegmentationOutcome:
    """A current completion with read-back bytes. Only ready records carry a PNG."""

    completion: SegmentationCompletion
    png: bytes | None

    @property
    def action(self) -> str:
        return {"ready": "use_mask", "needs_hint": "review", "failed": "stop"}[self.completion.status]


def decode_still(content: Content, data: bytes, *, plate: bool) -> Image.Image:
    """Read the pinned, normalized RGBA pixels used for observation and layout."""
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
    return {"sha256": content.sha256, "width": image.width, "height": image.height}, data, alpha, version


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
    if (parse_locator(blob.locator).scope != scope or blob.media_type != media_type
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


def _existing(store, completion, identity, request, profile, alpha):
    if (completion.identity != identity or completion.status != "ready"
            or completion.reason is not None or completion.mask is None):
        raise SegmentationError("invalid_output")
    receipt = _read_blob(store, completion.result, identity.scope, JSON, MAX_REPLY)
    png = _read_blob(store, completion.mask, identity.scope, PNG, MAX_SOURCE_BYTES)
    try:
        result = parse_strict(receipt.decode("utf-8"))
        if canonical_json(result) != receipt:
            raise ValueError("noncanonical receipt")
    except (ValueError, RecursionError):
        raise SegmentationError("invalid_output") from None
    pixels = verify_result(request, result, png, profile)
    _verify_support(pixels, alpha, request)
    return SegmentationOutcome(completion, png)


def _publish(store, identity, data, media_type, check_fence):
    check_fence()
    expected = digest(data)
    blob = store.publish(data, scope=identity.scope, media_type=media_type, expected_sha256=expected)
    if blob.sha256 != expected or _read_blob(store, blob, identity.scope, media_type, len(data)) != data:
        raise SegmentationError("store_failed")
    return blob


def run_segmentation_job(
    library: Library, *, source_version_id: str, production_id: str | None,
    kind: str, key: str, label: str | None = None, hint: Mapping | None = None,
    store: Store, client: SegmentationClient, check_fence: Callable[[], None],
    lookup_ready: Callable[[SegmentationIdentity], SegmentationCompletion | None],
    commit_completion: Callable[[SegmentationCompletion], None],
    record_failure: Callable[..., None],
) -> SegmentationOutcome | None:
    """Run beside the sidecar from an admitted, frozen asset operation.

    The caller supplies an authorized library slice and a current-only ready lookup.
    Both writers must enforce the claim fence atomically. The completion writer
    creates only ready records. The failure writer appends diagnostics, optionally
    with a verified non-ready receipt, outside the ready identity namespace.
    Source and library are read-only.
    """
    try:
        scope_prefix(LIBRARY if production_id is None else production_id)
        with client.serial(check_fence):
            source, data, alpha, version = _source(library, source_version_id, production_id, kind, store)
            if version.occlusion is not None:
                group = "foreground" if kind == "foreground" else "focal_props"
                declared = next((value for value in version.occlusion[group] if value["key"] == key), None)
                if declared is not None:
                    if declared.get("depth") == "separate":
                        raise SegmentationError("invalid_input")
                    label = declared["label"] if label is None else label
                    hint = declared.get("hint") if hint is None else hint
            request = make_request(source, kind=kind, key=key, label=label, hint=hint)
            identity = SegmentationIdentity(
                production_id, source_version_id, digest(canonical_json(request)), client.profile_sha256,
            )
            check_fence()
            existing = lookup_ready(identity)
            if existing is not None:
                outcome = _existing(store, existing, identity, request, client.profile, alpha)
                check_fence()
                return outcome

            result, png, pixels = client.run_locked(request, data, check_fence)
            _verify_support(pixels, alpha, request)
            mask = None if png is None else _publish(store, identity, png, PNG, check_fence)
            receipt = _publish(store, identity, canonical_json(result), JSON, check_fence)
            completion = SegmentationCompletion(identity, receipt, result["status"], result["reason"], mask)
            check_fence()
            if completion.status == "ready":
                commit_completion(completion)
            else:
                record_failure(code=completion.reason, diagnostic=completion)
            return SegmentationOutcome(completion, png)
    except SegmentationError as error:
        code = error.reason
    except (StoreError, OSError):
        code = "store_failed"
    check_fence()
    record_failure(code=code)
    return None
