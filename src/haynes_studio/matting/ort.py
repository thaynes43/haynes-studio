"""Pinned BiRefNet Lite inference, using an already verified in-memory graph."""

from __future__ import annotations

from importlib import import_module

import numpy as np
from PIL import Image
from scipy.special import expit

from .profile import (
    DIM, INPUT_NAME, MEAN, OUTPUT_NAME, PIN_MISMATCH, PROVIDER, RESPONSE_INVALID,
    RUNTIME_VERSION, STD, MatteError, SessionSettings,
)


OPTIMIZATION_LEVELS = {
    "all": "ORT_ENABLE_ALL",
    "extended": "ORT_ENABLE_EXTENDED",
    "basic": "ORT_ENABLE_BASIC",
    "disabled": "ORT_DISABLE_ALL",
}


class OnnxMatte:
    def __init__(self, graph: bytes, settings: SessionSettings = SessionSettings()):
        # ORT belongs to the matting image; the main Studio installation can
        # import this module without the optional native runtime.
        ort = import_module("onnxruntime")

        if ort.__version__ != RUNTIME_VERSION:
            raise MatteError(PIN_MISMATCH)
        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = settings.cpu_arena
        options.enable_mem_pattern = settings.memory_pattern
        options.graph_optimization_level = getattr(
            ort.GraphOptimizationLevel, OPTIMIZATION_LEVELS[settings.graph_optimization],
        )
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        if settings.arena_growth == "same-as-requested":
            # The CPU EP has no growth option in its provider-options map.
            # Register the CPU arena for this single-session worker process.
            memory = ort.OrtMemoryInfo("Cpu", ort.OrtAllocatorType.ORT_ARENA_ALLOCATOR, 0, ort.OrtMemType.DEFAULT)
            arena = ort.OrtArenaCfg({"arena_extend_strategy": 1})
            ort.create_and_register_allocator(memory, arena)
            options.add_session_config_entry("session.use_env_allocators", "1")
        self.run_options = None
        if settings.shrink_cpu_arena:
            self.run_options = ort.RunOptions()
            self.run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "cpu:0")
        self.session = ort.InferenceSession(graph, sess_options=options, providers=[PROVIDER])
        self.session.disable_fallback()
        inputs, outputs = self.session.get_inputs(), self.session.get_outputs()
        if (self.session.get_providers() != [PROVIDER] or len(inputs) != 1 or len(outputs) != 1
                or not self._matches(inputs[0], INPUT_NAME, [1, 3, DIM, DIM])
                or not self._matches(outputs[0], OUTPUT_NAME, [1, 1, DIM, DIM])):
            raise MatteError(PIN_MISMATCH)

    @staticmethod
    def _matches(node, name: str, shape: list[int]) -> bool:
        return node.name == name and node.type == "tensor(float)" and node.shape == shape

    def __call__(self, rgb: Image.Image) -> np.ndarray:
        image = rgb.resize((DIM, DIM), Image.Resampling.BILINEAR)
        normalized = np.asarray(image, dtype=np.float32) / 255
        normalized -= np.asarray(MEAN, dtype=np.float32)
        normalized /= np.asarray(STD, dtype=np.float32)
        tensor = np.ascontiguousarray(normalized.transpose(2, 0, 1)[None])
        logits, = self.session.run([OUTPUT_NAME], {INPUT_NAME: tensor}, self.run_options)
        if (logits.dtype != np.float32 or logits.shape != (1, 1, DIM, DIM)
                or not np.isfinite(logits).all()):
            raise MatteError(RESPONSE_INVALID)
        return expit(logits[0, 0])
