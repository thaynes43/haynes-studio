"""Round-trip tiny random checkpoints through Studio's production loader."""

import json
import sys
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import torch
from PIL import Image
from transformers import (
    BertConfig,
    BertTokenizer,
    GroundingDinoConfig,
    GroundingDinoForObjectDetection,
    GroundingDinoImageProcessor,
    Sam2Config,
    Sam2HieraDetConfig,
    Sam2ImageProcessor,
    Sam2MaskDecoderConfig,
    Sam2Model,
    Sam2PromptEncoderConfig,
    Sam2VisionConfig,
    SwinConfig,
)

from haynes_studio.segmentation.runtime import load_models


IMAGE_SIZE = 64
VOCAB = {token: index for index, token in enumerate(
    ("[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "prop", ".")
)}


def save_dino(path):
    config = GroundingDinoConfig(
        backbone_config=SwinConfig(
            image_size=IMAGE_SIZE, embed_dim=16, window_size=4,
            depths=[1, 1, 1, 1], num_heads=[1, 2, 4, 8], out_indices=[2, 3, 4],
        ),
        text_config=BertConfig(
            vocab_size=len(VOCAB), hidden_size=32, intermediate_size=64,
            num_hidden_layers=1, num_attention_heads=4,
        ),
        d_model=64, max_text_len=16, num_queries=2,
        encoder_layers=1, encoder_attention_heads=4, encoder_ffn_dim=64,
        decoder_layers=2, decoder_attention_heads=4, decoder_ffn_dim=64,
    )
    GroundingDinoForObjectDetection(config).save_pretrained(path)
    GroundingDinoImageProcessor(
        size={"shortest_edge": IMAGE_SIZE, "longest_edge": IMAGE_SIZE},
    ).save_pretrained(path)
    BertTokenizer(vocab=VOCAB).save_pretrained(path)


def save_sam(path):
    config = Sam2Config(
        vision_config=Sam2VisionConfig(
            backbone_config=Sam2HieraDetConfig(
                image_size=IMAGE_SIZE, hidden_size=16,
                blocks_per_stage=[1, 1, 2, 1], embed_dim_per_stage=[16, 32, 64, 128],
                window_size_per_stage=[4, 4, 4, 4], global_attention_blocks=[3],
            ),
            backbone_channel_list=[128, 64, 32, 16],
            backbone_feature_sizes=[[16, 16], [8, 8], [4, 4]], fpn_hidden_size=32,
        ),
        prompt_encoder_config=Sam2PromptEncoderConfig(hidden_size=32, image_size=IMAGE_SIZE),
        mask_decoder_config=Sam2MaskDecoderConfig(
            hidden_size=32, mlp_dim=64, num_hidden_layers=1,
            num_attention_heads=4, iou_head_hidden_dim=32,
        ),
    )
    Sam2Model(config).save_pretrained(path)
    Sam2ImageProcessor(size={"height": IMAGE_SIZE, "width": IMAGE_SIZE}).save_pretrained(path)


def main(strategy):
    torch.manual_seed(0)
    with TemporaryDirectory() as directory:
        weights = Path(directory)
        save_dino(weights / "dino")
        save_sam(weights / "sam")
        detector, segmenter = load_models(weights, lambda _: nullcontext(), strategy)
        assert isinstance(detector.model, GroundingDinoForObjectDetection)
        assert isinstance(segmenter.model, Sam2Model)
        assert detector.model.config.disable_custom_kernels is True
        assert all(model.config._attn_implementation == "eager"
                   for model in (detector.model, segmenter.model))

        image = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), (90, 100, 110))
        grounding = detector(image, "prop.")
        logits, scores = segmenter(image, {"kind": "point", "xy": [24, 24]})
        assert len(grounding.candidates) == detector.model.config.num_queries
        assert np.isfinite([candidate.box for candidate in grounding.candidates]).all()
        assert np.isfinite([candidate.score for candidate in grounding.candidates]).all()
        assert logits.shape == (3, IMAGE_SIZE, IMAGE_SIZE) and len(scores) == 3
        assert np.isfinite(logits).all() and np.isfinite(scores).all()

    print(json.dumps({
        "proof": "Production load_models and one forward per model with the pinned wheels and tiny random safetensors.",
        "classes": ["GroundingDinoForObjectDetection", "Sam2Model"],
        "local_files_only": True, "trust_remote_code": False, "use_safetensors": True,
        "disable_mmap": strategy == "buffered", "attn_implementation": "eager", "dtype": "float32",
        "dino_disable_custom_kernels": True,
        "unverified": "Publisher checkpoints were absent. Their compatibility and output quality require install evidence.",
    }))


if __name__ == "__main__":
    main(sys.argv[1])
