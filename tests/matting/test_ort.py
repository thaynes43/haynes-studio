"""Exercise the frozen ONNX interface without importing ORT or any weights."""

import sys
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from haynes_studio.matting.ort import OnnxMatte
from haynes_studio.matting.profile import (
    DIM, INPUT_NAME, MEAN, OUTPUT_NAME, PIN_MISMATCH, PROVIDER, RESPONSE_INVALID,
    RUNTIME_VERSION, STD, MatteError,
)


@pytest.fixture
def fake_ort(monkeypatch):
    class Options(SimpleNamespace):
        def add_session_config_entry(self, key, value):
            entries[key] = value

    entries = {}
    config = SimpleNamespace(
        inputs=[SimpleNamespace(name=INPUT_NAME, shape=[1, 3, DIM, DIM], type="tensor(float)")],
        outputs=[SimpleNamespace(name=OUTPUT_NAME, shape=[1, 1, DIM, DIM], type="tensor(float)")],
        providers=[PROVIDER],
        logits=np.zeros((1, 1, DIM, DIM), dtype=np.float32),
    )

    class Session:
        def __init__(self, graph, *, sess_options, providers):
            assert graph == b"verified"
            assert providers == [PROVIDER]
            assert vars(sess_options) == {
                "execution_mode": "sequential", "intra_op_num_threads": 2,
                "inter_op_num_threads": 1, "enable_cpu_mem_arena": True,
                "enable_mem_pattern": True, "graph_optimization_level": "all",
            }
            assert entries == {
                "session.intra_op.allow_spinning": "0",
                "session.inter_op.allow_spinning": "0",
            }
            self.fallback = True

        def get_providers(self):
            return config.providers

        def get_inputs(self):
            return config.inputs

        def get_outputs(self):
            return config.outputs

        def disable_fallback(self):
            self.fallback = False

        def run(self, outputs, inputs, run_options):
            assert not self.fallback
            assert run_options is None
            assert outputs == [OUTPUT_NAME] and list(inputs) == [INPUT_NAME]
            tensor = inputs[INPUT_NAME]
            assert tensor.shape == (1, 3, DIM, DIM)
            assert tensor.dtype == np.float32 and tensor.flags["C_CONTIGUOUS"]
            means = (np.asarray([255, 0, 127]) / 255 - MEAN) / STD
            np.testing.assert_allclose(tensor[0, :, DIM - 1, 0], means, atol=1e-6)
            return [config.logits]

    module = SimpleNamespace(
        __version__=RUNTIME_VERSION, SessionOptions=Options, InferenceSession=Session,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="all"),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", module)
    return config, module


def test_cpu_tensor_and_sigmoid(fake_ort):
    config, _ = fake_ort
    config.logits[0, 0, 0, :3] = [-1000, 0, 1000]
    source = OnnxMatte(b"verified")
    alpha = source(Image.new("RGB", (64, 72), (255, 0, 127)))
    assert alpha.dtype == np.float32 and alpha.shape == (DIM, DIM)
    assert alpha[0, :3].tolist() == [0, 0.5, 1]


@pytest.mark.parametrize("guard", ["version", "provider", "input", "output", "io_dtype", "io_shape"])
def test_startup_refuses_runtime_or_graph_metadata_mismatch(fake_ort, guard):
    config, module = fake_ort
    if guard == "version":
        module.__version__ = "1.0"
    elif guard == "provider":
        config.providers.append("CUDAExecutionProvider")
    elif guard == "input":
        config.inputs[0].name = "unrecognized"
    elif guard == "output":
        config.outputs[0].name = "unrecognized"
    elif guard == "io_dtype":
        config.inputs[0].type = "tensor(int64)"
    elif guard == "io_shape":
        config.outputs[0].shape[3] = "dynamic_width"
    with pytest.raises(MatteError) as error:
        OnnxMatte(b"verified")
    assert error.value.code == PIN_MISMATCH


@pytest.mark.parametrize("guard", ["nonfinite", "shape", "dtype"])
def test_rejects_bad_raw_logits(fake_ort, guard):
    config, _ = fake_ort
    if guard == "nonfinite":
        config.logits[0, 0, 0, 0] = np.inf
    elif guard == "shape":
        config.logits = config.logits[..., :2]
    else:
        config.logits = config.logits.astype(np.float64)
    with pytest.raises(MatteError) as error:
        OnnxMatte(b"verified")(Image.new("RGB", (64, 72), (255, 0, 127)))
    assert error.value.code == RESPONSE_INVALID
