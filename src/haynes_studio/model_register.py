"""The model licence register shipped with Studio, or an explicit local override."""

import os
from importlib.resources import files
from pathlib import Path
from typing import Any

from haynes_studio.jsonio import parse_strict, read_json


def load_model_register(path: str | Path | None = None) -> dict[str, Any]:
    """Read a fresh register independently of the process's working directory.

    An explicit path wins over ``STUDIO_MODEL_REGISTER``. Without either, read
    the single register shipped in the wheel. An unreadable override is an
    error; it never falls back to different licence terms.
    """
    if path is None:
        path = os.environ.get("STUDIO_MODEL_REGISTER")
    document = (read_json(path).document if path is not None else
                parse_strict(files("haynes_studio").joinpath("model_licences.json")
                             .read_text(encoding="utf-8")))
    if not isinstance(document, dict):
        raise ValueError("The model licence register must be a JSON object")
    return document
