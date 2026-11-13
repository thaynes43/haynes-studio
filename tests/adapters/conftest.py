"""Adapter test setup: no test inherits another's ComfyUI prompt in flight."""

from __future__ import annotations

import pytest

from haynes_studio.adapters.comfyui import ImageClient


@pytest.fixture(autouse=True)
def no_comfyui_prompt_in_flight():
    """``ImageClient`` remembers a prompt in flight per process, so each test starts and
    ends with none."""
    ImageClient.clear_in_flight()
    yield
    ImageClient.clear_in_flight()
