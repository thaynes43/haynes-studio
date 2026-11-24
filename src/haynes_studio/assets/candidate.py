"""Plan one shared-lane image prompt and record its result as a private candidate."""
from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from haynes_studio.adapters.comfyui import TextToImage
from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.canonical.model import Principal, require_human, to_document
from haynes_studio.errors import ContractError, Violation, blocking
from haynes_studio.jsonio import freeze
from haynes_studio.library import (
    Asset, AssetVersion, Content, Library, Outcome, Scope, VersionRequest, import_version,
    validate_asset,
)
from haynes_studio.library.library import IDEMPOTENCY_MISMATCH
from haynes_studio.library.model import CANDIDATE, PROMOTED, Licence, locator_for, signature
from haynes_studio.library.winter_menu import LicenceRegister
from haynes_studio.photo.build import MODEL, ImageEngine
from haynes_studio.photo.validation import (
    PNG, PhotoImage, check_hash, decode, png_image, sha256, text_is_encodable, verify_bytes,
)
from haynes_studio.store import HASH_MISMATCH, LIBRARY, LOCATOR_INVALID, Store, StoreError

_CAPABILITIES = {"cast": "opaque_photo", "costume": "opaque_photo", "set": "opaque_plate",
                 "prop": "opaque_photo"}


@dataclass(frozen=True)
class CandidatePlan:
    job_id: str
    asset_id: str
    kind: str
    name: str
    scope: Scope
    labels: tuple[str, ...]
    by: Principal
    request: TextToImage
    input_signature: str = field(init=False)

    def __post_init__(self) -> None:
        inputs = {
            "schema": "studio.asset-candidate-inputs/v1", "asset_id": self.asset_id,
            "kind": self.kind, "name": self.name,
            "production_id": self.scope.production_id, "labels": list(self.labels),
            "created_by": to_document(self.by), "model": MODEL, "prompt": self.request.prompt,
            "seed": self.request.seed, "request_size": [self.request.width, self.request.height],
        }
        try:
            digest = signature(inputs)
        except UnicodeEncodeError:
            raise _error("schema.invalid", "", "job inputs must be valid UTF-8 text") from None
        object.__setattr__(self, "input_signature", digest)

    @property
    def source_key(self) -> str:
        return f"asset-candidate:{self.job_id}"


def plan_candidate(*, job_id: str, asset_id: str, kind: str, name: str, production_id: str | None,
                   prompt: str, seed: int, by: Principal,
                   labels: tuple[str, ...] = ()) -> CandidatePlan:
    """Validate and freeze a human's job inputs before the shared lane is used."""
    require_human(by, "generate_asset_candidate")
    if not is_id(job_id, "job"):
        raise _error("id.malformed", "/job_id", "expected a job_ ID")
    if not isinstance(kind, str) or kind not in _CAPABILITIES:
        raise _error("schema.invalid", "/kind", "expected cast, costume, set or prop")
    if not isinstance(prompt, str) or not text_is_encodable(prompt):
        raise _error("schema.invalid", "/prompt", "expected Unicode text")
    if not isinstance(name, str) or not name.strip():
        raise _error("schema.invalid", "/name", "expected a name")
    if not isinstance(labels, (tuple, list)):
        raise _error("schema.invalid", "/labels", "expected an array")
    scope = Scope(production_id)
    name = unicodedata.normalize("NFC", name.strip())
    labels = tuple(unicodedata.normalize("NFC", label) if isinstance(label, str) else label
                   for label in labels)
    asset = Asset(asset_id, kind, name, scope, labels, {}, created_by=by)
    problems = blocking(validate_asset(asset.to_document(), context="write"))
    if problems:
        raise ContractError("<asset candidate>", problems)
    request = TextToImage(job=job_id.lower().replace("_", "-"), name="asset-candidate",
                          prompt=unicodedata.normalize("NFC", prompt), seed=seed)
    return CandidatePlan(job_id, asset_id, kind, name, scope, labels, by, request)


@dataclass(frozen=True)
class PreparedCandidate:
    plan: CandidatePlan
    image: PhotoImage
    generator: Mapping[str, Any]
    licence: Licence


