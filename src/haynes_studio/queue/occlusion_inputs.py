"""Signed admissions shared by the occlusion worker and its completion verifier."""

from haynes_studio.errors import ContractError, Violation
from haynes_studio.library import Library
from haynes_studio.library.model import signature
from haynes_studio.segmentation.inference import validate_request
from haynes_studio.segmentation.profile import Profile, SegmentationError, digest
from haynes_studio.store import canonical_json


def occlusion_signature(frozen):
    return signature({"schema": "studio.occlusion-job-inputs/v1", **frozen})


def checked_occlusion(job, frozen, production):
    changed = ContractError(job.id, [Violation("job.input_changed", "", "The frozen occlusion inputs changed")])
    try:
        source, request = frozen["source"], frozen["request"]
        if (occlusion_signature(frozen) != job.input_signature or frozen["production_id"] != production
                or job.target_id != (frozen["set_version_id"] or source["id"])):
            raise changed
        validate_request(request)
        profile = Profile.from_manifest(frozen["profile"])
        library = Library.from_version_documents([source])
    except (KeyError, TypeError, ValueError, SegmentationError) as error:
        raise changed from error
    return library, request, profile


def occlusion_provenance(frozen):
    return {"occlusion": {
        "source_version_id": frozen["source"]["id"], "set_version_id": frozen["set_version_id"],
        "production_id": frozen["production_id"], "request": frozen["request"],
        "profile_sha256": digest(canonical_json(frozen["profile"])),
    }}
