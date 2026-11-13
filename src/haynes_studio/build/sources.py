"""Clip sources for the two phases of a build (story 406), and the live hook.

The service phase and the offline phase are one build. The service phase is given the
clip sources that call the services (the Wan speech-to-video and image-to-video
clients) and stops once every clip is in the cache; the offline phase is the same
build given :class:`OfflineS2VSource` and :class:`OfflineClipSource`, which refuse
every call with ``build.offline_missing`` naming the artifact the cache lacks. So an
offline build of a story whose clips are all cached needs no client at all, and one
whose clips are not stops before anything is asked of a service.

:func:`live_clip_sources` is the one place the live clip sources are made (story 851):
the Wan clients of story 842 on the store's one journal (:mod:`.live`). Only the
command line calls it, and the client itself is made on the first clip request.

:class:`RecordingS2VSource` and :class:`RecordingClipSource` are the local pass's
sources (the build's first pass, before any clip is asked of a phase's sources): each
records the request the adapter built and raises :class:`ClipRequested` in place of a
clip, so the adapter commits nothing and the pass answers that clip with a stand-in.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haynes_studio.build.errors import OFFLINE_MISSING, BuildError
from haynes_studio.layered.source import S2VClip, S2VRequest, S2VSource
from haynes_studio.wholeframe.source import ClipRequest, ClipSource, SourceClip


@dataclass(frozen=True)
class ClipSources:
    """The clip sources one build uses: speech-to-video (layered) and image-to-video
    chains (whole-frame). Live sources (story 851) also give ``check``, run on every
    request of the local pass before any clip is asked for (it sends nothing), and
    ``stopped``, the stop a source latched while still returning a clip it kept (foreign
    work seen during a job whose clip passed its checks): the build ends ``held`` right
    after that clip is cached."""

    s2v: S2VSource
    i2v: ClipSource
    check: Callable[[S2VRequest | ClipRequest], None] | None = None
    stopped: Callable[[], BuildError | None] | None = None


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


def live_clip_sources(store_root: str | Path, *, story: str, runner: Any = None,
                      dry_run: bool = False,
                      client_options: Mapping[str, Any] | None = None) -> ClipSources:
    """The live clip sources of the service phase (and a full build): story 842's Wan
    clip client on the store's one journal, ``<store root>/wan-journal.jsonl``, through
    ``runner`` (the real ``kubectl exec`` runner when ``None``). ``story`` is the full
    work package URL the Wan ledger records each job under. With ``dry_run`` no client
    is made and the sources refuse every call; ``check`` still builds and checks every
    request. Making these sources contacts nothing and reads no journal: the client is
    made, and loads the journal, on the first clip request. ``client_options`` are the
    client's test hooks (``clock``, ``wall``, ``sleep``, ``new_job_id``). See
    :mod:`.live`; the offline phase never calls this."""
    from haynes_studio.build.live import live_sources  # noqa: PLC0415 - the hook's own module
    parts = live_sources(store_root, story=story, runner=runner, dry_run=dry_run,
                         client_options=client_options)
    clips = parts.clips
    return ClipSources(s2v=parts.s2v, i2v=parts.i2v, check=parts.check,
                       stopped=None if clips is None else (lambda: clips.stopped))


__all__ = ["ClipRequested", "ClipSources", "OfflineClipSource", "OfflineS2VSource",
           "RecordingClipSource", "RecordingS2VSource", "live_clip_sources", "offline_sources",
           "recording_sources"]
