"""Facts a board or story document cannot show by itself, passed in explicitly.

The asset library (story 382), voice and photo jobs (story 405) and the API (story
409) own these records. Story 404 takes only the facts its rules and derived values
need, so the model stays free of files, services and storage:

- a voice version's measured takes (line ID to ``duration_ms``, rule TIME-1) and
  whether its signature still matches the board (VOICE-3, VOICE-4);
- whether a photo version still matches the board's photo inputs;
- which boards have a voice or photo job running;
- each asset version's capabilities (``asset.capability_mismatch``).

An empty :class:`Facts` means "the library knows nothing": every voice or photo a
board names is then ``absent``, which blocks ``queue_run`` (fail closed).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

VOICE = "voice"
PHOTO = "photo"


@dataclass(frozen=True, slots=True)
class VoiceVersionFacts:
    """One ``board_voice`` asset version: its takes and whether it is the board's
    current signature. ``takes_ms`` maps line ID to the measured duration."""

    id: str
    takes_ms: Mapping[str, int]
    matches_board: bool = True


@dataclass(frozen=True, slots=True)
class PhotoVersionFacts:
    id: str
    matches_board: bool = True


@dataclass(frozen=True, slots=True)
class Facts:
    voice_versions: Mapping[str, VoiceVersionFacts] = field(
        default_factory=lambda: MappingProxyType({}))
    photo_versions: Mapping[str, PhotoVersionFacts] = field(
        default_factory=lambda: MappingProxyType({}))
    generating: frozenset[tuple[str, str]] = frozenset()  # (board_id, "voice" | "photo")
    capabilities: Mapping[str, frozenset[str]] = field(
        default_factory=lambda: MappingProxyType({}))

    @classmethod
    def build(cls, *, voices: Iterable[VoiceVersionFacts] = (),
              photos: Iterable[PhotoVersionFacts] = (),
              generating: Iterable[tuple[str, str]] = (),
              capabilities: Mapping[str, Iterable[str]] | None = None) -> Facts:
        return cls(
            voice_versions=MappingProxyType({v.id: v for v in voices}),
            photo_versions=MappingProxyType({p.id: p for p in photos}),
            generating=frozenset(generating),
            capabilities=MappingProxyType({key: frozenset(value) for key, value
                                           in (capabilities or {}).items()}),
        )

    def merged(self, other: Facts) -> Facts:
        """These facts with ``other``'s added (``other`` wins on the same ID)."""
        return Facts(
            voice_versions=MappingProxyType({**self.voice_versions, **other.voice_versions}),
            photo_versions=MappingProxyType({**self.photo_versions, **other.photo_versions}),
            generating=self.generating | other.generating,
            capabilities=MappingProxyType({**self.capabilities, **other.capabilities}),
        )


NO_FACTS = Facts()
