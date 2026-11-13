"""The layered stages as one ``upstream`` for a build (story 426).

:class:`LayeredStages` answers the plan's layered keys: drive tracks
(:class:`~.drive.DriveTracks`), speech-to-video clips (:class:`~.s2v.S2VClips`) and keyed
frames (:class:`~.keyed.KeyedFrames`), all on one
:class:`~haynes_studio.cache.artifacts.ArtifactCache`. Any other kind is
:class:`LookupError`, so a build composes it with the other adapters' stages.
:func:`reader` opens a blob by hash from the scopes and media types a stage reads.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import BinaryIO

from haynes_studio.cache.artifacts import ArtifactCache
from haynes_studio.cache.keys import KEYED_FRAMES, S2V_CLIP, S2V_DRIVE_TRACK, CacheKey
from haynes_studio.layered.drive import DriveTracks
from haynes_studio.layered.keyed import KeyedFrames
from haynes_studio.layered.s2v import S2VClips
from haynes_studio.layered.source import S2VSource
from haynes_studio.store import BLOB_MISSING, Store, StoreError, blob_locator

MEDIA = ("video/mp4", "image/png", "image/jpeg", "image/webp", "audio/wav", "application/json")


def reader(store: Store, scopes: Sequence[str], media_types: Sequence[str] = MEDIA
           ) -> Callable[[str], BinaryIO]:
    """Opens the first blob of ``sha256`` the store holds in ``scopes`` (production IDs
    or ``library``) under ``media_types``, else ``store.blob_missing``. The caller
    re-hashes what it reads."""

    def open_input(sha256: str) -> BinaryIO:
        for scope in scopes:
            for media_type in media_types:
                try:
                    return store.open(blob_locator(scope, sha256, media_type))
                except StoreError as error:
                    if error.code != BLOB_MISSING:
                        raise
        raise StoreError(BLOB_MISSING, f"no blob {sha256} in {', '.join(scopes)}")
    return open_input


class LayeredStages:
    """Drive tracks, S2V clips and keyed frames through ``cache``. ``read`` opens any
    input by hash (takes, drive tracks, start images, clips, decal stills)."""

    def __init__(self, cache: ArtifactCache, source: S2VSource, *,
                 read: Callable[[str], BinaryIO]):
        self.drive = DriveTracks(cache, read_take=read)
        self.clips = S2VClips(cache, source, read_drive=read, read_image=read)
        self.keyed = KeyedFrames(cache, read_clip=read, read_still=read)
        self.routes = {S2V_DRIVE_TRACK: self.drive, S2V_CLIP: self.clips, KEYED_FRAMES: self.keyed}

    def handles(self, key: CacheKey) -> bool:
        return key.kind in self.routes

    def __call__(self, key: CacheKey) -> str:
        stage = self.routes.get(key.kind)
        if stage is None:
            raise LookupError(f"the layered stages make no {key.kind} artifacts")
        return stage(key)

    @property
    def made(self) -> dict[str, list[str]]:
        """Keys each stage made in this build (a hit makes nothing)."""
        return {"drive": list(self.drive.made), "s2v_clip": list(self.clips.made),
                "keyed": list(self.keyed.made)}


__all__ = ["LayeredStages", "MEDIA", "reader"]
