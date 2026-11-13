"""Read-only model of ``studio.delivery/v1`` (contract section 8, review H5): a run's
verified master and phone proxy, or a legacy delivery read in place from the Wan
ledger.

Each model is a frozen dataclass whose field names are the JSON field names, built
with ``from_document`` from a document that has passed
:func:`~haynes_studio.delivery.validate.validate_delivery`, and turned back into JSON
with :func:`~haynes_studio.canonical.model.to_document`. Nothing here reads files,
decodes media or calls services.

The media profiles and the proxy limit live here too, so the validator, the media
checks and the delivery agree on one set of numbers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.jsonio import freeze
from haynes_studio.timebase import DELIVERY_FPS, MIX_RATE, SAMPLES_PER_FRAME

DELIVERY_SCHEMA = "studio.delivery/v1"
DELIVERY_FILE = "studio.delivery.v1.schema.json"

# Store adapters (contract section 8). A legacy delivery is read in place, never written.
LOCAL, NFS, LEGACY_WAN_LEDGER = "local", "nfs", "legacy_wan_ledger"
ADAPTERS = (LOCAL, NFS, LEGACY_WAN_LEDGER)

MP4 = "video/mp4"
H264, AAC = "h264", "aac"
FPS = DELIVERY_FPS  # 24
AUDIO_RATE = MIX_RATE  # 48 000 Hz, 2000 samples per delivery frame (section 3)
AUDIO_SAMPLES_PER_FRAME = SAMPLES_PER_FRAME

SHORT, VIDEO = "short", "video"
# The media kind's delivery frame size (section 3: `short` is Legacy, `video` is P-20).
MASTER_SIZES = {SHORT: (1080, 1920), VIDEO: (1920, 1080)}
# P-10: the phone proxy of a short is 720x1280. The 16:9 `video` proxy, 1280x720, is
# story 381's proposal (the same 720-line height on the short side).
PROXY_SIZES = {SHORT: (720, 1280), VIDEO: (1280, 720)}

# P-10: a proxy is under 25 000 000 bytes for a 60 s (1440-frame) delivery. Proposal
# (story 381): a longer delivery's limit grows at the same rate per frame, so a proxy is
# always under 25 000 000 bytes per minute; a shorter one keeps the 60 s limit.
PROXY_LIMIT_BYTES = 25_000_000
PROXY_LIMIT_FRAMES = 60 * FPS


def media_kind_of(width: int, height: int) -> str | None:
    """The media kind whose master is ``width`` x ``height``, or ``None``."""
    return next((kind for kind, size in MASTER_SIZES.items() if size == (width, height)), None)


def proxy_byte_limit(frames: int) -> int:
    """The proxy's byte limit for a delivery of ``frames`` frames: 25 000 000 up to 60 s,
    and the same bytes per frame beyond (proposal). A proxy must be strictly under it."""
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
        raise ValueError(f"frames must be a positive integer, got {frames!r}")
    return PROXY_LIMIT_BYTES * max(frames, PROXY_LIMIT_FRAMES) // PROXY_LIMIT_FRAMES


@dataclass(frozen=True, slots=True)
class StoreInfo:
    adapter: str
    writable: bool


@dataclass(frozen=True, slots=True)
class MediaFile:
    """A master or proxy: its bytes by hash, its picture and codecs, and where it is.
    A studio delivery has a ``locator``; a legacy master has a ``legacy_path`` on the
    Wan volume instead."""

    sha256: str
    bytes: int
    media_type: str
    width: int
    height: int
    fps: int
    frames: int
    video_codec: str
    audio_codec: str
    locator: str | None
    legacy_path: str | None

    @classmethod
    def from_document(cls, doc: Mapping[str, Any] | None) -> MediaFile | None:
        return None if doc is None else cls(**{item.name: doc[item.name] for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class Verification:
    """What was checked: decoded frames against the expected count (TIME-11), the hashes
    re-read, and the proxy's byte limit; a legacy delivery names its evidence file."""

    decoded_frames: int
    expected_frames: int
    sha256_verified: bool
    proxy_under_bytes: int | None = None
    source: str | None = None

    _omit_none = ("proxy_under_bytes", "source")


@dataclass(frozen=True, slots=True)
class LegacyLedger:
    """The legacy ledger a delivery was mapped from. ``provenance`` is the ledger's,
    verbatim and read-only."""

    ledger_id: str
    kind: str
    preset: str
    provenance: Any
    assets_ref: str
    url: str


@dataclass(frozen=True, slots=True)
class Delivery:
    schema: str
    id: str
    run_id: str
    created_at: str
    store: StoreInfo
    master: MediaFile
    proxy: MediaFile | None
    verification: Verification
    legacy: LegacyLedger | None

    @property
    def is_legacy(self) -> bool:
        return self.store.adapter == LEGACY_WAN_LEDGER

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Delivery:
        """The model of a document that has passed ``validate_delivery``."""
        doc = normalize(doc)
        verification = doc["verification"]
        legacy = doc["legacy"]
        return cls(
            schema=doc["schema"], id=doc["id"], run_id=doc["run_id"],
            created_at=doc["created_at"], store=StoreInfo(**doc["store"]),
            master=MediaFile.from_document(doc["master"]),
            proxy=MediaFile.from_document(doc["proxy"]),
            verification=Verification(
                decoded_frames=verification["decoded_frames"],
                expected_frames=verification["expected_frames"],
                sha256_verified=verification["sha256_verified"],
                proxy_under_bytes=verification.get("proxy_under_bytes"),
                source=verification.get("source")),
            legacy=None if legacy is None else LegacyLedger(
                ledger_id=legacy["ledger_id"], kind=legacy["kind"], preset=legacy["preset"],
                provenance=freeze(legacy["provenance"]), assets_ref=legacy["assets_ref"],
                url=legacy["url"]))


__all__ = [
    "AAC", "ADAPTERS", "AUDIO_RATE", "AUDIO_SAMPLES_PER_FRAME", "DELIVERY_FILE",
    "DELIVERY_SCHEMA", "Delivery", "FPS", "H264", "LEGACY_WAN_LEDGER", "LOCAL",
    "LegacyLedger", "MASTER_SIZES", "MP4", "MediaFile", "NFS", "PROXY_LIMIT_BYTES",
    "PROXY_LIMIT_FRAMES", "PROXY_SIZES", "SHORT", "StoreInfo", "VIDEO", "Verification",
    "media_kind_of", "proxy_byte_limit",
]
