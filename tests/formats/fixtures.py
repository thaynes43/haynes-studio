"""Source-only format recipe inputs."""

from pathlib import Path

from haynes_studio.jsonio import read_json

ROOT = Path(__file__).resolve().parents[2]


def doll_short():
    return read_json(ROOT / "docs/reference/fixtures/doll-short-v1.json").document


def wide():
    return read_json(Path(__file__).with_name("wide-v1.json")).document
