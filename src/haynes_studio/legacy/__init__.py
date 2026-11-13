"""Read-only adapters for the PoC's legacy files: the title manifest
(``legacy.manifest/v1``), its ``speech.json``, and the timeline they make.

Nothing here writes a legacy file. The canonical model and the legacy-to-canonical
import are story 404's; they build on these modules.
"""

from haynes_studio.legacy.manifest import (
    SCHEMA_NAME,
    LegacyManifest,
    detect,
    from_document,
    load,
    validate,
)
from haynes_studio.legacy.speech import LegacySpeech, load_speech, pair, speech_from_document
from haynes_studio.legacy.timeline import Comparison, LegacyTimeline, compare, compute


def validate_manifest(document, *, context="read"):
    """The contract harness's validator for type ``legacy.manifest``."""
    return validate(document, context=context)


__all__ = [
    "SCHEMA_NAME",
    "Comparison",
    "LegacyManifest",
    "LegacySpeech",
    "LegacyTimeline",
    "compare",
    "compute",
    "detect",
    "from_document",
    "load",
    "load_speech",
    "pair",
    "speech_from_document",
    "validate",
    "validate_manifest",
]
