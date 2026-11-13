"""Deliveries (contract section 8, story 381): a run's verified master and phone proxy,
published as one completed stage through the store, and legacy deliveries mapped
read-only from the Wan ledger.

- :mod:`.model`: the ``studio.delivery/v1`` model, media profiles and the proxy limit.
- :mod:`.validate`: :func:`validate_delivery`.
- :mod:`.media`: the master and proxy checks (:func:`inspect`) and the proxy encoder.
- :mod:`.publish`: :func:`deliver` and :func:`read_delivery`.
- :mod:`.legacy`: :func:`legacy_delivery`, a recorded Wan ledger as a read-only delivery.
- :mod:`.errors`: :class:`DeliveryError` and its codes.

Reference: ``docs/reference/studio-delivery.md``.
"""

from __future__ import annotations

from haynes_studio.delivery.model import (
    DELIVERY_SCHEMA,
    LEGACY_WAN_LEDGER,
    LOCAL,
    MASTER_SIZES,
    PROXY_LIMIT_BYTES,
    PROXY_SIZES,
    Delivery,
    LegacyLedger,
    MediaFile,
    StoreInfo,
    Verification,
    media_kind_of,
    proxy_byte_limit,
)
from haynes_studio.delivery.validate import validate_delivery
from haynes_studio.delivery.media import MediaReport, Problem, inspect, make_proxy
from haynes_studio.delivery.errors import (
    LEGACY_MISMATCH,
    MASTER_CHANGED,
    MASTER_INVALID,
    NOT_VERIFIED,
    PROXY_INVALID,
    RECORD_INVALID,
    DeliveryError,
)
from haynes_studio.delivery.publish import STAGE, deliver, read_delivery
from haynes_studio.delivery.legacy import legacy_delivery

__all__ = [
    "DELIVERY_SCHEMA", "Delivery", "DeliveryError", "LEGACY_MISMATCH", "LEGACY_WAN_LEDGER",
    "LOCAL", "LegacyLedger", "MASTER_CHANGED", "MASTER_INVALID", "MASTER_SIZES", "MediaFile",
    "MediaReport", "NOT_VERIFIED", "PROXY_INVALID", "PROXY_LIMIT_BYTES", "PROXY_SIZES",
    "Problem", "RECORD_INVALID", "STAGE", "StoreInfo", "Verification", "deliver", "inspect",
    "legacy_delivery", "make_proxy", "media_kind_of", "proxy_byte_limit", "read_delivery",
    "validate_delivery",
]
