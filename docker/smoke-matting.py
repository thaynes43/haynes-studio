"""Exercise the packaged ORT and the local service with a generated toy graph."""

import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import onnxruntime

from haynes_studio.matting.backend import Engine, verify_result
from haynes_studio.matting.pixels import encode_png
from haynes_studio.matting.profile import (
    DIM, GRAPH_NAME, INPUT_NAME, OUTPUT_NAME, PROFILE_ID, PROVIDER, RUNTIME_VERSION,
    WHEEL_NAME, WHEEL_SHA256, Profile,
)
from haynes_studio.matting.service import listening, local_call
from haynes_studio.matting.smoke import _request


def varint(number):
    encoded = bytearray()
    while number >= 128:
        encoded.append((number & 127) | 128)
        number >>= 7
    encoded.append(number)
    return bytes(encoded)


def integer(field, value):
    return varint(field << 3) + varint(value)


def message(field, data):
    if isinstance(data, str):
        data = data.encode("ascii")
    return varint((field << 3) | 2) + varint(len(data)) + data


def tensor_info(name, shape):
    dimensions = b"".join(message(1, integer(1, size)) for size in shape)
    tensor = integer(1, 1) + message(2, dimensions)  # TensorProto.FLOAT
    return message(1, name) + message(2, message(1, tensor))


def synthetic_graph():
    # ONNX protobuf, IR 8, opset 13. ReduceMean over channels keeps the
    # spatial dimensions, yielding a foreground and background from RGB.
    axes = message(1, "axes") + integer(8, 1) + integer(20, 7)  # AttributeProto.INTS
    node = message(1, INPUT_NAME) + message(2, OUTPUT_NAME) + message(4, "ReduceMean") + message(5, axes)
    graph = (message(1, node) + message(2, "synthetic_channel_mean")
             + message(11, tensor_info(INPUT_NAME, [1, 3, DIM, DIM]))
             + message(12, tensor_info(OUTPUT_NAME, [1, 1, DIM, DIM])))
    return integer(1, 8) + message(7, graph) + message(8, integer(2, 13))


def exercise_graph(scratch_parent, revision):
    graph = synthetic_graph()
    profile = Profile("sha256:" + "f" * 64, revision, len(graph), hashlib.sha256(graph).hexdigest())
    with TemporaryDirectory(dir=scratch_parent) as work:
        scratch = Path(work)
        weights = scratch / "fake-weights"
        weights.mkdir()
        manifest = profile.manifest()
        digest = hashlib.sha256(manifest).hexdigest()
        (weights / "profile.json").write_bytes(manifest)
        (weights / "profile.sha256").write_text(digest + "\n")
        (weights / GRAPH_NAME).write_bytes(graph)
        socket = scratch / "matte.sock"
        with Engine(scratch, weights, profile) as engine, listening(socket, engine):
            assert local_call(socket, "GET", "/v1/ready") == (200, {
                "profile_id": PROFILE_ID, "profile_sha256": digest, "provider": PROVIDER,
            })
            rgb = np.zeros((64, 64, 3), dtype=np.uint8)
            rgb[8:56, 8:56] = 255
            request = _request(scratch, encode_png(rgb), 64, 64, digest)
            status, receipt = local_call(socket, "POST", "/v1/matte", request)
            assert status == 200, receipt
            directory = scratch / request["attempt_id"]
            artifacts = {name: (directory / (name + ".png")).read_bytes()
                         for name in ("cutout", "mask")}
            verify_result(request["request"], receipt, artifacts, profile)
            assert receipt["shape"]["bbox_xyxy"] == [8, 8, 56, 56]


def main():
    assert os.geteuid() == os.getegid() == 10001
    assert os.statvfs("/").f_flag & os.ST_RDONLY
    assert not any(Path("/weights").iterdir())
    assert sys.version_info[:2] == (3, 12)
    assert importlib.metadata.version("onnxruntime") == onnxruntime.__version__ == RUNTIME_VERSION
    wheel_hash, wheel_name = Path("/opt/studio/onnxruntime-wheel.sha256").read_text().split()
    assert (wheel_name, wheel_hash) == (WHEEL_NAME, WHEEL_SHA256)
    exercise_graph("/matting", os.environ["STUDIO_MATTING_REVISION"])
    print(json.dumps({"runtime_version": RUNTIME_VERSION, "wheel_sha256": wheel_hash,
                      "provider": PROVIDER, "graph": "synthetic_channel_mean",
                      "proof": "CPU session, Unix HTTP, PNG and receipt read-back",
                      "pending": "real weight load, quality, RSS, timing and deployment"}))


if __name__ == "__main__":
    main()
