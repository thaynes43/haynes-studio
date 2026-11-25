"""Run OpenCV DNN Super Resolution against an already verified graph."""

import os

import numpy as np
from PIL import Image

from .profile import PIN_MISMATCH, RESPONSE_INVALID, SETTINGS, THREADS, UpscaleError, runtime_identity


class Fsrcnn:
    def __init__(self, graph: bytes, *, identity: bytes, settings: str):
        import cv2

        if (runtime_identity() != identity
                or os.environ.get("GLIBC_TUNABLES", "") != SETTINGS[settings]):
            raise UpscaleError(PIN_MISMATCH)
        cv2.setNumThreads(THREADS)
        cv2.ocl.setUseOpenCL(False)
        if cv2.getNumThreads() != THREADS or cv2.ocl.useOpenCL():
            raise UpscaleError(PIN_MISMATCH)
        self.cv2 = cv2
        self.model = cv2.dnn_superres.DnnSuperResImpl_create()
        # OpenCV's Python binding only accepts a path. Read the verified bytes
        # from an anonymous Linux file; never give the runtime a mutable NFS path.
        descriptor = os.memfd_create("studio-fsrcnn", os.MFD_CLOEXEC)
        with os.fdopen(descriptor, "wb") as model:
            model.write(graph)
            model.flush()
            self.model.readModel(f"/proc/self/fd/{descriptor}")
        self.model.setModel("fsrcnn", 2)
        self.model.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.model.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        if self.model.getAlgorithm() != "fsrcnn" or self.model.getScale() != 2:
            raise UpscaleError(PIN_MISMATCH)
        # Exercise decoding, inference and the tensor-to-image conversion before readiness.
        self(Image.new("RGB", (16, 16)))

    def __call__(self, rgb: Image.Image) -> Image.Image:
        cv2 = self.cv2
        bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
        enlarged = self.model.upsample(bgr)
        if enlarged.dtype != np.uint8 or enlarged.shape != (rgb.height * 2, rgb.width * 2, 3):
            raise UpscaleError(RESPONSE_INVALID)
        return Image.fromarray(cv2.cvtColor(enlarged, cv2.COLOR_BGR2RGB))
