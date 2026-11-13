"""Picture through the cache (story 380): board segments and the film picture.

:class:`PictureBuilder` is a ``content`` source for :func:`~haynes_studio.cache.plan.plan_story`.
For a segment key it returns the cached segment's hash, or renders the board with the
:class:`~haynes_studio.render.base.SegmentRenderer`, encodes it and commits it; for a
film picture key it returns the cached film, or splices the cached segments the key
lists. Every other artifact (takes, tracks, clips, the mix and the master) comes from
``upstream``, which a real build points at its adapters (stories 426, 427, 381, 406)
and a test at a stand-in.

A second build of an unchanged story renders nothing: every segment and the film are
hits, read from completed records. After one board edit, exactly that board's segment
is a miss.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import BinaryIO

from haynes_studio.cache.artifacts import ArtifactCache, CachedArtifact
from haynes_studio.cache.errors import ENTRY_INVALID, CacheError
from haynes_studio.cache.keys import FILM_PICTURE, SEGMENT, CacheKey
from haynes_studio.render.base import SegmentRenderer, SegmentRequest
from haynes_studio.render.encode import EncoderSettings, encode_segment, probe_segment
from haynes_studio.render.errors import CONSERVATION
from haynes_studio.render.splice import SpliceInput, splice
from haynes_studio.store import blob_locator

MP4 = "video/mp4"


class PictureBuilder:
    """Makes segments and film pictures through ``cache`` (see the module docstring).
    ``open_input`` reads a key input by hash, for a renderer that needs bytes."""

    def __init__(self, cache: ArtifactCache, renderer: SegmentRenderer, *,
                 encoder: EncoderSettings | None = None,
                 upstream: Callable[[CacheKey], str] | None = None,
                 open_input: Callable[[str], BinaryIO] | None = None):
        self.cache = cache
        self.renderer = renderer
        self.encoder = encoder or EncoderSettings()
        self.upstream = upstream
        self.open_input = open_input
        self.rendered: list[str] = []  # segment keys this builder rendered, in order
        self.spliced: list[str] = []  # film picture keys this builder spliced

    def __call__(self, key: CacheKey) -> str:
        if key.kind == SEGMENT:
            return self.segment(key).sha256
        if key.kind == FILM_PICTURE:
            return self.film_picture(key).sha256
        if self.upstream is None:
            raise LookupError(f"no source for {key.kind} artifacts")
        return self.upstream(key)

    def segment(self, key: CacheKey) -> CachedArtifact:
        """The board's segment: a hit, or rendered, encoded, checked and committed."""
        document = key.document
        if document["compositor"] != self.renderer.compositor:
            raise CacheError(ENTRY_INVALID, f"the key names compositor {document['compositor']!r}, "
                             f"the renderer is {self.renderer.compositor!r}", where=key.value)
        if dict(document["encoder"]) != self.encoder.key_inputs():
            raise CacheError(ENTRY_INVALID, "the key names other encoder settings than this "
                             "builder's", where=key.value)
        return self.cache.get_or_make(key, lambda: self._render(key), MP4)

    def _render(self, key: CacheKey) -> bytes:
        request = SegmentRequest(key=key.value, inputs=key.document, open_input=self.open_input)
        data = encode_segment(self.renderer.render(request), frames_expected=request.frames,
                              width=request.width, height=request.height, fps=request.fps,
                              settings=self.encoder)
        if probe_segment(data, fps=request.fps).frames != request.frames:
            raise CacheError(CONSERVATION, "the encoded segment does not hold the board's frames "
                             "(TIME-11)", where=key.value)
        self.rendered.append(key.value)
        return data

    def film_picture(self, key: CacheKey, *, fps: int = 24) -> CachedArtifact:
        """The film picture: a hit, or the key's segments spliced in order and
        committed. Each segment is read from the production's folder by its hash."""
        return self.cache.get_or_make(key, lambda: self._splice(key, fps), MP4)

    def _splice(self, key: CacheKey, fps: int) -> bytes:
        store, production = self.cache.store, self.cache.production_id
        inputs = []
        try:
            for index, item in enumerate(key.document["segments"]):
                handle = store.open(blob_locator(production, item["segment"], MP4))
                inputs.append(SpliceInput(handle, item["frames"], label=f"segment {index}"))
            data = splice(inputs, fps=fps)
        finally:
            for item in inputs:
                item.source.close()  # type: ignore[union-attr]
        self.spliced.append(key.value)
        return data
