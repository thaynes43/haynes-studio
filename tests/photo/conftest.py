from __future__ import annotations

import hashlib
import io
from dataclasses import replace

import pytest
from PIL import Image

from haynes_studio.canonical import Story
from haynes_studio.canonical.model import Principal
from haynes_studio.library import Library
from haynes_studio.library.model import locator_for
from tests.canonical.fixtures import example

PNG = "image/png"
BY = Principal("agent", key_id="key_01M79V9FC00000000000000001")
NOW = "2026-11-24T19:30:00Z"


def base_story() -> Story:
    return Story.from_document(example("valid/story-winter-menu-r4.json"))


@pytest.fixture
def world(tmp_path):
    story = base_story()
    board = story.ordered_boards()[0]
    production = story.production_id
    template = example("valid/asset-version-cast.json")
    documents, files = [], {}
    for suffix, color in [("1", "red"), ("2", "blue"), ("3", "green")]:
        asset = dict(template, id=template["id"][:-1] + suffix,
                     asset_id=template["asset_id"][:-1] + suffix)
        buffer = io.BytesIO()
        sample = Image.new("RGBA", (16, 16), color)
        sample.putpixel((0, 0), (0, 0, 0, 0))
        sample.save(buffer, format="PNG")
        data = buffer.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        locator = locator_for(digest, PNG, production)
        asset["content"] = dict(sha256=digest, bytes=len(data), media_type=PNG,
                                locator=locator, width=16, height=16)
        asset["provenance"] = dict(template["provenance"], source_key=f"fixture:{suffix}")
        asset["legacy"] = None
        path = tmp_path / f"source-{suffix}.png"
        path.write_bytes(data)
        files[locator] = path
        documents.append(asset)
    ids = tuple(doc["id"] for doc in documents)

    def fetch(locator, digest):
        if locator in files:
            return files[locator].read_bytes()
        return None

    def publish(data, media_type):
        digest = hashlib.sha256(data).hexdigest()
        locator = locator_for(digest, media_type, production)
        path = tmp_path / f"{digest}.png"
        if path.exists():
            assert path.read_bytes() == data
        else:
            with path.open("xb") as stream:
                stream.write(data)
        return digest, locator

    photo = replace(board.photo, prompt="The blue figure stands behind the red one.",
                    current_version_id=None, input_asset_version_ids=ids[:2])
    whole = replace(board, photo=photo, method=replace(board.method, layer="whole_frame"))
    return story, whole, Library.from_version_documents(documents), ids, fetch, publish
