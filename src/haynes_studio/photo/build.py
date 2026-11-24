"""Prepare generated, externally supplied and layered photos through their existing boundaries."""
from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from haynes_studio.adapters.comfyui import ImageEdit, ImageResult, TextToImage
from haynes_studio.canonical.ids import is_id
from haynes_studio.canonical.model import Principal
from haynes_studio.jsonio import freeze
from haynes_studio.layered.photo import compose_photo
from haynes_studio.library import Library
from haynes_studio.library.model import Licence
from haynes_studio.library.resolve import BYTES_MISSING
from haynes_studio.library.winter_menu import LicenceRegister

from .plan import LAYERED, WHOLE_FRAME, PhotoPlan, PhotoSource, sources_for
from .validation import (
    INVALID_IMAGE, MAX_UPLOAD_BYTES, PNG, TOO_LARGE, PhotoImage, check_hash, decode, error,
    png_image, reference_canvas, sha256, text_is_encodable, verify_bytes,
)

MODEL = "Qwen-Image 2.1"
METHOD_INVALID = "photo.method_invalid"
PROVENANCE_INVALID = "prov.external_incomplete"
IDENTITY_CONTROL = re.compile(r"[\u0000-\u001f\u007f-\u009f]")
Fetch = Callable[[str, str], bytes | None]


class ImageEngine(Protocol):
    def render(self, request: TextToImage | ImageEdit) -> ImageResult: ...


@dataclass(frozen=True)
class PreparedPhoto:
    plan: PhotoPlan
    image: PhotoImage
    origin: str
    generator: Mapping[str, Any]
    licence: Licence
    external: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ExternalProvenance:
    model: str
    prompt: str
    session: str
    harness: str
    source_asset_version_ids: tuple[str, ...]
    paid_api: bool
    upload_sha256: str | None = None


def _generator(plan: PhotoPlan, *, sources: tuple[PhotoSource, ...], role: str,
               params: dict[str, Any], **fields: Any) -> Mapping[str, Any]:
    return freeze({
        "role": role, **fields,
        "source_asset_version_ids": [source.version_id for source in sources],
        "params": {
            **params, "input_signature": plan.input_signature,
            "source_assets": [source.pin() for source in sources],
        },
    })


def _read(source: PhotoSource, fetch: Fetch) -> bytes:
    data = fetch(source.content.locator, source.content.sha256)
    if data is None:
        raise error(BYTES_MISSING, "/photo", "no bytes held for a pinned photo source")
    verify_bytes(data, source.content.sha256, "/photo/source")
    return data


def _whole_frame(plan: PhotoPlan) -> None:
    if plan.layer != WHOLE_FRAME:
        raise error(METHOD_INVALID, "/method/layer", "layered board photos come from the compositor")


def generate_photo(plan: PhotoPlan, *, client: ImageEngine, fetch: Fetch, job: str,
                   seed: int, licences: LicenceRegister | None = None) -> PreparedPhoto:
    """Render from a frozen plan with the story 425 client, using one prompt."""
    _whole_frame(plan)
    if plan.prompt is None or not plan.prompt.strip():
        raise error("schema.invalid", "/photo/prompt", "board photo generation needs a prompt")
    # Keep the board aspect at ~1 MP, the scale of the pinned edit graph.
    width, height = (side * 2 // 3 for side in plan.size)
    text = TextToImage(job=job, name="board-photo", prompt=plan.prompt, seed=seed,
                       width=width, height=height)
    params: dict[str, Any] = {"request_size": [width, height]}
    request: TextToImage | ImageEdit = text
    if plan.sources:
        images = (decode(_read(source, fetch), source.content.media_type, "/photo/source")
                  for source in plan.sources)
        canvas = reference_canvas(images, len(plan.sources), (width, height))
        request = ImageEdit(job=job, name=text.name, prompt=plan.prompt, seed=seed,
                            source_png=canvas.png)
        params.update(reference_canvas="white-grid/v1", reference_png_sha256=sha256(canvas.png))
    answer = client.render(request)
    verify_bytes(answer.png, answer.sha256, "/photo/result")
    check_hash(answer.graph_sha256, "/provenance/generator/workflow_sha256")
    image = png_image(decode(answer.png, PNG, "/photo/result"))
    params.update(engine_png_sha256=answer.sha256, waited_s=answer.waited_s, render_s=answer.render_s)
    generator = _generator(plan, sources=plan.sources, role="image", params=params,
                           engine="ComfyUI", model=MODEL, files_sha256={},
                           workflow_sha256=answer.graph_sha256, seed=seed, prompt=plan.prompt,
                           engine_job_id=answer.prompt_id)
    licence = (Licence.unknown("No licence register was supplied for the image model.")
               if licences is None else licences.licence_for("image", MODEL))
    return PreparedPhoto(plan, image, "generated", generator, licence)


def _external_text(value: str, field: str, limit: int, *, identity: bool = True) -> None:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or (identity and IDENTITY_CONTROL.search(value)) or not text_is_encodable(value)):
        raise error(PROVENANCE_INVALID, f"/provenance/{field}", f"expected text up to {limit} characters")


