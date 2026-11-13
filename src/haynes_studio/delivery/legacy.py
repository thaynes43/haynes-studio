"""Legacy deliveries (contract sections 1 and 8, story 381): a recorded Wan ledger
document (``kind: edited_production``, as ``poc/deliver.py`` wrote it and story 425's
:class:`~haynes_studio.adapters.wan_ledger.LedgerRecord` types it) and its validation
evidence, mapped to a ``studio.delivery/v1`` with adapter ``legacy_wan_ledger``.

Read-only by construction: :func:`legacy_delivery` takes documents already read (from
the public ``titles/<slug>/evidence*/`` files, or from
:meth:`~haynes_studio.adapters.wan_ledger.LedgerReader.get`), makes no call and has no
store, runner or path to write through. The legacy master stays where it is on the Wan
volume; the delivery names it by ``legacy_path`` and hash, never copies it, and has no
proxy (the ledger never made one).

| Delivery field | From |
|---|---|
| ``id``, ``run_id`` | the caller: the import map's ``delivery_id`` and ``imported_run_id`` |
| ``created_at`` | ledger ``created_at`` (epoch seconds), as ISO time to the whole second, rounded down (the contract's r4 example) |
| ``master.sha256``, ``bytes``, ``legacy_path`` | ledger ``sha256``, ``bytes``, ``output`` |
| ``master.width``, ``height``, ``fps``, ``frames`` | the validation evidence: ``width``, ``height``, ``fps``, ``decoded_frames`` |
| ``master.video_codec``, ``audio_codec`` | Legacy: ``poc/edit.py`` encodes ``libx264`` and ``aac`` (not decoded here: the file is on the Wan volume) |
| ``verification`` | the evidence's ``decoded_frames`` and ``expected_frames``; ``sha256_verified`` when its ``sha256`` and ``bytes`` are the ledger's; ``source`` names it |
| ``legacy`` | ledger ``id``, ``kind``, ``preset`` and ``provenance`` verbatim; ``assets_ref`` names the ledger file; ``url`` is the review link ``poc/deliver.py`` printed |

A ledger whose evidence disagrees with it (another hash or size, a failed or
incomplete validation, a frame size that is no media kind) is refused with
``delivery.legacy_mismatch`` (proposal), never mapped to a partial delivery.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from haynes_studio.adapters.wan_ledger import ADAPTER, KIND, record_from_document
from haynes_studio.canonical.validate import READ
from haynes_studio.delivery.errors import LEGACY_MISMATCH, DeliveryError
from haynes_studio.delivery.model import (
    AAC,
    DELIVERY_SCHEMA,
    FPS,
    H264,
    MP4,
    Delivery,
    media_kind_of,
)
from haynes_studio.delivery.validate import validate_delivery
from haynes_studio.jsonio import thaw

REVIEW_URL = "https://video.haynesops.com/videos/{ledger_id}/file"  # poc/deliver.py


def legacy_delivery(ledger: Mapping[str, Any], validation: Mapping[str, Any], *,
                    delivery_id: str, run_id: str, assets_ref: str,
                    verification_ref: str) -> Delivery:
    """The read-only delivery of one recorded ledger. ``ledger`` is the ledger document
    (``evidence*/production.json``); ``validation`` its evidence
    (``evidence*/validation.json``); ``assets_ref`` and ``verification_ref`` are those
    files' paths in this repository. The ledger is checked as story 425's reader checks
    an answer (``adapter.response_invalid``)."""
    record = record_from_document(thaw(ledger), label="legacy_delivery")
    evidence = _evidence(validation, record.sha256, record.bytes)
    document = {
        "schema": DELIVERY_SCHEMA,
        "id": delivery_id,
        "run_id": run_id,
        "created_at": datetime.fromtimestamp(int(record.created_at), UTC)
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "store": {"adapter": ADAPTER, "writable": False},
        "master": {
            "sha256": record.sha256, "bytes": record.bytes, "media_type": MP4,
            "width": evidence["width"], "height": evidence["height"], "fps": evidence["fps"],
            "frames": evidence["decoded_frames"], "video_codec": H264, "audio_codec": AAC,
            "locator": None, "legacy_path": record.output,
        },
        "proxy": None,
        "verification": {
            "decoded_frames": evidence["decoded_frames"],
            "expected_frames": evidence["expected_frames"],
            "sha256_verified": True,
            "source": verification_ref,
        },
        "legacy": {
            "ledger_id": record.id,
            "kind": KIND,
            "preset": record.preset,
            "provenance": thaw(ledger["provenance"]),
            "assets_ref": assets_ref,
            "url": REVIEW_URL.format(ledger_id=record.id),
        },
    }
    problems = validate_delivery(document, context=READ)
    if problems:
        raise DeliveryError(LEGACY_MISMATCH, f"ledger {record.id} does not map to a delivery: "
                            + "; ".join(str(problem) for problem in problems))
    return Delivery.from_document(document)


def _evidence(validation: Any, sha256: str, size: int) -> Mapping[str, Any]:
    """The validation evidence, if it verified this exact master."""
    def bad(message: str) -> DeliveryError:
        return DeliveryError(LEGACY_MISMATCH, f"the validation evidence {message}")
    if not isinstance(validation, Mapping):
        raise bad("is not an object")
    fields = ("sha256", "bytes", "width", "height", "fps", "decoded_frames", "expected_frames")
    missing = [name for name in fields if name not in validation]
    if missing:
        raise bad("lacks " + ", ".join(missing))
    if validation["sha256"] != sha256 or validation["bytes"] != size:
        raise bad("is for another file than the ledger's master")
    if validation.get("passed") is not True:
        raise bad("did not pass")
    numbers = [validation[name] for name in fields[1:]]
    if not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in numbers):
        raise bad("has a size, frame rate or frame count that is not a positive integer")
    if validation["decoded_frames"] != validation["expected_frames"]:
        raise bad("decoded another frame count than it expected (TIME-11)")
    if validation["fps"] != FPS or media_kind_of(validation["width"], validation["height"]) is None:
        raise bad("is not a media kind's frame size at 24 fps")
    return validation


__all__ = ["REVIEW_URL", "legacy_delivery"]
