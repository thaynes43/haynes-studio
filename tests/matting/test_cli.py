"""Verify serving provenance and smoke settings without loading a graph."""

import json
import sys
from unittest.mock import Mock

import pytest

from haynes_studio.matting import smoke
from haynes_studio.matting.__main__ import main
from haynes_studio.matting.profile import IMAGE_REPOSITORY, SessionSettings


def test_profile_records_serving_settings(monkeypatch, capsys):
    monkeypatch.setenv("STUDIO_MATTING_IMAGE", IMAGE_REPOSITORY + "@sha256:" + "f" * 64)
    monkeypatch.setenv("STUDIO_MATTING_REVISION", "1" * 40)
    monkeypatch.setattr(sys, "argv", ["studio-matting", "profile"])
    assert main() == 0
    manifest = json.loads(json.loads(capsys.readouterr().out)["manifest"])
    assert manifest["parameters"]["session"]["cpu_arena"] is False
    assert manifest["memory"] == {
        "schema": "studio.matting-resources/v1", "request_gib": 8, "limit_gib": 10,
    }


@pytest.mark.parametrize(("flags", "expected"), [
    ([], SessionSettings()),
    (["--no-cpu-arena"], SessionSettings()),
    (["--cpu-arena"], SessionSettings(cpu_arena=True)),
    (["--cpu-arena", "--arena-growth", "same-as-requested", "--shrink-cpu-arena"],
     SessionSettings(cpu_arena=True, arena_growth="same-as-requested", shrink_cpu_arena=True)),
])
def test_smoke_settings(monkeypatch, flags, expected):
    run = Mock(return_value={"passed": True})
    monkeypatch.setattr(smoke, "smoke", run)
    monkeypatch.setattr(sys, "argv", ["studio-matting", "smoke", *flags])
    assert main() == 0
    assert run.call_args.args[2] == expected


@pytest.mark.parametrize("flags", [
    ["--arena-growth", "same-as-requested"],
    ["--no-cpu-arena", "--shrink-cpu-arena"],
])
def test_smoke_refuses_arena_options_with_arena_off(monkeypatch, capsys, flags):
    run = Mock()
    monkeypatch.setattr(smoke, "smoke", run)
    monkeypatch.setattr(sys, "argv", ["studio-matting", "smoke", *flags])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "arena growth and shrinkage require the CPU arena" in capsys.readouterr().err
    run.assert_not_called()
