"""Offline adapters for the pinned Transformers image processors and models."""

from __future__ import annotations

import os
import socket
import sys
from importlib import import_module

import numpy as np

from .inference import Candidate, Grounding
from .profile import MAX_TOKENS, TEXT_FLOOR, THREAD_ENV, SegmentationError


def _deny_network(event, args):
    if event == "socket.__new__" and args[1] != socket.AF_UNIX:
        raise PermissionError("the segmentation process only uses local sockets")


def cpu_runtime():
    # Install before any lazy imports can initialize a Hub or tokenizer cache.
    os.environ.update(THREAD_ENV)
    sys.addaudithook(_deny_network)
    # This is an image-only dependency. Importing Studio's source package
    # should never load or require the ML runtime.
    torch = import_module("torch")

    if torch.version.cuda is not None or torch.version.hip is not None:
        raise SegmentationError("profile_unavailable")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    return torch


class DINO:
    def __init__(self, torch, processor, model):
        self.torch = torch
        self.processor = processor
        self.model = model

    def __call__(self, image, prompt):
        if len(self.processor.tokenizer(prompt, truncation=False, verbose=False)["input_ids"]) > MAX_TOKENS:
            raise SegmentationError("invalid_input")
        inputs = self.processor(images=image, text=prompt, return_tensors="pt")
        height, width = inputs.pixel_values.shape[-2:]
        # Batch one pads to its own resized dimensions in this profile.
        # Reject any change to the pinned preprocessing before rescaling boxes.
        if "pixel_mask" in inputs and not bool(inputs.pixel_mask.all()):
            raise SegmentationError("invalid_output")
        with self.torch.inference_mode():
            output = self.model(**inputs)
            if (not bool(self.torch.isfinite(output.pred_boxes).all())
                    or not bool((self.torch.isfinite(output.logits) | self.torch.isneginf(output.logits)).all())):
                raise SegmentationError("invalid_output")
            # The pinned processor uses strict >. Shift the token floor by
            # one float32 value so an exactly on-floor token still qualifies.
            text_threshold = float(np.nextafter(np.float32(TEXT_FLOOR), np.float32(0)))
            result, = self.processor.post_process_grounded_object_detection(
                output, inputs.input_ids, threshold=0.0, text_threshold=text_threshold,
                target_sizes=[(height, width)],
            )
        candidates = [
            Candidate(tuple(box), score, phrase)
            for box, score, phrase in zip(
                result["boxes"].tolist(), result["scores"].tolist(), result["text_labels"], strict=True,
            )
        ]
        return Grounding(candidates, (width, height), (width, height))


class SAM:
    def __init__(self, torch, processor, model):
        self.torch = torch
        self.processor = processor
        self.model = model

    def __call__(self, image, hint):
        if hint["kind"] == "point":
            prompts = {"input_points": [[[hint["xy"]]]], "input_labels": [[[1]]]}
        else:
            prompts = {"input_boxes": [[hint["xyxy"]]]}
        inputs = self.processor(images=image, return_tensors="pt", **prompts)
        original_sizes = inputs.pop("original_sizes")
        with self.torch.inference_mode():
            output = self.model(**inputs, multimask_output=True)
            logits, = self.processor.post_process_masks(output.pred_masks, original_sizes, binarize=False)
        scores = output.iou_scores
        if logits.ndim != 4 or logits.shape[0] != 1 or scores.ndim != 3 or scores.shape[:2] != (1, 1):
            raise SegmentationError("invalid_output")
        return np.asarray(logits[0]), scores[0, 0].tolist()


def load_models(weights, phase, load_strategy):
    with phase("runtime_import"):
        torch = cpu_runtime()
        transformers = import_module("transformers")

    dino, sam = weights / "dino", weights / "sam"
    options = {"local_files_only": True, "trust_remote_code": False}
    model_options = {
        **options, "use_safetensors": True, "dtype": torch.float32, "attn_implementation": "eager",
        "disable_mmap": load_strategy == "buffered",
    }
    with phase("load_dino"):
        processor = transformers.GroundingDinoProcessor(
            transformers.GroundingDinoImageProcessor.from_pretrained(dino, **options),
            transformers.BertTokenizer.from_pretrained(dino, **options),
        )
        detector = DINO(torch, processor, transformers.GroundingDinoForObjectDetection.from_pretrained(
            dino, disable_custom_kernels=True, **model_options,
        ).eval())
    with phase("load_sam"):
        processor = transformers.Sam2Processor(transformers.Sam2ImageProcessor.from_pretrained(sam, **options))
        segmenter = SAM(torch, processor, transformers.Sam2Model.from_pretrained(sam, **model_options).eval())

    for model in (detector.model, segmenter.model):
        if any(parameter.device.type != "cpu" or parameter.dtype != torch.float32
               for parameter in model.parameters()):
            raise SegmentationError("profile_unavailable")
    return detector, segmenter