def generate_candidate(plan: CandidatePlan, *, client: ImageEngine,
                       licences: LicenceRegister | None = None) -> PreparedCandidate:
    """Render one still with the same client and PNG validation as board photos."""
    require_human(plan.by, "generate_asset_candidate")
    request = plan.request
    answer = client.render(request)
    verify_bytes(answer.png, answer.sha256, "/content/sha256")
    check_hash(answer.graph_sha256, "/provenance/generator/workflow_sha256")
    image = png_image(decode(answer.png, PNG, "/content"))
    generator = freeze({
        "role": "image", "engine": "ComfyUI", "model": MODEL, "files_sha256": {},
        "workflow_sha256": answer.graph_sha256, "seed": request.seed, "prompt": request.prompt,
        "engine_job_id": answer.prompt_id, "source_asset_version_ids": [],
        "params": {
            "input_signature": plan.input_signature, "request_size": [request.width, request.height],
            "engine_png_sha256": answer.sha256, "waited_s": answer.waited_s,
            "render_s": answer.render_s,
        },
    })
    licence = (Licence.unknown("No licence register was supplied for the image model.")
               if licences is None else licences.licence_for("image", MODEL))
    return PreparedCandidate(plan, image, generator, licence)


def candidate_result(library: Library, plan: CandidatePlan) -> AssetVersion | None:
    """Look up an authorized job's result before submitting or resuming work."""
    require_human(plan.by, "generate_asset_candidate")
    asset = library.by_source_key(plan.source_key)
    if asset is None:
        if plan.asset_id in library.assets:
            raise _error("ref.duplicate", "/asset_id", "the candidate's asset ID is already in use")
        return None
    versions = library.versions_of(asset.id)
    if len(versions) == 1:
        (version,) = versions
        params = (version.provenance.get("generator") or {}).get("params", {})
        if (asset.id == plan.asset_id and asset.scope == plan.scope and asset.kind == plan.kind
                and version.source_key == plan.source_key and version.origin == "generated"
                and version.state in (CANDIDATE, PROMOTED)
                and params.get("input_signature") == plan.input_signature):
            return version
    raise _error(IDEMPOTENCY_MISMATCH, "/job_id", "this job ID already names another candidate request",
                 status="conflict")


def record_candidate(prepared: PreparedCandidate, library: Library, *, store: Store,
                     now: str, minter: Minter | None = None) -> Outcome:
    """Publish create-only and return metadata for the caller's fenced completion write."""
    plan, image = prepared.plan, prepared.image
    existing = candidate_result(library, plan)
    digest = sha256(image.png)
    locator = locator_for(digest, PNG, plan.scope.production_id)
    content = Content(digest, len(image.png), PNG, locator, image.width, image.height)
    if existing is not None and (existing.content != content
                                 or existing.provenance["generator"] != prepared.generator):
        raise _error(IDEMPOTENCY_MISMATCH, "/job_id", "this job ID already has a different recorded result",
                     status="conflict")
    outcome = import_version(library, VersionRequest(
        kind=plan.kind, name=plan.name, scope=plan.scope, labels=plan.labels,
        capabilities=(_CAPABILITIES[plan.kind],), content=content, state=CANDIDATE,
        provenance={"origin": "generated", "generator": prepared.generator, "external": None,
                    "source_key": plan.source_key},
        licence=prepared.licence, asset_id=plan.asset_id,
    ), by=plan.by, now=now, minter=minter)
    if outcome.created:
        blob = store.publish(image.png, scope=plan.scope.production_id or LIBRARY, media_type=PNG,
                             expected_sha256=digest)
        if blob.sha256 != digest or blob.bytes != content.bytes:
            raise StoreError(HASH_MISMATCH, "the store returned different content", locator=locator)
        if blob.locator != locator or blob.media_type != PNG:
            raise StoreError(LOCATOR_INVALID, "the store returned a different locator or media type",
                             locator=locator)
    return outcome


def _error(rule: str, path: str, message: str, *, status: str = "invalid") -> ContractError:
    return ContractError("<asset candidate>", [Violation(rule, path, message, status)])
