"""Create-only build staging in a separate, shared filesystem directory."""

import stat
from pathlib import Path

from haynes_studio.canonical.ids import is_id
from haynes_studio.delivery.publish import STAGE
from haynes_studio.store import MISSING, LocalStore, StoreError
from haynes_studio.store.errors import BLOB_MISSING


class BuildStageStore(LocalStore):
    """Write to one run's staging directory and read authoritative inputs on misses."""

    def __init__(self, root, run_id, source, *, create=False):
        if not is_id(run_id, "run"):
            raise ValueError("Build staging requires a canonical run ID")
        path = Path(root) / run_id
        if create:
            path.mkdir(mode=0o770, exist_ok=True)
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise OSError("Expected a build staging directory")
        super().__init__(path)
        self.source = source

    def open(self, locator):
        try:
            return super().open(locator)
        except StoreError as error:
            if error.code != BLOB_MISSING:
                raise
        return self.source.open(locator)

    def verify(self, locator, sha256):
        status = super().verify(locator, sha256)
        return self.source.verify(locator, sha256) if status == MISSING else status


def publish_staged_delivery(staging, store, production_id, run_id):
    """The API publishes the verified delivery stage and its blobs create-only."""
    stage = staging.stage_record(production_id, run_id, STAGE, verify=True)
    if stage is None:
        raise OSError("The build delivery stage is missing")
    for blob in stage.blobs.values():
        with staging.open(blob.locator) as source:
            store.publish(source, scope=production_id, media_type=blob.media_type,
                          expected_sha256=blob.sha256)
    store.complete_stage(stage)
