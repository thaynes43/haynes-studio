"""Clip sources for the two phases of a build (story 406), and the live hook.

The service phase and the offline phase are one build. The service phase is given the
clip sources that call the services (the Wan speech-to-video and image-to-video
clients) and stops once every clip is in the cache; the offline phase is the same
build given :class:`OfflineS2VSource` and :class:`OfflineClipSource`, which refuse
every call with ``build.offline_missing`` naming the artifact the cache lacks. So an
offline build of a story whose clips are all cached needs no client at all, and one
whose clips are not stops before anything is asked of a service.

:func:`live_clip_sources` is the one place the live clients will be made. Story 842's
Wan clients are not on ``main`` yet, so it raises ``build.clip_sources_unwired``; a
later story fills it. Nothing below the command line constructs a live client.

:class:`RecordingS2VSource` and :class:`RecordingClipSource` are the local pass's
sources (the build's first pass, before any clip is asked of a phase's sources): each
records the request the adapter built and raises :class:`ClipRequested` in place of a
clip, so the adapter commits nothing and the pass answers that clip with a stand-in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from haynes_studio.build.errors import CLIP_SOURCES_UNWIRED, OFFLINE_MISSING, BuildError
from haynes_studio.layered.source import S2VClip, S2VRequest, S2VSource
from haynes_studio.wholeframe.source import ClipRequest, ClipSource, SourceClip


@dataclass(frozen=True)
class ClipSources:
    """The clip sources one build uses: speech-to-video (layered) and image-to-video
    chains (whole-frame)."""

    s2v: S2VSource
    i2v: ClipSource


class OfflineS2VSource(S2VSource):
    """Refuses every speech-to-video request: the offline phase calls no service."""

    name = "offline"

    def generate(self, request: S2VRequest) -> S2VClip:
        raise BuildError(OFFLINE_MISSING, f"the speech-to-video clip {request.key} (drive track "
                         f"{request.drive_track_sha256[:12]}..., seed {request.seed}) is not in "
                         "the cache; the offline phase calls no service: run `studio build "
                         "--phase service` first", stage="s2v_clip")


class OfflineClipSource(ClipSource):
    """Refuses every image-to-video request: the offline phase calls no service."""

    name = "offline"

    def generate(self, request: ClipRequest) -> Sequence[SourceClip]:
        raise BuildError(OFFLINE_MISSING, f"the whole-frame clips {request.key} (photo "
                         f"{request.photo_sha256[:12]}..., seed {request.seed}) are not in the "
                         "cache; the offline phase calls no service: run `studio build --phase "
                         "service` first", stage="whole_frame_clip")


def offline_sources() -> ClipSources:
    return ClipSources(s2v=OfflineS2VSource(), i2v=OfflineClipSource())


class ClipRequested(Exception):
    """A recording source's answer: the request it would have sent, never a clip."""

    def __init__(self, request: S2VRequest | ClipRequest):
        super().__init__(request.key)
        self.request = request


class RecordingS2VSource(S2VSource):
    """Records each speech-to-video request and raises :class:`ClipRequested`: the
    local pass's source, which asks no service."""

    name = "studio.build.local-pass"

    def __init__(self) -> None:
        self.requests: list[S2VRequest] = []

    def generate(self, request: S2VRequest) -> S2VClip:
        self.requests.append(request)
        raise ClipRequested(request)


class RecordingClipSource(ClipSource):
    """Records each whole-frame request and raises :class:`ClipRequested`: the local
    pass's source, which asks no service."""

    name = "studio.build.local-pass"

    def __init__(self) -> None:
        self.requests: list[ClipRequest] = []

    def generate(self, request: ClipRequest) -> Sequence[SourceClip]:
        self.requests.append(request)
        raise ClipRequested(request)


def recording_sources() -> ClipSources:
    return ClipSources(s2v=RecordingS2VSource(), i2v=RecordingClipSource())


def live_clip_sources() -> ClipSources:
    """The live clip sources of the service phase: the Wan clients of story 842, each
    through the Wan API's compute lease. **Not wired yet**: story 842 is in review, and
    a later story fills this hook once it merges. Until then the service phase stops
    here with ``build.clip_sources_unwired``; the offline phase never calls it."""
    raise BuildError(CLIP_SOURCES_UNWIRED, "the live clip sources are not wired yet: the Wan "
                     "clip clients (story 842) are not on main. Build from cached clips with "
                     "`studio build --offline`", stage="service")


__all__ = ["ClipRequested", "ClipSources", "OfflineClipSource", "OfflineS2VSource",
           "RecordingClipSource", "RecordingS2VSource", "live_clip_sources", "offline_sources",
           "recording_sources"]
