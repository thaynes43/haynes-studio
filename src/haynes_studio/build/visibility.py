"""Turn completed layered-render measurements into delivery run checks."""

import json
from hashlib import sha256

from haynes_studio.cache.keys import check_result_key
from haynes_studio.render.visibility import (
    THRESHOLDS, VISIBILITY_CHECK, VISIBILITY_OUTPUT, VISIBILITY_VERSION, verdict,
)
from haynes_studio.store import canonical_json, is_sha256

from .errors import BuildError


def visibility_check(cache, board, overrides):
    segment = board.segment
    document = segment.key.document
    declaration = document["visibility"]
    artifact = cache.lookup(segment.key, "video/mp4")
    invalid = BuildError("visibility.evidence_invalid", "The segment has no valid visibility evidence",
                         stage="checks", board_id=board.board_id)
    if artifact is None or artifact.sha256 != segment.content:
        raise invalid
    evidence = artifact.record.blobs[VISIBILITY_OUTPUT]
    with cache.store.open(evidence.locator) as handle:
        data = handle.read(8193)
    if len(data) > 8192 or sha256(data).hexdigest() != evidence.sha256:
        raise invalid
    try:
        rows = json.loads(data)
        frames = sorted(declaration["frames"])
        if not isinstance(rows, list) or len(rows) != len(frames):
            raise ValueError("Wrong number of measurements")
        poses = []
        for frame, row in zip(frames, rows, strict=True):
            support, visible = row["unoccluded_pixels"], row["visible_pixels"]
            if (type(row["frame"]) is not int or row["frame"] != frame
                    or not is_sha256(row["frame_sha256"])
                    or type(support) is not int or type(visible) is not int
                    or not 0 <= visible <= support <= document["width"] * document["height"]):
                raise ValueError("Invalid measurement")
            poses.append({"frame": frame, "frame_sha256": row["frame_sha256"],
                          "unoccluded_pixels": support, "lower_visible_pixels": visible,
                          "upper_visible_pixels": visible, "verdict": verdict(support, visible, visible)})
    except (KeyError, TypeError, ValueError) as error:
        raise invalid from error
    outcomes = {pose["verdict"] for pose in poses}
    outcome = next(value for value in ("hidden", "uncertain", "visible") if value in outcomes)
    measured = {"verdict": outcome, "poses": poses, "segment_sha256": segment.content,
                "segment_key": segment.key.value, "evidence_sha256": evidence.sha256}
    identity = sha256(canonical_json({
        "board_id": board.board_id, "measurement": measured, "version": VISIBILITY_VERSION,
        "thresholds": THRESHOLDS,
    })).hexdigest()
    override = overrides.get(identity) if outcome != "visible" else None
    result = "overridden" if override else "pass" if outcome == "visible" else "fail"
    return {
        "check": VISIBILITY_CHECK, "board_id": board.board_id, "slot": declaration["slot"],
        "result": result, "version": VISIBILITY_VERSION, "artifact": identity,
        "key": check_result_key(artifact=identity, check=VISIBILITY_CHECK,
                                version=VISIBILITY_VERSION, thresholds=THRESHOLDS).value,
        "measured": measured, "thresholds": THRESHOLDS,
        **({"override": override} if override else {}),
    }
