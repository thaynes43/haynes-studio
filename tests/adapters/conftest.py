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


def forget_wan_process_state():
    """What a new process starts with: ``WanClipClient`` holds no blocking job and no halt
    in memory. Journals are not touched (they are what a new process loads)."""
    from haynes_studio.adapters.wan import WanClipClient

    WanClipClient._unsettled = WanClipClient._unsettled_journal = None
    WanClipClient._halt = WanClipClient._halt_journal = None


@pytest.fixture(autouse=True)
def no_wan_job_in_flight():
    """``WanClipClient`` remembers a blocking job and a halt per process, so each test
    starts and ends with neither (as a new process would)."""
    forget_wan_process_state()
    yield
    forget_wan_process_state()
