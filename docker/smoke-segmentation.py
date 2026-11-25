"""Exercise the pinned CPU runtime and Unix service with synthetic Torch modules."""

from pathlib import Path
from types import SimpleNamespace
import json
import os
import ssl
import sys

import numpy as np
from PIL import Image

from haynes_studio.segmentation.backend import Engine
from haynes_studio.segmentation.fixtures import Fixture
from haynes_studio.segmentation.pixels import describe_mask
from haynes_studio.segmentation.profile import IMAGE, RUNTIME_PINS, SERVING_PROFILE_ID, Profile, digest
from haynes_studio.segmentation.runtime import DINO, SAM, cpu_runtime
from haynes_studio.segmentation.service import listening, local_call
from haynes_studio.segmentation.smoke import stage
from haynes_studio.store import canonical_json


VOCAB = b"[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nprop\n.\n"


class SyntheticProfile(Profile):
    def model_files(self):
        weight = tensor_bytes()
        return tuple({
            "directory": name, "repository": f"synthetic/{name}", "revision": "0" * 40,
            "files": [{"name": "model.safetensors", "size_bytes": len(weight), "sha256": digest(weight)}]
            + ([{"name": "vocab.txt", "size_bytes": len(VOCAB), "sha256": digest(VOCAB)}] if name == "dino" else []),
        } for name in ("dino", "sam"))


def tensor_bytes():
    # Safetensors header plus a single application-generated FP32 value.
    metadata = b'{"scale":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}'
    metadata = metadata.ljust(64)
    return len(metadata).to_bytes(8, "little") + metadata + b"\x00\x00\x80\x3f"


def factory(weights, phase, strategy):
    with phase("runtime_import"):
        torch = cpu_runtime()
        from safetensors.torch import load_file
        from transformers import (
            BertTokenizer, GroundingDinoForObjectDetection, GroundingDinoImageProcessor,
            GroundingDinoProcessor, Sam2ImageProcessor, Sam2Model, Sam2Processor,
        )
        import torchvision

        assert GroundingDinoForObjectDetection and Sam2Model
        assert not torch.cuda.is_available()
        assert (torch.get_num_threads(), torch.get_num_interop_threads()) == (2, 1)
        assert torchvision.ops.nms(torch.tensor([[0.0, 0.0, 1.0, 1.0]]), torch.tensor([1.0]), 0.5).item() == 0
        import socket

        try:
            socket.socket(socket.AF_INET)
        except PermissionError:
            pass
        else:
            raise AssertionError("INET sockets must be denied inside the model process")

    class BoxModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("scale", torch.zeros(1))

        def forward(self, pixel_values, input_ids, **rest):
            scores = torch.full((1, 1, input_ids.shape[1]), -8.0)
            scores[0, 0, 1] = 8.0 * self.scale
            return SimpleNamespace(
                logits=scores, pred_boxes=torch.tensor([[[0.5, 0.5, 0.5, 0.5]]]) * self.scale,
            )

    class MaskModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("scale", torch.zeros(1))

        def forward(self, pixel_values, **rest):
            mask = (pixel_values[:, :1] - 0.5) * self.scale
            return SimpleNamespace(pred_masks=mask[:, None], iou_scores=torch.tensor([[[0.95]]]))

    with phase("load_dino"):
        dino_model = BoxModel()
        dino_model.load_state_dict(load_file(weights / "dino/model.safetensors", device="cpu"))
        vocab = weights / "dino/vocab.txt"
        # The vocabulary is a fixture input, generated in scratch. Production
        # startup instead runs the exact pinned configuration from /opt/studio-models.
        tokenizer = BertTokenizer(vocab={
            token: index for index, token in enumerate(vocab.read_text().splitlines())
        })
        dino = DINO(torch, GroundingDinoProcessor(
            GroundingDinoImageProcessor(size={"shortest_edge": 64, "longest_edge": 64}), tokenizer,
        ), dino_model.eval())
    with phase("load_sam"):
        sam_model = MaskModel()
        sam_model.load_state_dict(load_file(weights / "sam/model.safetensors", device="cpu"))
        sam = SAM(torch, Sam2Processor(Sam2ImageProcessor(
            size={"height": 64, "width": 64}, do_normalize=False,
        )), sam_model.eval())
    return dino, sam


def main():
    assert os.geteuid() == os.getegid() == 10001
    assert os.statvfs("/").f_flag & os.ST_RDONLY
    assert not any(Path("/opt/studio-models").iterdir())
    assert sys.version_info[:2] == (3, 12)
    assert ssl.create_default_context().get_ca_certs()
    os.environ["STUDIO_SEGMENTATION_IMAGE"] = IMAGE + "@sha256:" + "1" * 64
    installed = Profile.installed()
    wheel_hashes = dict(line.split()[::-1] for line in
                        Path("/opt/studio/segmentation-wheels.sha256").read_text().splitlines())
    actual = set(wheel_hashes.values())
    assert {wheel_hash for _, wheel_hash in RUNTIME_PINS.values()} <= actual
    profile = SyntheticProfile(installed.image_digest, installed.revision, installed.lock_sha256, installed.libraries)
    scratch = Path("/segmentation")
    weights = scratch / "fake-weights"
    (weights / "dino").mkdir(parents=True)
    (weights / "sam").mkdir()
    for model in ("dino", "sam"):
        (weights / model / "model.safetensors").write_bytes(tensor_bytes())
    (weights / "dino/vocab.txt").write_bytes(VOCAB)
    (weights / "profile.json").write_bytes(profile.manifest())
    pin = digest(profile.manifest())
    (weights / "profile.sha256").write_text(pin + "\n")
    pixels = np.zeros((64, 64), dtype=bool)
    pixels[16:48, 16:48] = True
    image = Image.fromarray(pixels.astype(np.uint8) * 255).convert("RGB")
    fixture = Fixture(image, pixels, "prop", "prop", None)
    data, request = fixture.request("synthetic")
    socket_path = scratch / "segment.sock"
    with Engine(scratch, weights, profile, factory=factory) as engine, listening(socket_path, engine):
        assert local_call(socket_path, "GET", "/v1/ready") == (200, {
            "profile_id": SERVING_PROFILE_ID, "profile_sha256": pin, "device": "cpu",
        })
        for hint in (None, {"kind": "point", "xy": [24, 24]}, {"kind": "box", "xyxy": [16, 16, 48, 48]}):
            payload = stage(scratch, data, {**request, "hint": hint})
            status, reply = local_call(socket_path, "POST", "/v1/segment", payload)
            result = reply["result"]
            assert status == 200 and result["status"] == "ready", reply
            assert result["box_xyxy"] == [16, 16, 48, 48]
            assert len(result["provenance"]["models"]) == (1 if hint else 2)
            directory = scratch / payload["attempt_id"]
            receipt, png = ((directory / name).read_bytes() for name in ("result.json", "mask.png"))
            descriptor, mask = describe_mask(png, image.size)
            assert np.array_equal(mask, pixels) and descriptor == result["mask"]
            assert receipt == canonical_json(result) and digest(receipt) == reply["result_sha256"]
    print(json.dumps({
        "wheel_hashes": wheel_hashes, "runtime": profile.runtime(),
        "proof": "CPU Torch, pinned image processors, synthetic safetensors, local service and artifacts",
        "model_weights_loaded": False,
    }))


if __name__ == "__main__":
    main()
