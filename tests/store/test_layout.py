"""The D39 layout and locators (contract section 8): ``store.locator_invalid``."""

from __future__ import annotations

import json

import pytest

from haynes_studio.store import (
    LOCATOR_INVALID,
    MEDIA_TYPE_UNSUPPORTED,
    RECORD_INVALID,
    StoreError,
    blob_locator,
    is_locator,
    parse_locator,
    record_path,
)
from haynes_studio.store.layout import parse_record_path
from tests.store.helpers import PRD, RUN
from tests.support.policy import REPO_ROOT

H = "ab" + "0123456789abcdef" * 3 + "0123456789abcd"  # 64 hex digits, starting "ab"


def test_valid_locators_parse():
    library = parse_locator(f"library/sha256/ab/{H}.png")
    assert (library.production_id, library.sha256, library.ext, library.scope) == (None, H, "png", "library")
    assert library.media_type == "image/png"
    production = parse_locator(f"productions/{PRD}/sha256/ab/{H}.wav")
    assert (production.production_id, production.scope, production.media_type) == (PRD, PRD, "audio/wav")
    for ext in ("mp4", "wav", "png", "jpg", "webp", "json"):
        assert is_locator(f"library/sha256/ab/{H}.{ext}")


@pytest.mark.parametrize("locator", [
    "../../etc/passwd",  # the contract's invalid example
    f"/library/sha256/ab/{H}.png",  # absolute
    f"/tmp/store/library/sha256/ab/{H}.png",
    f"library/sha256/ab/../ab/{H}.png",  # ..
    f"library/../library/sha256/ab/{H}.png",
    f"./library/sha256/ab/{H}.png",
    f"library/sha256/./ab/{H}.png",
    f"library//sha256/ab/{H}.png",  # empty component
    f"library/sha256/ab/{H}.png/",  # trailing slash
    f"library\\sha256\\ab\\{H}.png",  # backslashes
    f"library/sha256/ab/{H.upper()}.png",  # upper-case hex
    f"library/sha256/cd/{H}.png",  # fan folder is not h[0:2]
    f"library/sha256/ab/{H[:-1]}.png",  # 63 digits
    f"library/sha256/ab/{H}.gif",  # extension outside the list
    f"library/sha256/ab/{H}.PNG",
    f"library/sha256/ab/{H}",
    f"library/sha256/ab/{H}.png\n",  # a trailing newline ($ alone would accept it)
    f"library/sha256/ab/{H}.png\x00",
    f"productions/prd_bad/sha256/ab/{H}.png",  # not a production ID
    f"productions/{RUN}/sha256/ab/{H}.png",  # an ID of another type
    f"productions/{PRD}/records/{RUN}/voice.json",  # a record path is not a locator
    f".staging/{H}.part",
    f"store/library/sha256/ab/{H}.png",
    f"C:/library/sha256/ab/{H}.png",
    "",
])
def test_anything_outside_the_layout_is_locator_invalid(locator):
    with pytest.raises(StoreError) as caught:
        parse_locator(locator)
    assert caught.value.code == LOCATOR_INVALID
    assert caught.value.status == "invalid"
    assert not is_locator(locator)


@pytest.mark.parametrize("value", [None, 7, b"library/sha256", ["library"]])
def test_a_locator_is_a_string(value):
    with pytest.raises(StoreError) as caught:
        parse_locator(value)
    assert caught.value.code == LOCATOR_INVALID


def test_the_contract_example_locator_is_refused():
    case = json.loads((REPO_ROOT / "docs/contracts/examples/invalid/store-locator-invalid.json")
                      .read_text(encoding="utf-8"))
    assert case["rule"] == LOCATOR_INVALID
    with pytest.raises(StoreError) as caught:
        parse_locator(case["document"]["content"]["locator"])
    assert caught.value.code == case["rule"]


def test_blob_locator_from_scope_hash_and_media_type():
    assert blob_locator("library", H, "image/jpeg") == f"library/sha256/ab/{H}.jpg"
    assert blob_locator(PRD, H, "video/mp4") == f"productions/{PRD}/sha256/ab/{H}.mp4"
    with pytest.raises(StoreError) as caught:
        blob_locator(PRD, H, "image/gif")
    assert caught.value.code == MEDIA_TYPE_UNSUPPORTED
    with pytest.raises(StoreError) as caught:
        blob_locator(PRD, H.upper(), "image/png")
    assert caught.value.code == LOCATOR_INVALID
    with pytest.raises(StoreError) as caught:
        blob_locator("prd_bad", H, "image/png")
    assert caught.value.code == "id.malformed"
    with pytest.raises(StoreError) as caught:
        blob_locator(RUN, H, "image/png")
    assert caught.value.code == "id.type_mismatch"


def test_record_paths():
    path = record_path(PRD, RUN, "segment-brd_01M79V9FC00000000000000001")
    assert path == f"productions/{PRD}/records/{RUN}/segment-brd_01M79V9FC00000000000000001.json"
    assert parse_record_path(path) == (PRD, RUN, "segment-brd_01M79V9FC00000000000000001")
    assert parse_record_path(f"productions/{PRD}/records/{RUN}/../x.json") is None
    for stage in ("", ".", "..", "a/b", "a.b", "-voice", "voice\n", "x" * 129, None):
        with pytest.raises(StoreError) as caught:
            record_path(PRD, RUN, stage)
        assert caught.value.code == RECORD_INVALID
    with pytest.raises(StoreError) as caught:
        record_path(PRD, PRD, "voice")
    assert caught.value.code == "id.type_mismatch"
