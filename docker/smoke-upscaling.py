"""Exercise the contrib wheel, CPU inference and Unix HTTP with a toy graph."""

import hashlib
import os
import struct
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from haynes_studio.store import canonical_json
from haynes_studio.upscaling.backend import Engine
from haynes_studio.upscaling.profile import GRAPH_NAME, PROFILE_ID, PROVIDER, WHEELS, Profile, runtime_identity
from haynes_studio.upscaling.service import listening, local_call
from haynes_studio.upscaling.trial import frame


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


def node(name, op, inputs=(), **attrs):
    fields = message(1, name) + message(2, op)
    fields += b"".join(message(3, value) for value in inputs)
    fields += b"".join(message(5, message(1, key) + message(2, value)) for key, value in attrs.items())
    return message(1, fields)


def shape(*dimensions):
    return b"".join(message(2, integer(1, size)) for size in dimensions)


def list_of_ints(*values):
    return message(1, b"".join(integer(3, value) for value in values))


def synthetic_graph():
    # GraphDef: copy the luma input into four channels with a frozen 1x1
    # convolution, then rearrange the channels into a 2x nearest copy.
    float_type = integer(6, 1)
    tensor = integer(1, 1) + message(2, shape(1, 1, 1, 4)) + message(4, struct.pack("<4f", 1, 1, 1, 1))
    return (
        node("input", "Placeholder", dtype=float_type)
        + node("kernel", "Const", dtype=float_type, value=message(8, tensor))
        + node("conv", "Conv2D", ("input", "kernel"), T=float_type, strides=list_of_ints(1, 1, 1, 1),
               data_format=message(2, "NHWC"), padding=message(2, "VALID"))
        + node("output", "DepthToSpace", ("conv",), T=float_type,
               data_format=message(2, "NHWC"), block_size=integer(3, 2))
    )


def exercise(parent):
    graph = synthetic_graph()
    digest = hashlib.sha256(graph).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(graph)).encode() + b"\0" + graph, usedforsecurity=False).hexdigest()
    profile = Profile("sha256:" + "f" * 64, os.environ["STUDIO_UPSCALING_REVISION"], runtime_identity(),
                      len(graph), digest, blob)
    pin = profile.manifest()
    expected = hashlib.sha256(pin).hexdigest()
    with TemporaryDirectory(dir=parent) as work:
        scratch = Path(work)
        weights = scratch / "toy"
        weights.mkdir()
        (weights / "profile.json").write_bytes(pin)
        (weights / "profile.sha256").write_text(expected + "\n")
        (weights / GRAPH_NAME).write_bytes(graph)
        socket = scratch / "upscale.sock"
        rgb = Image.new("RGB", (540, 960), (87, 87, 87))
        outputs = []
        for settings in ("default", "compact-allocator"):
            memory = {}
            with Engine(scratch, weights, profile, smoke_settings=settings, memory=memory) as engine:
                with listening(socket, engine):
                    ready = engine.readiness
                    assert local_call(socket, "GET", "/v1/ready") == (200, ready)
                    assert ready["profile_id"] == PROFILE_ID and ready["provider"] == PROVIDER
                    assert (ready["profile_sha256"] == expected) == (settings == "default")
                    output, receipt = frame(scratch, socket, rgb, (1080, 1920), engine.profile, ready["profile_sha256"])
                    assert receipt["output"]["width"] == 1080 and receipt["output"]["height"] == 1920
                    outputs.append(output)
            assert memory["startup"][0]["peak_rss_bytes"]
            assert memory["requests"][0]["rss_after_bytes"]
        assert outputs[0] == outputs[1]
        return {"graph": "synthetic_luma_pixel_shuffle", "graph_sha256": digest,
                "output_sha256": hashlib.sha256(outputs[0]).hexdigest(),
                "provider": PROVIDER, "allocator_byte_match": True}


def main():
    assert os.geteuid() == os.getegid() == 10001
    assert os.statvfs("/").f_flag & os.ST_RDONLY
    assert not any(Path("/weights").iterdir())
    assert sys.version_info[:2] == (3, 12)
    recorded = {}
    for line in Path("/opt/studio/upscaling-wheels.sha256").read_text().splitlines():
        digest, name = line.split()
        recorded[Path(name).name] = digest
    assert recorded == {filename: digest for _, filename, digest in WHEELS.values()}
    evidence = exercise("/upscaling")
    print(canonical_json(evidence).decode())


if __name__ == "__main__":
    main()
