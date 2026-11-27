"""Turn completed layered-render measurements into delivery run checks."""

from hashlib import sha256

from haynes_studio.cache.artifacts import INPUTS, JSON
from haynes_studio.cache.keys import FILM_PICTURE, MASTER, SCHEME, SEGMENT, check_result_key
from haynes_studio.jsonio import parse_strict
from haynes_studio.render.visibility import (
    MEASUREMENT_STAGE, THRESHOLDS, VISIBILITY_CHECK, VISIBILITY_OUTPUT, VISIBILITY_VERSION, verdict,
)
from haynes_studio.store import StoreError, canonical_json, is_sha256

from .errors import BuildError

MP4 = "video/mp4"
KEY_INPUTS_MAX_BYTES = 16 * 1024 * 1024
EVIDENCE_MAX_BYTES = 8192


def visibility_check(cache, board, overrides):
    segment = board.segment
    artifact = cache.lookup(segment.key, MP4)
    if artifact is None or artifact.sha256 != segment.content:
        raise _invalid_evidence(board.board_id)
    return _segment_check(cache.store, board.board_id, segment.key.value, artifact.record,
                          segment.key.document, overrides)


def _invalid_evidence(board_id):
    return BuildError("visibility.evidence_invalid", "The segment has no valid visibility evidence",
                      stage="checks", board_id=board_id)


def _segment_check(store, board_id, key, record, document, overrides):
    declaration = document["visibility"]
    evidence = record.blobs.get(VISIBILITY_OUTPUT)
    try:
        rows = _read_json(store, evidence, EVIDENCE_MAX_BYTES)
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
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise _invalid_evidence(board_id) from error
    outcomes = {pose["verdict"] for pose in poses}
    outcome = next(value for value in ("hidden", "uncertain", "visible") if value in outcomes)
    measured = {"measurement_stage": MEASUREMENT_STAGE, "verdict": outcome, "poses": poses,
                "segment_sha256": record.blobs[SEGMENT].sha256, "segment_key": key,
                "evidence_sha256": evidence.sha256}
    identity = sha256(canonical_json({
        "board_id": board_id, "measurement": measured, "version": VISIBILITY_VERSION,
        "thresholds": THRESHOLDS,
    })).hexdigest()
    override = overrides.get(identity) if outcome == "uncertain" else None
    result = "overridden" if override else "pass" if outcome == "visible" else "fail"
    return {
        "check": VISIBILITY_CHECK, "board_id": board_id, "slot": declaration["slot"],
        "result": result, "version": VISIBILITY_VERSION, "artifact": identity,
        "key": check_result_key(artifact=identity, check=VISIBILITY_CHECK,
                                version=VISIBILITY_VERSION, thresholds=THRESHOLDS).value,
        "measured": measured, "thresholds": THRESHOLDS,
        **({"override": override} if override else {}),
    }


def _read_json(store, blob, limit):
    if blob is None or blob.media_type != JSON or blob.bytes > limit:
        raise ValueError("Missing or oversized JSON blob")
    with store.open(blob.locator) as handle:
        data = handle.read(blob.bytes + 1)
    if len(data) != blob.bytes or sha256(data).hexdigest() != blob.sha256:
        raise ValueError("JSON blob does not match its recorded bytes")
    return parse_strict(data.decode("utf-8"))


def _staged_artifact(store, production_id, run_id, kind, key, digest):
    if not isinstance(key, str) or not key.startswith("sha256:"):
        raise ValueError("Missing staged artifact identity")
    key_hash = key.removeprefix("sha256:")
    if not is_sha256(key_hash):
        raise ValueError("Invalid staged cache key")
    # Delivery has verified the master bytes. Follow the completed records' video
    # hashes and rehash the input and measurement JSON before using their contents.
    record = store.stage_record(production_id, run_id, f"{kind}-{key_hash}", verify=False)
    if record is None:
        raise ValueError("Missing staged artifact record")
    artifact, inputs = record.blobs[kind], record.blobs[INPUTS]
    if artifact.sha256 != digest or artifact.media_type != MP4 or inputs.sha256 != key_hash:
        raise ValueError("The staged artifact differs from its completion record")
    document = _read_json(store, inputs, KEY_INPUTS_MAX_BYTES)
    if document["kind"] != kind or document["scheme"] != SCHEME:
        raise ValueError("Wrong staged artifact inputs")
    return record, document


def staged_visibility_checks(store, production_id, run_id, frozen, stages, outputs, master_sha256):
    """Follow the completed master and splice cache records to the measured segments."""
    admission = frozen["visibility_admission"]
    pins = admission["boards"]
    board_order = frozen["story"]["board_order"]
    try:
        keys = outputs["keys"]
        _, master = _staged_artifact(store, production_id, run_id, MASTER, keys["master"], master_sha256)
        _, picture = _staged_artifact(store, production_id, run_id, FILM_PICTURE, keys["film_picture"],
                                     master["picture"])
        if master["picture"] != outputs["picture_sha256"] or len(stages) != len(board_order):
            raise ValueError("The staged picture differs from the recorded boards")

        checks = {}
        for board_id, stage, segment in zip(board_order, stages, picture["segments"], strict=True):
            if (stage["board_id"] != board_id or stage["segment_sha256"] != segment["segment"]
                    or stage["frames"] != segment["frames"]):
                raise ValueError("The staged splice differs from the recorded board segment")
            if board_id in pins:
                key = stage["segment_key"]
                record, document = _staged_artifact(store, production_id, run_id, SEGMENT, key, segment["segment"])
                if document["visibility"] != {**pins[board_id], "version": VISIBILITY_VERSION}:
                    raise ValueError("The segment differs from the admitted poses and cast slot")
                checks[board_id] = _segment_check(store, board_id, key, record, document,
                                                  admission.get("overrides", {}))
        return checks
    except (KeyError, TypeError, ValueError, RecursionError, OSError, StoreError) as error:
        raise _invalid_evidence(None) from error