def import_photo(plan: PhotoPlan, library: Library, *, data: bytes, media_type: str,
                 declared: ExternalProvenance, by: Principal) -> PreparedPhoto:
    """Validate the D42 declaration and strip external media metadata before storage."""
    _whole_frame(plan)
    if by.kind != "agent" or not is_id(by.key_id, "key") or declared.paid_api is not False:
        raise error(PROVENANCE_INVALID, "/provenance/external",
                    "D42 needs an authenticated agent key and a paid_api: false declaration")
    _external_text(declared.model, "generator/model", 200)
    _external_text(declared.prompt, "generator/prompt", 10_000, identity=False)
    _external_text(declared.session, "external/agent/session", 200)
    _external_text(declared.harness, "external/agent/harness", 200)
    ids = declared.source_asset_version_ids
    if not isinstance(ids, (tuple, list)) or not all(is_id(item, "asv") for item in ids):
        raise error(PROVENANCE_INVALID, "/provenance/generator/source_asset_version_ids",
                    "expected an ordered array of asset version IDs")
    sources = sources_for(library, plan.scope, tuple(ids),
                          "/provenance/generator/source_asset_version_ids", images_only=False)
    if not isinstance(data, bytes) or not data:
        raise error(INVALID_IMAGE, "/photo", "expected non-empty image bytes")
    if len(data) > MAX_UPLOAD_BYTES:
        raise error(TOO_LARGE, "/photo", "an upload can be at most 20 MiB", "too_large")
    digest = (sha256(data) if declared.upload_sha256 is None
              else verify_bytes(data, declared.upload_sha256, "/provenance/upload_sha256"))
    image = png_image(decode(data, media_type, "/photo"))
    external = freeze({
        "externally_generated": True, "paid_api": False, "server_computed_sha256": True,
        "declared_by": "agent",
        "agent": {"kind": "agent", "key_id": by.key_id, "session": declared.session,
                  "harness": declared.harness},
    })
    generator = _generator(plan, sources=sources, role="image",
                           params={"upload_sha256": digest, "upload_media_type": media_type},
                           engine=None, model=declared.model,
                           prompt=unicodedata.normalize("NFC", declared.prompt))
    licence = Licence.unknown("Terms of the externally declared image model are unchecked.")
    return PreparedPhoto(plan, image, "uploaded", generator, licence, external)


def compose_layered_photo(plan: PhotoPlan, *, fetch: Fetch) -> PreparedPhoto:
    """Delegate to the existing D51 adapter with the frozen still pins."""
    if plan.layer != LAYERED or plan.layers is None:
        raise error(METHOD_INVALID, "/method/layer", "the compositor needs a layered board")
    by_hash = {source.content.sha256: source for source in plan.sources}

    def read(digest: str) -> io.BytesIO:
        return io.BytesIO(_read(by_hash[digest], fetch))

    data = compose_photo(plan.layers, read)
    image = PhotoImage(data, *plan.size)
    generator = _generator(plan, sources=plan.sources, role="composite",
                           params={"composite": plan.layers.document()},
                           engine=plan.layers.composer, model=None)
    licence = Licence.unknown("Derived from library stills whose licences remain on their versions.")
    return PreparedPhoto(plan, image, "derived", generator, licence)
