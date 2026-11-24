"""Create-only build staging in a separate, shared filesystem directory."""

import stat
from pathlib import Path

from haynes_studio.build.live import KEPT, KEPT_RECORD, S2V_STAGE
from haynes_studio.canonical.ids import is_id
from haynes_studio.delivery.publish import STAGE
from haynes_studio.layered.s2v import RECORD_STAGE
from haynes_studio.store import MISSING, PRESENT, LocalStore, StoreError
from haynes_studio.store.errors import BLOB_MISSING


class BuildStageStore(LocalStore):
    """Write to one run's staging directory and read authoritative inputs on misses."""

    def __init__(self, root, run_id, source, *, create=False, earlier_runs=()):
        if not is_id(run_id, "run"):
            raise ValueError("Build staging requires a canonical run ID")
        path = Path(root) / run_id
        if create:
            path.mkdir(mode=0o770, exist_ok=True)
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise OSError("Expected a build staging directory")
        super().__init__(path)
        self.source = source
        self.stage_root = Path(root)
        self.earlier_runs = frozenset(earlier_runs)

    def stage_record(self, production_id, run_id, stage, *, verify=True):
        if run_id not in self.earlier_runs:
            return super().stage_record(production_id, run_id, stage, verify=verify)
        if stage.partition("-")[0] not in (KEPT, KEPT_RECORD, S2V_STAGE, RECORD_STAGE):
            return None
        try:
            previous = BuildStageStore(self.stage_root, run_id, self.source)
        except FileNotFoundError:
            return None
        record = previous.stage_record(production_id, run_id, stage)
        if record is not None:
            # Store callers open by locator alone. Copy verified old clip bytes
            # into this run's staging so those lookups remain self-contained.
            for blob in record.blobs.values():
                if self.verify(blob.locator, blob.sha256) != PRESENT:
                    with previous.open(blob.locator) as source:
                        self.publish(source, scope=production_id, media_type=blob.media_type,
                                     expected_sha256=blob.sha256)
        return record

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
