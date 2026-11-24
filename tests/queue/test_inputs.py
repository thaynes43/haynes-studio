"""Cold-cache run estimates use the build's rendered cast and chunk clock."""

from types import SimpleNamespace

from haynes_studio.queue import inputs


def test_layered_estimate_counts_rendered_speakers_once_and_skips_narration(monkeypatch):
    board = SimpleNamespace(
        method=SimpleNamespace(layer="layered", motion="s2v"),
        lines=[SimpleNamespace(speaker=name) for name in ("a", "a", "narrator")],
        cast=[SimpleNamespace(slot=name) for name in ("a", "b")],
    )
    prepared = SimpleNamespace(
        story=SimpleNamespace(ordered_boards=lambda: [board]),
        facts=None,
        report=SimpleNamespace(blocking=[]),
    )
    monkeypatch.setattr(inputs, "board_clock", lambda board, facts: SimpleNamespace(frames=119))
    result = inputs.estimate(prepared)
    assert result["methods"] == [{"method": "layered/s2v", "chunks": 2, "gpu_wall_s": [280, 720]}]
    assert result["estimate"]["uncertain"]
